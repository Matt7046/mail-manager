import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Alert,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { useAuth } from '@/src/contexts/AuthContext';
import { api, Account } from '@/src/services/api';

export default function Accounts() {
  const { userEmail, masterPassword } = useAuth();
  const router = useRouter();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [label, setLabel] = useState('PEC principale');
  const [address, setAddress] = useState('');
  const [imapUser, setImapUser] = useState('');
  const [imapPassword, setImapPassword] = useState('');
  const [provider, setProvider] = useState<'aruba' | 'legalmail' | 'postecert' | 'other'>('aruba');
  const [asPec, setAsPec] = useState(true);

  const load = useCallback(async () => {
    if (!userEmail || !masterPassword) return;
    setAccounts(await api.listAccounts(userEmail, masterPassword));
  }, [userEmail, masterPassword]);

  useFocusEffect(
    useCallback(() => {
      load().catch((e) => Alert.alert('Errore', e.message));
    }, [load]),
  );

  const presets: Record<string, { imap_host: string; imap_port: number; smtp_host: string; smtp_port: number }> = {
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
    other: {
      imap_host: '',
      imap_port: 993,
      smtp_host: '',
      smtp_port: 465,
    },
  };

  const add = async () => {
    if (!userEmail || !masterPassword) return;
    const p = presets[provider];
    try {
      await api.addImapAccount({
        email: userEmail,
        master_password: masterPassword,
        label,
        address: address || imapUser,
        account_type: asPec ? 'pec' : 'imap',
        imap_host: p.imap_host || 'imap.example.com',
        imap_port: p.imap_port,
        imap_user: imapUser || address,
        imap_password: imapPassword,
        smtp_host: p.smtp_host || undefined,
        smtp_port: p.smtp_port,
        pec_provider: asPec ? provider : null,
        color: asPec ? '#e040a0' : '#4ecdc4',
      });
      setImapPassword('');
      await load();
      Alert.alert('OK', 'Account salvato (credenziali cifrate)');
    } catch (e: any) {
      Alert.alert('Errore', e.message);
    }
  };

  const remove = async (id: string) => {
    if (!userEmail || !masterPassword) return;
    try {
      await api.deleteAccount(id, userEmail, masterPassword);
      await load();
    } catch (e: any) {
      Alert.alert('Errore', e.message);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 16, paddingTop: 56 }}>
      <TouchableOpacity onPress={() => router.back()}>
        <Text style={styles.link}>← Inbox</Text>
      </TouchableOpacity>
      <Text style={styles.title}>Account</Text>

      {accounts.map((a) => (
        <View key={a.id} style={styles.card}>
          <Text style={styles.cardTitle}>
            {a.label} {a.type === 'pec' ? '· PEC' : ''}
          </Text>
          <Text style={styles.cardSub}>{a.address}</Text>
          <TouchableOpacity onPress={() => remove(a.id)}>
            <Text style={styles.danger}>Rimuovi</Text>
          </TouchableOpacity>
        </View>
      ))}

      <Text style={styles.section}>Aggiungi IMAP / PEC</Text>
      <View style={styles.chips}>
        {(['aruba', 'legalmail', 'postecert', 'other'] as const).map((p) => (
          <TouchableOpacity
            key={p}
            style={[styles.chip, provider === p && styles.chipOn]}
            onPress={() => setProvider(p)}
          >
            <Text style={[styles.chipText, provider === p && styles.chipTextOn]}>{p}</Text>
          </TouchableOpacity>
        ))}
      </View>
      <TouchableOpacity
        style={[styles.chip, asPec && styles.chipOn, { alignSelf: 'flex-start', marginBottom: 10 }]}
        onPress={() => setAsPec((v) => !v)}
      >
        <Text style={[styles.chipText, asPec && styles.chipTextOn]}>
          {asPec ? 'Tipo: PEC' : 'Tipo: IMAP'}
        </Text>
      </TouchableOpacity>

      <TextInput style={styles.input} placeholder="Etichetta" placeholderTextColor="#666" value={label} onChangeText={setLabel} />
      <TextInput style={styles.input} placeholder="Indirizzo email/PEC" placeholderTextColor="#666" autoCapitalize="none" value={address} onChangeText={setAddress} />
      <TextInput style={styles.input} placeholder="Utente IMAP" placeholderTextColor="#666" autoCapitalize="none" value={imapUser} onChangeText={setImapUser} />
      <TextInput style={styles.input} placeholder="Password / app password" placeholderTextColor="#666" secureTextEntry value={imapPassword} onChangeText={setImapPassword} />
      <TouchableOpacity style={styles.btn} onPress={add}>
        <Text style={styles.btnText}>Salva account</Text>
      </TouchableOpacity>
      <Text style={styles.hint}>
        OAuth Google/Microsoft: endpoint /api/accounts/oauth/.../start (config client id in .env).
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0b1220' },
  link: { color: '#4ecdc4', marginBottom: 12 },
  title: { color: '#fff', fontSize: 22, fontWeight: '700', marginBottom: 16 },
  card: {
    backgroundColor: '#16213e',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  cardTitle: { color: '#fff', fontWeight: '600' },
  cardSub: { color: '#999', marginTop: 4 },
  danger: { color: '#ff6b6b', marginTop: 8 },
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
  },
  btnText: { color: '#0b1220', fontWeight: '700' },
  hint: { color: '#666', marginTop: 16, marginBottom: 40, fontSize: 12 },
});
