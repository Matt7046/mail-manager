import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Platform,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { useAuth } from '@/src/contexts/AuthContext';
import { api, Account } from '@/src/services/api';

type Provider = 'gmail' | 'outlook' | 'aruba' | 'legalmail' | 'postecert' | 'intesi' | 'other';

const PRESETS: Record<
  Provider,
  { imap_host: string; imap_port: number; smtp_host: string; smtp_port: number; hint?: string }
> = {
  gmail: {
    imap_host: 'imap.gmail.com',
    imap_port: 993,
    smtp_host: 'smtp.gmail.com',
    smtp_port: 465,
    hint: 'Gmail: serve una App Password (Google Account → Sicurezza → Password per le app), non la password normale. Puoi incollarla con o senza spazi.',
  },
  outlook: {
    imap_host: 'outlook.office365.com',
    imap_port: 993,
    smtp_host: 'smtp.office365.com',
    smtp_port: 587,
    hint: 'Outlook/Hotmail: abilita IMAP e usa password o app password Microsoft.',
  },
  aruba: {
    imap_host: 'imaps.pec.aruba.it',
    imap_port: 993,
    smtp_host: 'smtps.pec.aruba.it',
    smtp_port: 465,
  },
  legalmail: {
    imap_host: 'mbox.legalmail.it',
    imap_port: 993,
    smtp_host: 'smtp.legalmail.it',
    smtp_port: 465,
  },
  postecert: {
    imap_host: 'mail.postecert.it',
    imap_port: 993,
    smtp_host: 'mail.postecert.it',
    smtp_port: 465,
  },
  intesi: {
    imap_host: 'imap.ig-trustmail.com',
    imap_port: 993,
    smtp_host: 'smtp.ig-trustmail.com',
    smtp_port: 465,
    hint: 'PEC Intesi Group: indirizzo PEC completo + password casella (imap/smtp.ig-trustmail.com).',
  },
  other: {
    imap_host: '',
    imap_port: 993,
    smtp_host: '',
    smtp_port: 465,
  },
};

function notify(title: string, message: string) {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    window.alert(`${title}\n\n${message}`);
  }
}

