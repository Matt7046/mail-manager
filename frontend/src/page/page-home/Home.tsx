import React, { createElement, useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  TextInput,
  RefreshControl,
  Alert,
  Platform,
  Linking,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { useAuth } from '@/src/contexts/AuthContext';
import { api, Account, MessageListItem } from '@/src/services/api';

type FolderTab = 'inbox' | 'sent' | 'trash';

const AUTO_SYNC_MS = 90_000;
const PULL_THRESHOLD = 72;
const PULL_MAX = 120;
const PERSONALITY_URL = 'https://colorsdev.tech/personality';

const FOLDER_LABELS: Record<FolderTab, string> = {
  inbox: 'Ricevute',
  sent: 'Inviate',
  trash: 'Cestino',
};

function feedback(title: string, message: string) {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    window.alert(`${title}\n\n${message}`);
  } else {
    Alert.alert(title, message);
  }
}

export default function Home() {
  const {
    userEmail,
    masterPassword,
    isReady,
    logout,
    enableNotifications,
    isBiometricEnabled,
    enableBiometric,
    disableBiometric,
  } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<MessageListItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState('');
  const [q, setQ] = useState('');
  const [folder, setFolder] = useState<FolderTab>('inbox');
  const [onlyUnread, setOnlyUnread] = useState(false);
  const [onlyPec, setOnlyPec] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [pullPx, setPullPx] = useState(0);
  const [syncHint, setSyncHint] = useState<string | null>(null);
  const [pushHint, setPushHint] = useState<{ ok: boolean; text: string } | null>(null);
  const [pushBusy, setPushBusy] = useState(false);
  const lastCount = useRef(0);
  const atTopRef = useRef(true);
  const pullActiveRef = useRef(false);
  const pullStartYRef = useRef(0);
  const pullDistRef = useRef(0);
  const refreshingRef = useRef(false);
  const wheelAccRef = useRef(0);
  const listWrapRef = useRef<View>(null);

  // Evita inbox vuota / "account non collegati" se si apre /home senza vault sbloccato
  useEffect(() => {
    if (!isReady) return;
    if (!userEmail || !masterPassword) {
      router.replace('/login');
    }
  }, [isReady, userEmail, masterPassword, router]);

  const loadAccounts = useCallback(async () => {
    if (!userEmail || !masterPassword) return;
    const list = await api.listAccounts(userEmail, masterPassword);
    setAccounts(list);
    setAccountId((prev) => (prev && !list.some((a) => a.id === prev) ? '' : prev));
  }, [userEmail, masterPassword]);

  const load = useCallback(async () => {
    if (!userEmail || !masterPassword) return;
    const data = await api.listMessages({
      email: userEmail,
      master_password: masterPassword,
      account: accountId || undefined,
      q: q.trim() || undefined,
      unread: onlyUnread ? true : undefined,
      pec: onlyPec ? true : undefined,
      folder,
    });
    setItems(data.items);
    lastCount.current = data.total ?? data.items.length;
  }, [userEmail, masterPassword, q, folder, onlyUnread, onlyPec, accountId]);

  const loadRef = useRef(load);
  loadRef.current = load;

  const runSync = useCallback(
    async (silent = false) => {
      if (!userEmail || !masterPassword) return;
      try {
        const res: any = await api.syncRun(userEmail, masterPassword);
        const n = res?.messages_inserted ?? 0;
        if (n > 0) {
          setSyncHint(`${n} nuov${n === 1 ? 'a' : 'e'} email sincronizzat${n === 1 ? 'a' : 'e'}`);
        } else if (!silent) {
          setSyncHint('Inbox aggiornata');
        }
        if (res?.errors?.length && !silent) {
          Alert.alert('Sync parziale', res.errors.join('\n'));
        }
        await loadRef.current();
      } catch (e: any) {
        if (!silent) Alert.alert('Sync', e.message);
        setSyncHint(e.message);
      }
    },
    [userEmail, masterPassword],
  );

  // Cambio filtri → solo lista messaggi (veloce). Mai sync IMAP qui.
  useEffect(() => {
    if (!userEmail || !masterPassword) return;
    load().catch((e) => Alert.alert('Errore', e.message));
  }, [load, userEmail, masterPassword]);

  // Sync IMAP solo all'ingresso in Home (e pull-to-refresh / intervallo)
  useFocusEffect(
    useCallback(() => {
      loadAccounts().catch(() => undefined);
      let force = false;
      try {
        force = sessionStorage.getItem('mm_force_sync') === '1';
        if (force) sessionStorage.removeItem('mm_force_sync');
      } catch {
        /* ignore */
      }
      runSync(!force).catch(() => undefined);
    }, [loadAccounts, runSync]),
  );

  useEffect(() => {
    if (!userEmail || !masterPassword) return;
    const id = setInterval(() => {
      runSync(true).catch(() => undefined);
    }, AUTO_SYNC_MS);
    return () => clearInterval(id);
  }, [userEmail, masterPassword, runSync]);

  const onRefresh = useCallback(async () => {
    if (refreshingRef.current) return;
    refreshingRef.current = true;
    setRefreshing(true);
    setPullPx(0);
    pullDistRef.current = 0;
    wheelAccRef.current = 0;
    try {
      await runSync(false);
    } finally {
      refreshingRef.current = false;
      setRefreshing(false);
    }
  }, [runSync]);

  const resetPull = useCallback(() => {
    pullActiveRef.current = false;
    pullDistRef.current = 0;
    wheelAccRef.current = 0;
    setPullPx(0);
  }, []);

  const finishPull = useCallback(() => {
    const dist = pullDistRef.current;
    pullActiveRef.current = false;
    if (dist >= PULL_THRESHOLD && !refreshingRef.current) {
      void onRefresh();
    } else {
      resetPull();
    }
  }, [onRefresh, resetPull]);

  const onListScroll = useCallback(
    (e: any) => {
      const y = e?.nativeEvent?.contentOffset?.y ?? 0;
      atTopRef.current = y <= 2;
      if (y > 2 && pullDistRef.current > 0) {
        resetPull();
      }
    },
    [resetPull],
  );

  const onWebWheel = useCallback(
    (e: any) => {
      if (Platform.OS !== 'web' || refreshingRef.current) return;
      const deltaY = e?.deltaY ?? e?.nativeEvent?.deltaY ?? 0;
      if (!atTopRef.current) {
        wheelAccRef.current = 0;
        return;
      }
      if (deltaY >= 0) {
        if (wheelAccRef.current > 0) {
          wheelAccRef.current = Math.max(0, wheelAccRef.current - deltaY * 0.35);
          pullDistRef.current = wheelAccRef.current;
          setPullPx(Math.min(wheelAccRef.current, PULL_MAX));
        }
        return;
      }
      wheelAccRef.current = Math.min(PULL_MAX, wheelAccRef.current + Math.abs(deltaY) * 0.45);
      pullDistRef.current = wheelAccRef.current;
      setPullPx(wheelAccRef.current);
      if (wheelAccRef.current >= PULL_THRESHOLD) {
        e?.preventDefault?.();
        void onRefresh();
      }
    },
    [onRefresh],
  );

  // Web: FlatList cattura spesso touch/wheel — listener in capture sul wrap + scroll interno
  useEffect(() => {
    if (Platform.OS !== 'web' || typeof document === 'undefined') return;
    let targets: HTMLElement[] = [];
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];

    const resolveDom = (node: unknown): HTMLElement | null => {
      if (!node) return null;
      if (typeof HTMLElement !== 'undefined' && node instanceof HTMLElement) return node;
      const anyNode = node as any;
      if (anyNode?.nodeType === 1) return anyNode as HTMLElement;
      if (anyNode?._nativeNode?.nodeType === 1) return anyNode._nativeNode as HTMLElement;
      return null;
    };

    const detach = () => {
      for (const el of targets) {
        const cleanup = (el as any).__mmPullCleanup;
        if (typeof cleanup === 'function') cleanup();
      }
      targets = [];
    };

    const bind = (el: HTMLElement) => {
      if ((el as any).__mmPullCleanup) return;
      const onTouchStart = (ev: TouchEvent) => {
        if (!atTopRef.current || refreshingRef.current) return;
        const t = ev.touches[0];
        if (!t) return;
        pullActiveRef.current = true;
        pullStartYRef.current = t.clientY;
        pullDistRef.current = 0;
      };
      const onTouchMove = (ev: TouchEvent) => {
        if (!pullActiveRef.current || refreshingRef.current) return;
        if (!atTopRef.current) {
          resetPull();
          return;
        }
        const t = ev.touches[0];
        if (!t) return;
        const dist = Math.max(0, (t.clientY - pullStartYRef.current) * 0.55);
        pullDistRef.current = dist;
        setPullPx(Math.min(dist, PULL_MAX));
        if (dist > 10) ev.preventDefault();
      };
      const onTouchEnd = () => {
        if (!pullActiveRef.current) return;
        finishPull();
      };
      const onWheel = (ev: WheelEvent) => onWebWheel(ev);

      el.addEventListener('touchstart', onTouchStart, { passive: true, capture: true });
      el.addEventListener('touchmove', onTouchMove, { passive: false, capture: true });
      el.addEventListener('touchend', onTouchEnd, { capture: true });
      el.addEventListener('touchcancel', onTouchEnd, { capture: true });
      el.addEventListener('wheel', onWheel, { passive: false, capture: true });

      (el as any).__mmPullCleanup = () => {
        el.removeEventListener('touchstart', onTouchStart, true);
        el.removeEventListener('touchmove', onTouchMove, true);
        el.removeEventListener('touchend', onTouchEnd, true);
        el.removeEventListener('touchcancel', onTouchEnd, true);
        el.removeEventListener('wheel', onWheel, true);
        delete (el as any).__mmPullCleanup;
      };
      targets.push(el);
    };

    const attach = () => {
      if (cancelled) return;
      detach();
      const wrap =
        resolveDom(listWrapRef.current) ||
        (document.querySelector('[data-mm-inbox-list]') as HTMLElement | null);
      if (!wrap) return;
      bind(wrap);
      const scrollables = wrap.querySelectorAll<HTMLElement>(
        '[data-testid="scrollView"], [style*="overflow"], div',
      );
      for (const el of Array.from(scrollables)) {
        const style = window.getComputedStyle(el);
        const oy = style.overflowY;
        if (oy === 'auto' || oy === 'scroll' || oy === 'overlay') {
          bind(el);
          break;
        }
      }
    };

    timers.push(setTimeout(attach, 0));
    timers.push(setTimeout(attach, 250));
    timers.push(setTimeout(attach, 800));

    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
      detach();
    };
  }, [finishPull, onWebWheel, resetPull, userEmail, masterPassword, items.length]);

  const pullLabel = refreshing
    ? 'Sincronizzazione…'
    : pullPx >= PULL_THRESHOLD
      ? 'Rilascia per aggiornare'
      : 'Scorri per aggiornare · o tocca qui';

  const onEnableNotifications = async () => {
    if (pushBusy) return;
    setPushBusy(true);
    setPushHint(null);
    try {
      const res = await enableNotifications();
      setPushHint({ ok: res.ok, text: res.message });
      feedback(res.ok ? 'Notifiche' : 'Notifiche', res.message);
    } catch (e: any) {
      const text = e?.message || 'Attivazione fallita';
      setPushHint({ ok: false, text });
      feedback('Notifiche', text);
    } finally {
      setPushBusy(false);
    }
  };

  const onToggleBiometric = async () => {
    try {
      if (isBiometricEnabled) {
        await disableBiometric();
        feedback('Biometrica', 'Accesso biometrico disabilitato');
      } else {
        await enableBiometric();
        feedback('Biometrica', 'Accesso biometrico abilitato (Windows Hello / Face ID)');
      }
    } catch (e: any) {
      feedback('Biometrica', e?.message || 'Operazione fallita');
    }
  };

  if (!isReady || !userEmail || !masterPassword) {
    return (
      <View style={[styles.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <Text style={{ color: '#888' }}>Caricamento…</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Mail Manager</Text>
        <View style={styles.headerActionsCol}>
          <View style={styles.headerActions}>
            {Platform.OS === 'web' ? (
              <TouchableOpacity onPress={onEnableNotifications} disabled={pushBusy}>
                <Text style={styles.link}>{pushBusy ? '…' : 'Notifiche'}</Text>
              </TouchableOpacity>
            ) : null}
            <TouchableOpacity onPress={onToggleBiometric}>
              <Text style={isBiometricEnabled ? styles.link : styles.linkMuted}>
                {isBiometricEnabled ? 'Biometria ON' : 'Biometria'}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={async () => {
                await logout();
                router.replace('/login');
              }}
            >
              <Text style={styles.linkMuted}>Esci</Text>
            </TouchableOpacity>
          </View>
          <View style={styles.headerActions}>
            <TouchableOpacity onPress={() => router.push('/compose')}>
              <Text style={styles.link}>Scrivi</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => router.push('/accounts')}>
              <Text style={styles.link}>Account</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => Linking.openURL(PERSONALITY_URL)}>
              <Text style={styles.link}>Personalità</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>

      {syncHint ? <Text style={styles.hint}>{syncHint}</Text> : null}
      {pushHint ? (
        <Text style={pushHint.ok ? styles.pushOk : styles.pushErr}>{pushHint.text}</Text>
      ) : null}

      <TextInput
        style={styles.search}
        placeholder="Cerca…"
        placeholderTextColor="#666"
        value={q}
        onChangeText={setQ}
        onSubmitEditing={() => load().catch(() => undefined)}
      />

      <View style={styles.filters}>
        {(['inbox', 'sent', 'trash'] as FolderTab[]).map((f) => (
          <TouchableOpacity
            key={f}
            style={[styles.chip, folder === f && styles.chipOn]}
            onPress={() => setFolder(f)}
          >
            <Text style={[styles.chipText, folder === f && styles.chipTextOn]}>
              {FOLDER_LABELS[f]}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      <View style={styles.filters}>
        <TouchableOpacity
          style={[styles.chip, onlyUnread && styles.chipOn]}
          onPress={() => setOnlyUnread((v) => !v)}
        >
          <Text style={[styles.chipText, onlyUnread && styles.chipTextOn]}>Non lette</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.chip, onlyPec && styles.chipOn]}
          onPress={() => setOnlyPec((v) => !v)}
        >
          <Text style={[styles.chipText, onlyPec && styles.chipTextOn]}>PEC</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.accountFilterWrap}>
        {Platform.OS === 'web'
          ? createElement(
              'select',
              {
                value: accountId,
                onChange: (e: any) => {
                  const v = String(e?.target?.value ?? '');
                  setAccountId(v);
                },
                style: {
                  width: '100%',
                  padding: 12,
                  borderRadius: 12,
                  backgroundColor: '#16213e',
                  color: '#fff',
                  border: '1px solid #2a3a5c',
                  fontSize: 14,
                },
              },
              createElement('option', { key: 'all', value: '' }, 'Tutti gli account'),
              ...accounts.map((a) =>
                createElement(
                  'option',
                  { key: a.id, value: a.id },
                  a.label ? `${a.label} — ${a.address}` : a.address,
                ),
              ),
            )
          : (
            <View style={styles.accountChips}>
              <TouchableOpacity
                style={[styles.chip, !accountId && styles.chipOn]}
                onPress={() => setAccountId('')}
              >
                <Text style={[styles.chipText, !accountId && styles.chipTextOn]}>
                  Tutti gli account
                </Text>
              </TouchableOpacity>
              {accounts.map((a) => (
                <TouchableOpacity
                  key={a.id}
                  style={[styles.chip, accountId === a.id && styles.chipOn]}
                  onPress={() => setAccountId(a.id)}
                >
                  <Text style={[styles.chipText, accountId === a.id && styles.chipTextOn]}>
                    {a.address}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          )}
      </View>

      <View
        ref={listWrapRef}
        style={styles.listWrap}
        {...(Platform.OS === 'web'
          ? ({
              // marker per listener DOM (RefreshControl su web spesso non funziona)
              'data-mm-inbox-list': '1',
            } as any)
          : {})}
      >
        <FlatList
          data={items}
          keyExtractor={(i) => i.id}
          onScroll={onListScroll}
          scrollEventThrottle={16}
          refreshControl={
            Platform.OS === 'web' ? undefined : (
              <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#4ecdc4" />
            )
          }
          contentContainerStyle={{ padding: 16, paddingBottom: 40, flexGrow: 1 }}
          ListHeaderComponent={
            <TouchableOpacity
              activeOpacity={0.7}
              disabled={refreshing}
              onPress={() => {
                if (!refreshingRef.current) void onRefresh();
              }}
              style={[
                styles.pullHeader,
                {
                  height: refreshing ? 40 : Math.max(32, pullPx > 0 ? 32 + pullPx * 0.25 : 32),
                  opacity: refreshing || pullPx > 12 ? 1 : 0.7,
                },
              ]}
            >
              <Text style={styles.pullText}>{pullLabel}</Text>
            </TouchableOpacity>
          }
          ListEmptyComponent={
            <Text style={styles.empty}>
              {!userEmail || !masterPassword
                ? 'Sessione non attiva. Reindirizzamento al login…'
                : folder === 'trash'
                  ? 'Cestino vuoto.'
                : folder === 'sent'
                  ? onlyPec
                    ? 'Nessuna PEC inviata con questi filtri.'
                    : 'Nessuna email inviata ancora. Scorri in basso per sincronizzare la cartella Sent dal provider.'
                  : accounts.length === 0
                      ? 'Nessun account collegato. Apri Account e aggiungi una casella email.'
                      : onlyPec
                        ? 'Nessuna PEC ricevuta con questi filtri.'
                        : 'Nessuna email ricevuta. Scorri (o tocca) per sincronizzare — sync automatica ogni ~90s.'}
            </Text>
          }
          renderItem={({ item }) => {
            const isSent =
              folder === 'sent' || (item.folder || '').toLowerCase() === 'sent';
            const seenFlag = item.flags?.seen;
            const isUnread =
              !isSent &&
              !(seenFlag === true || seenFlag === 1 || seenFlag === '1' || seenFlag === 'true');
            const peer = isSent
              ? (item.to?.length ? item.to.join(', ') : '—')
              : item.from;
            return (
            <TouchableOpacity
              style={[styles.card, isUnread && styles.cardUnread]}
              onPress={() => {
                // Optimistic: togli NEW subito (il GET messaggio conferma sul server)
                if (isUnread) {
                  setItems((prev) =>
                    prev.map((x) =>
                      x.id === item.id
                        ? { ...x, flags: { ...(x.flags || {}), seen: true } }
                        : x,
                    ),
                  );
                }
                router.push({ pathname: '/message', params: { id: item.id } });
              }}
            >
              <View style={styles.cardTop}>
                <Text style={[styles.from, isUnread && styles.fromUnread]} numberOfLines={1}>
                  {isSent ? `A: ${peer}` : peer}
                </Text>
                <View style={styles.badges}>
                  {isUnread ? (
                    <View style={styles.newBadge}>
                      <Text style={styles.newText}>NEW</Text>
                    </View>
                  ) : null}
                  {item.is_pec ? (
                    <View style={styles.pecBadge}>
                      <Text style={styles.pecText}>PEC</Text>
                    </View>
                  ) : null}
                </View>
              </View>
              <Text style={[styles.subject, isUnread && styles.subjectUnread]} numberOfLines={1}>
                {item.subject || '(senza oggetto)'}
              </Text>
              <Text style={[styles.snippet, isUnread && styles.snippetUnread]} numberOfLines={2}>
                {item.snippet}
              </Text>
            </TouchableOpacity>
            );
          }}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0b1220' },
  listWrap: { flex: 1 },
  pullHeader: {
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
  },
  pullText: { color: '#7a8aaa', fontSize: 12, fontWeight: '600' },
  header: {
    paddingTop: 52,
    paddingHorizontal: 16,
    paddingBottom: 8,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  title: { color: '#fff', fontSize: 22, fontWeight: '700', paddingTop: 2 },
  headerActionsCol: {
    alignItems: 'flex-end',
    gap: 8,
  },
  headerActions: {
    flexDirection: 'row',
    gap: 12,
    alignItems: 'center',
    justifyContent: 'flex-end',
  },
  link: { color: '#4ecdc4', fontWeight: '600' },
  linkMuted: { color: '#888' },
  hint: { color: '#f0c674', paddingHorizontal: 16, marginBottom: 6, fontSize: 13 },
  pushOk: { color: '#4ecdc4', paddingHorizontal: 16, marginBottom: 6, fontSize: 13 },
  pushErr: { color: '#ff8a8a', paddingHorizontal: 16, marginBottom: 6, fontSize: 13 },
  search: {
    marginHorizontal: 16,
    backgroundColor: '#16213e',
    borderRadius: 12,
    padding: 12,
    color: '#fff',
    marginBottom: 8,
  },
  filters: {
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 16,
    marginBottom: 8,
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  accountFilterWrap: {
    marginHorizontal: 16,
    marginBottom: 8,
  },
  accountChips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 14,
    backgroundColor: '#16213e',
  },
  chipOn: { backgroundColor: '#4ecdc4' },
  chipText: { color: '#aaa', fontSize: 13 },
  chipTextOn: { color: '#0b1220', fontWeight: '700' },
  empty: { color: '#666', textAlign: 'center', marginTop: 48, paddingHorizontal: 24 },
  card: {
    backgroundColor: '#16213e',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  cardUnread: {
    backgroundColor: '#1c3558',
    borderLeftWidth: 4,
    borderLeftColor: '#4ecdc4',
  },
  cardTop: { flexDirection: 'row', justifyContent: 'space-between', gap: 8, alignItems: 'center' },
  badges: { flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 0 },
  from: { color: '#c5cdd8', fontWeight: '600', flex: 1 },
  fromUnread: { color: '#fff', fontWeight: '800' },
  newBadge: {
    backgroundColor: '#4ecdc4',
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  newText: { color: '#0b1220', fontSize: 11, fontWeight: '800', letterSpacing: 0.3 },
  pecBadge: {
    backgroundColor: '#e040a0',
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  pecText: { color: '#fff', fontSize: 11, fontWeight: '700' },
  subject: { color: '#9aa3b2', marginTop: 4 },
  subjectUnread: { color: '#fff', fontWeight: '700' },
  snippet: { color: '#666', marginTop: 4, fontSize: 13 },
  snippetUnread: { color: '#a8b4c4' },
});
