import React, { useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Alert,
  Switch,
  ScrollView,
  Platform,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useAuth } from '@/src/contexts/AuthContext';
import { api, Account } from '@/src/services/api';

type PendingAttachment = {
  id: string;
  filename: string;
  content_type: string;
  content_base64: string;
  size: number;
};

const MAX_FILES = 10;
const MAX_ONE = 12 * 1024 * 1024;
const MAX_ALL = 25 * 1024 * 1024;

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function feedback(title: string, message: string) {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    window.alert(`${title}\n\n${message}`);
  } else {
    Alert.alert(title, message);
  }
}

function readFileAsAttachment(file: File): Promise<PendingAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`Lettura fallita: ${file.name}`));
    reader.onload = () => {
      const result = String(reader.result || '');
      const base64 = result.includes(',') ? result.split(',', 1)[1] : result;
      resolve({
        id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
        filename: file.name || 'allegato',
        content_type: file.type || 'application/octet-stream',
        content_base64: base64,
        size: file.size,
      });
    };
    reader.readAsDataURL(file);
  });
}

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
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

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

  const addFiles = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    if (attachments.length + list.length > MAX_FILES) {
      feedback('Allegati', `Puoi allegare al massimo ${MAX_FILES} file.`);
      return;
    }
    try {
      const next: PendingAttachment[] = [];
      let total = attachments.reduce((s, a) => s + a.size, 0);
      for (const file of list) {
        if (file.size > MAX_ONE) {
          feedback('Allegati', `«${file.name}» supera i 12 MB.`);
          return;
        }
        total += file.size;
        if (total > MAX_ALL) {
          feedback('Allegati', 'Dimensione totale oltre 25 MB.');
          return;
        }
        next.push(await readFileAsAttachment(file));
      }
      setAttachments((prev) => [...prev, ...next]);
    } catch (e: any) {
      feedback('Allegati', e?.message || 'Impossibile leggere i file');
    }
  };

  const pickAttachments = () => {
    if (Platform.OS === 'web' && typeof document !== 'undefined') {
      const input = document.createElement('input');
      input.type = 'file';
      input.multiple = true;
      input.accept = '*/*';
      // Alcuni browser ignorano click() se l'input non è nel DOM
      input.style.cssText =
        'position:fixed;left:-9999px;top:0;opacity:0;width:1px;height:1px;';
      document.body.appendChild(input);
      const cleanup = () => {
        try {
          input.remove();
        } catch {
          /* ignore */
        }
      };
      input.addEventListener('change', () => {
        const files = input.files;
        cleanup();
        if (files?.length) addFiles(files).catch(() => undefined);
      });
      input.addEventListener('cancel', cleanup);
      fileInputRef.current = input;
      input.click();
      return;
    }
    feedback(
      'Allegati',
      'La selezione file è disponibile nella versione web / PWA.',
    );
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const send = async () => {
    if (!userEmail || !masterPassword) {
      feedback('Invio', 'Sessione scaduta: effettua di nuovo il login.');
      return;
    }
    if (!accountId) {
      feedback('Invio', 'Seleziona un account mittente.');
      return;
    }
    if (!to.trim()) {
      feedback('Invio', 'Inserisci almeno un destinatario.');
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
        attachments: attachments.map((a) => ({
          filename: (a.filename || 'allegato').trim() || 'allegato',
          content_type: a.content_type || 'application/octet-stream',
          content_base64: a.content_base64 || '',
        })),
      });
      feedback(
        'Inviato',
        attachments.length
          ? `Email inviata con ${attachments.length} allegat${attachments.length === 1 ? 'o' : 'i'}.`
          : 'Email inviata via SMTP',
      );
      router.replace('/home');
    } catch (e: any) {
      feedback('Errore invio', e?.message || 'Invio fallito');
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
        <Text style={styles.label}>Invia come PEC</Text>
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

      <Text style={styles.label}>Allegati</Text>
      <TouchableOpacity style={styles.attachBtn} onPress={pickAttachments} disabled={sending}>
        <Text style={styles.attachBtnText}>＋ Aggiungi allegati</Text>
      </TouchableOpacity>
      {attachments.length === 0 ? (
        <Text style={styles.attachHint}>Nessun allegato (max 10 file, 12 MB ciascuno, 25 MB totali).</Text>
      ) : (
        attachments.map((a) => (
          <View key={a.id} style={styles.attachRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.attachName} numberOfLines={1}>
                {a.filename}
              </Text>
              <Text style={styles.attachMeta}>{formatSize(a.size)}</Text>
            </View>
            <TouchableOpacity onPress={() => removeAttachment(a.id)}>
              <Text style={styles.attachRemove}>Rimuovi</Text>
            </TouchableOpacity>
          </View>
        ))
      )}

      <TouchableOpacity style={styles.btn} onPress={send} disabled={sending}>
        <Text style={styles.btnText}>{sending ? 'Invio…' : 'Invia'}</Text>
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
  attachBtn: {
    borderWidth: 1,
    borderColor: '#4ecdc4',
    borderRadius: 12,
    padding: 14,
    alignItems: 'center',
    marginBottom: 10,
  },
  attachBtnText: { color: '#4ecdc4', fontWeight: '700' },
  attachHint: { color: '#666', fontSize: 13, marginBottom: 12 },
  attachRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#16213e',
    borderRadius: 10,
    padding: 12,
    marginBottom: 8,
    gap: 10,
  },
  attachName: { color: '#fff', fontWeight: '600' },
  attachMeta: { color: '#888', fontSize: 12, marginTop: 2 },
  attachRemove: { color: '#ff6b6b', fontWeight: '600' },
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