export default function Accounts() {
  const { userEmail, masterPassword } = useAuth();
  const router = useRouter();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [label, setLabel] = useState('Gmail');
  const [address, setAddress] = useState('');
  const [imapUser, setImapUser] = useState('');
  const [imapPassword, setImapPassword] = useState('');
  const [provider, setProvider] = useState<Provider>('gmail');
  const [customHost, setCustomHost] = useState('');
  const [testingId, setTestingId] = useState<string | null>(null);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    if (!userEmail || !masterPassword) return;
    setAccounts(await api.listAccounts(userEmail, masterPassword));
  }, [userEmail, masterPassword]);

  useFocusEffect(
    useCallback(() => {
      load().catch((e) => setStatus({ ok: false, text: e.message }));
    }, [load]),
  );

  const isPec =
    provider === 'aruba' ||
    provider === 'legalmail' ||
    provider === 'postecert' ||
    provider === 'intesi';

  const add = async () => {
    if (!userEmail || !masterPassword) return;
    const p = PRESETS[provider];
    const host = provider === 'other' ? customHost : p.imap_host;
    const addr = address.trim().toLowerCase();
    const user = (imapUser || addr).trim().toLowerCase();
    const secret = imapPassword.replace(/\s+/g, '').trim();
    if (!host) {
      setStatus({ ok: false, text: 'Inserisci host IMAP' });
      return;
    }
    if (!addr) {
      setStatus({ ok: false, text: 'Inserisci l’indirizzo email della casella' });
      return;
    }
    if (!secret) {
      setStatus({
        ok: false,
        text: provider === 'gmail' ? 'Serve una App Password Google' : 'Password richiesta',
      });
      return;
    }
    try {
      await api.addImapAccount({
        email: userEmail,
        master_password: masterPassword,
        label: label || provider,
        address: addr,
        account_type: isPec ? 'pec' : provider === 'gmail' ? 'google' : provider === 'outlook' ? 'microsoft' : 'imap',
        imap_host: host,
        imap_port: p.imap_port,
        imap_user: user,
        imap_password: secret,
        smtp_host: provider === 'other' ? host : p.smtp_host,
        smtp_port: p.smtp_port,
        pec_provider: provider === 'other' ? null : provider,
        color: isPec ? '#e040a0' : provider === 'gmail' ? '#ea4335' : '#4ecdc4',
      });
      setImapPassword('');
      await load();
      const msg =
        'Account salvato. Premi Test IMAP, poi torna in Inbox e scorri in basso per sincronizzare.';
      setStatus({ ok: true, text: msg });
      notify('OK', msg);
    } catch (e: any) {
      setStatus({ ok: false, text: e.message });
      notify('Errore', e.message);
    }
  };

  const remove = async (id: string) => {
    if (!userEmail || !masterPassword) return;
    try {
      await api.deleteAccount(id, userEmail, masterPassword);
      await load();
      setStatus({ ok: true, text: 'Account rimosso' });
    } catch (e: any) {
      setStatus({ ok: false, text: e.message });
    }
  };

  const test = async (id: string) => {
    if (!userEmail || !masterPassword) return;
    setTestingId(id);
    setStatus({ ok: true, text: 'Test IMAP in corso…' });
    try {
      const data = await api.testAccount(id, userEmail, masterPassword);
      const okMsg = `IMAP OK — INBOX: ${data.inbox_count ?? '?'} messaggi. Avvio sync…`;
      setStatus({ ok: true, text: okMsg });
      notify('IMAP OK', okMsg);
      const sync: any = await api.syncRun(userEmail, masterPassword);
      if (sync?.errors?.length) {
        setStatus({ ok: false, text: `IMAP ok, sync parziale: ${sync.errors.join(' | ')}` });
      } else {
        setStatus({
          ok: true,
          text: `IMAP OK (${data.inbox_count ?? '?'} in INBOX). Sync: +${sync?.inserted ?? 0} nuovi. Torna in Inbox.`,
        });
      }
    } catch (e: any) {
      setStatus({ ok: false, text: e.message || 'Test fallito' });
      notify('Test fallito', e.message || 'Test fallito');
    } finally {
      setTestingId(null);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 16, paddingTop: 56 }}>
      <TouchableOpacity onPress={() => router.back()}>
        <Text style={styles.link}>← Inbox</Text>
      </TouchableOpacity>
      <Text style={styles.title}>Account</Text>

      {status ? (
        <View style={[styles.banner, status.ok ? styles.bannerOk : styles.bannerErr]}>
          <Text style={styles.bannerText}>{status.text}</Text>
        </View>
      ) : null}

      {accounts.map((a) => (
        <View key={a.id} style={styles.card}>
          <Text style={styles.cardTitle}>
            {a.label} · {a.type}
          </Text>
          <Text style={styles.cardSub}>{a.address}</Text>
          <View style={styles.rowBtns}>
            <TouchableOpacity onPress={() => test(a.id)} disabled={testingId === a.id}>
              <Text style={styles.link}>{testingId === a.id ? 'Test…' : 'Test IMAP + sync'}</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => remove(a.id)}>
              <Text style={styles.danger}>Rimuovi</Text>
            </TouchableOpacity>
          </View>
        </View>
      ))}

      <Text style={styles.section}>Aggiungi casella</Text>
      <View style={styles.chips}>
        {(['gmail', 'outlook', 'aruba', 'legalmail', 'postecert', 'intesi', 'other'] as Provider[]).map((p) => (
          <TouchableOpacity
            key={p}
            style={[styles.chip, provider === p && styles.chipOn]}
            onPress={() => {
              setProvider(p);
              if (p === 'gmail') setLabel('Gmail');
              else if (p === 'outlook') setLabel('Outlook');
              else if (p !== 'other') setLabel(`PEC ${p}`);
            }}
          >
            <Text style={[styles.chipText, provider === p && styles.chipTextOn]}>{p}</Text>
          </TouchableOpacity>
        ))}
      </View>
      {PRESETS[provider].hint ? <Text style={styles.hint}>{PRESETS[provider].hint}</Text> : null}

      {provider === 'other' ? (
        <TextInput
          style={styles.input}
          placeholder="Host IMAP (es. imap.example.com)"
          placeholderTextColor="#666"
          autoCapitalize="none"
          value={customHost}
          onChangeText={setCustomHost}
        />
      ) : null}

      <TextInput style={styles.input} placeholder="Etichetta" placeholderTextColor="#666" value={label} onChangeText={setLabel} />
      <TextInput
        style={styles.input}
        placeholder="Indirizzo email (Gmail completo)"
        placeholderTextColor="#666"
        autoCapitalize="none"
        keyboardType="email-address"
        value={address}
        onChangeText={(t) => {
          setAddress(t);
          if (!imapUser || imapUser === address) setImapUser(t);
        }}
      />
      {provider === 'other' || provider === 'outlook' ? (
        <TextInput
          style={styles.input}
          placeholder="Utente IMAP (di solito = email)"
          placeholderTextColor="#666"
          autoCapitalize="none"
          value={imapUser}
          onChangeText={setImapUser}
        />
      ) : null}
      <TextInput
        style={styles.input}
        placeholder={provider === 'gmail' ? 'App Password Google' : 'Password / app password'}
        placeholderTextColor="#666"
        secureTextEntry
        autoComplete="off"
        value={imapPassword}
        onChangeText={setImapPassword}
      />
      <TouchableOpacity style={styles.btn} onPress={add}>
        <Text style={styles.btnText}>Salva account</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0b1220' },
  link: { color: '#4ecdc4', marginBottom: 12, fontWeight: '600' },
  title: { color: '#fff', fontSize: 22, fontWeight: '700', marginBottom: 16 },
  banner: { borderRadius: 10, padding: 12, marginBottom: 14 },
  bannerOk: { backgroundColor: '#14352f' },
  bannerErr: { backgroundColor: '#3a1a1a' },
  bannerText: { color: '#eee', fontSize: 14, lineHeight: 20 },
  card: {
    backgroundColor: '#16213e',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  cardTitle: { color: '#fff', fontWeight: '600' },
  cardSub: { color: '#999', marginTop: 4 },
  rowBtns: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 10 },
  danger: { color: '#ff6b6b' },
  section: { color: '#4ecdc4', marginTop: 20, marginBottom: 10, fontWeight: '700' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 8 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 16,
    backgroundColor: '#16213e',
  },
  chipOn: { backgroundColor: '#4ecdc4' },
  chipText: { color: '#aaa', fontSize: 13 },
  chipTextOn: { color: '#0b1220', fontWeight: '700' },
  input: {
    backgroundColor: '#16213e',
    borderRadius: 12,
    padding: 14,
    color: '#fff',
    marginBottom: 10,
  },
  btn: {
    backgroundColor: '#4ecdc4',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    marginTop: 4,
    marginBottom: 40,
  },
  btnText: { color: '#0b1220', fontWeight: '700' },
  hint: { color: '#f0c674', marginBottom: 12, fontSize: 13, lineHeight: 18 },
});
