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
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { useAuth } from '@/src/contexts/AuthContext';
import { api, Account, MessageListItem } from '@/src/services/api';

type Filter = 'all' | 'unread' | 'pec' | 'trash';

const AUTO_SYNC_MS = 90_000;

const FILTER_LABELS: Record<Filter, string> = {
  all: 'Tutte',
  unread: 'Non lette',
  pec: 'PEC',
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
  const { userEmail, masterPassword, logout, enableNotifications } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<MessageListItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState('');
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [refreshing, setRefreshing] = useState(false);
  const [syncHint, setSyncHint] = useState<string | null>(null);
  const [pushHint, setPushHint] = useState<{ ok: boolean; text: string } | null>(null);
  const [pushBusy, setPushBusy] = useState(false);
  const lastCount = useRef(0);

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
      unread: filter === 'unread' ? true : undefined,
      pec: filter === 'pec' ? true : undefined,
      folder: filter === 'trash' ? 'trash' : undefined,
    });
    setItems(data.items);
    lastCount.current = data.total ?? data.items.length;
  }, [userEmail, masterPassword, q, filter, accountId]);

  const runSync = useCallback(
    async (silent = false) => {
      if (!userEmail || !masterPassword) return;
      try {
        const res: any = await api.syncRun(userEmail, masterPassword);
        const n = res?.messages_inserted ?? 0;
        if (n > 0) {
          setSyncHint(`${n} nuov${n === 1 ? 'a' : 'e'} email sincronizzat${n === 1 ? 'a' : 'e'}`);
          if (
            !silent &&
            Platform.OS === 'web' &&
            typeof Notification !== 'undefined' &&
            Notification.permission === 'granted'
          ) {
            try {
              new Notification(n === 1 ? 'Nuova email' : `${n} nuove email`, {
                body: 'Inbox aggiornata',
                icon: '/pwa/icon-192.png',
                tag: 'new-mail-local',
              });
            } catch (_) {}
          }
        } else if (!silent) {
          setSyncHint('Inbox aggiornata');
        }
        if (res?.errors?.length && !silent) {
          Alert.alert('Sync parziale', res.errors.join('\n'));
        }
        await load();
      } catch (e: any) {
        if (!silent) Alert.alert('Sync', e.message);
        setSyncHint(e.message);
      }
    },
    [userEmail, masterPassword, load],
  );

  useFocusEffect(
    useCallback(() => {
      loadAccounts().catch(() => undefined);
      load().catch((e) => Alert.alert('Errore', e.message));
      runSync(true).catch(() => undefined);
    }, [load, loadAccounts, runSync]),
  );

  useEffect(() => {
    if (!userEmail || !masterPassword) return;
    const id = setInterval(() => {
      runSync(true).catch(() => undefined);
    }, AUTO_SYNC_MS);
    return () => clearInterval(id);
  }, [userEmail, masterPassword, runSync]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await runSync(false);
    } finally {
      setRefreshing(false);
    }
  };

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

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Mail Manager</Text>
        <View style={styles.headerActions}>
          <TouchableOpacity onPress={() => router.push('/compose')}>
            <Text style={styles.link}>Scrivi</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => router.push('/accounts')}>
            <Text style={styles.link}>Account</Text>
          </TouchableOpacity>
          {Platform.OS === 'web' ? (
            <TouchableOpacity onPress={onEnableNotifications} disabled={pushBusy}>
              <Text style={styles.link}>{pushBusy ? '…' : 'Notifiche'}</Text>
            </TouchableOpacity>
          ) : null}
          <TouchableOpacity onPress={() => logout()}>
            <Text style={styles.linkMuted}>Esci</Text>
          </TouchableOpacity>
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
        {(['all', 'unread', 'pec', 'trash'] as Filter[]).map((f) => (
          <TouchableOpacity
            key={f}
            style={[styles.chip, filter === f && styles.chipOn]}
            onPress={() => setFilter(f)}
          >
            <Text style={[styles.chipText, filter === f && styles.chipTextOn]}>
              {FILTER_LABELS[f]}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <View style={styles.accountFilterWrap}>
        {Platform.OS === 'web'
          ? createElement(
              'select',
              {
                value: accountId,
                onChange: (e: any) => setAccountId(e.target.value || ''),
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

      <FlatList
        data={items}
        keyExtractor={(i) => i.id}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#4ecdc4" />
        }
        contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
        ListEmptyComponent={
          <Text style={styles.empty}>
            {filter === 'trash'
              ? 'Cestino vuoto.'
              : 'Nessuna email. Aggiungi una casella in Account: la sync automatica parte ogni ~2 minuti (e all’apertura inbox). Scorri in basso per forzare.'}
          </Text>
        }
        renderItem={({ item }) => (
          <TouchableOpacity
            style={[styles.card, !item.flags?.seen && styles.cardUnread]}
            onPress={() => router.push({ pathname: '/message', params: { id: item.id } })}
          >
            <View style={styles.cardTop}>
              <Text style={styles.from} numberOfLines={1}>
                {item.from}
              </Text>
              {item.is_pec ? (
                <View style={styles.pecBadge}>
                  <Text style={styles.pecText}>PEC</Text>
                </View>
              ) : null}
            </View>
            <Text style={styles.subject} numberOfLines={1}>
              {item.subject || '(senza oggetto)'}
            </Text>
            <Text style={styles.snippet} numberOfLines={2}>
              {item.snippet}
            </Text>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0b1220' },
  header: {
    paddingTop: 52,
    paddingHorizontal: 16,
    paddingBottom: 8,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  title: { color: '#fff', fontSize: 22, fontWeight: '700' },
  headerActions: {
    flexDirection: 'row',
    gap: 12,
    alignItems: 'center',
    flexWrap: 'wrap',
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
  cardUnread: { borderLeftWidth: 3, borderLeftColor: '#4ecdc4' },
  cardTop: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  from: { color: '#fff', fontWeight: '600', flex: 1 },
  pecBadge: {
    backgroundColor: '#e040a0',
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  pecText: { color: '#fff', fontSize: 11, fontWeight: '700' },
  subject: { color: '#ddd', marginTop: 4 },
  snippet: { color: '#888', marginTop: 4, fontSize: 13 },
});
