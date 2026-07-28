import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Alert,
  Switch,
  ScrollView,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useAuth } from '@/src/contexts/AuthContext';
import { api, Account } from '@/src/services/api';

export default function Compose() {
  const { userEmail, masterPassword } = useAuth();
  const router = useRouter();
  const params = useLocalSearchParams<{ to?: string; subject?: string; replyTo?: string }>();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState('');
  const [to, setTo] = useState(params.to || '');
  const [subject, setSubject] = useState(params.subject || '');
  const [body, setBody] = useState('');
  const [asPec, setAsPec] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    (async () => {
      if (!userEmail || !masterPassword) return;
      const list = await api.listAccounts(userEmail, masterPassword);
      setAccounts(list);
      if (list[0]) {
        setAccountId(list[0].id);
        setAsPec(list[0].type === 'pec');
      }
    })().catch((e) => Alert.alert('Errore', e.message));
  }, [userEmail, masterPassword]);

  const selected = accounts.find((a) => a.id === accountId);

  const send = async () => {
    if (!userEmail || !masterPassword || !accountId) return;
    if (!to.trim()) {
      Alert.alert('Destinatario mancante');
      return;
    }
    setSending(true);
    try {
      await api.sendMessage({
        email: userEmail,
        master_password: masterPassword,
        account_id: accountId,
        to: to.split(',').map((s) => s.trim()).filter(Boolean),
        subject,
        body_text: body,
        as_pec: asPec || selected?.type === 'pec',
        reply_to_message_id: params.replyTo || null,
      });
      Alert.alert('Inviato', 'Email inviata via SMTP');
      router.replace('/home');
    } catch (e: any) {
      Alert.alert('Errore', e.message);
    } finally {
      setSending(false);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 16, paddingTop: 56 }}>
      <TouchableOpacity onPress={() => router.back()}>
        <Text style={styles.link}>← Annulla</Text>
      </TouchableOpacity>
      <Text style={styles.title}>Nuovo messaggio {asPec || selected?.type === 'pec' ? '(PEC)' : ''}</Text>

      <Text style={styles.label}>Da account</Text>
      {accounts.map((a) => (
        <TouchableOpacity
          key={a.id}
          style={[styles.account, accountId === a.id && styles.accountOn]}
          onPress={() => {
            setAccountId(a.id);
            setAsPec(a.type === 'pec');
          }}
        >
          <Text style={styles.accountText}>
            {a.label} — {a.address} {a.type === 'pec' ? '· PEC' : ''}
          </Text>
        </TouchableOpacity>
      ))}

      <View style={styles.row}>
        <Text style={styles.label}>Invia come PEC (v2)</Text>
        <Switch
          value={asPec || selected?.type === 'pec'}
          onValueChange={setAsPec}
          disabled={selected?.type === 'pec'}
        />
      </View>

      <TextInput
        style={styles.input}
        placeholder="A (email, separate da virgola)"
        placeholderTextColor="#666"
        autoCapitalize="none"
        value={to}
        onChangeText={setTo}
      />
      <TextInput
        style={styles.input}
        placeholder="Oggetto"
        placeholderTextColor="#666"
        value={subject}
        onChangeText={setSubject}
      />
      <TextInput
        style={[styles.input, styles.body]}
        placeholder="Messaggio"
        placeholderTextColor="#666"
        multiline
        textAlignVertical="top"
        value={body}
        onChangeText={setBody}
      />
      <TouchableOpacity style={styles.btn} onPress={send} disabled={sending}>
        <Text style={styles.btnText}>{sending ? '…' : 'Invia (outbox v2)'}</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0b1220' },
  link: { color: '#4ecdc4', marginBottom: 12 },
  title: { color: '#fff', fontSize: 22, fontWeight: '700', marginBottom: 16 },
  label: { color: '#999', marginBottom: 8, marginTop: 8 },
  account: {
    padding: 12,
    borderRadius: 10,
    backgroundColor: '#16213e',
    marginBottom: 6,
  },
  accountOn: { borderColor: '#4ecdc4', borderWidth: 1 },
  accountText: { color: '#ddd' },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginVertical: 12,
  },
  input: {
    backgroundColor: '#16213e',
    borderRadius: 12,
    padding: 14,
    color: '#fff',
    marginBottom: 10,
  },
  body: { minHeight: 160 },
  btn: {
    backgroundColor: '#4ecdc4',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    marginTop: 8,
    marginBottom: 40,
  },
  btnText: { color: '#0b1220', fontWeight: '700' },
});
