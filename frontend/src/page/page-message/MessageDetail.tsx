import React, { createElement, useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Platform,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useAuth } from '@/src/contexts/AuthContext';
import { api } from '@/src/services/api';

function cleanPlainText(s: string): string {
  if (!s) return '';
  return s
    .replace(/&zwnj;/gi, '')
    .replace(/&#8204;/gi, '')
    .replace(/&#x0*200c;/gi, '')
    .replace(/[\u200b\u200c\ufeff]+/g, '')
    .replace(/[ \t\f\v\u00a0]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function EmailHtmlBody({ html }: { html: string }) {
  const srcDoc = useMemo(() => {
    const safe = html || '';
    return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  html,body{margin:0;padding:12px;background:#0b1220;color:#e8eef7;font:15px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;word-break:break-word;}
  img{max-width:100%;height:auto;}
  a{color:#4ecdc4;}
  table{max-width:100% !important;}
</style></head><body>${safe}</body></html>`;
  }, [html]);

  if (Platform.OS !== 'web') {
    return <Text style={styles.body}>{cleanPlainText(html.replace(/<[^>]+>/g, ' '))}</Text>;
  }

  return createElement('iframe', {
    title: 'corpo-email',
    srcDoc,
    sandbox: 'allow-same-origin allow-popups allow-popups-to-escape-sandbox',
    style: {
      width: '100%',
      minHeight: 420,
      border: 'none',
      borderRadius: 12,
      background: '#0b1220',
    },
  });
}

export default function MessageDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { userEmail, masterPassword } = useAuth();
  const router = useRouter();
  const [msg, setMsg] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      if (!id || !userEmail || !masterPassword) return;
      try {
        const data = await api.getMessage(id, userEmail, masterPassword);
        setMsg(data);
      } catch (e: any) {
        Alert.alert('Errore', e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [id, userEmail, masterPassword]);

  const inTrash = (msg?.folder || '').toLowerCase() === 'trash';
  const plain = cleanPlainText(msg?.body_text || '');
  const html = (msg?.body_html || '').trim();
  const showHtml = !!html && html.length > 20;

  const moveToTrash = async () => {
    if (!id || !userEmail || !masterPassword || busy) return;
    setBusy(true);
    try {
      await api.trashMessage(id, userEmail, masterPassword);
      router.back();
    } catch (e: any) {
      Alert.alert('Errore', e.message);
    } finally {
      setBusy(false);
    }
  };

  const restore = async () => {
    if (!id || !userEmail || !masterPassword || busy) return;
    setBusy(true);
    try {
      await api.restoreMessage(id, userEmail, masterPassword);
      router.back();
    } catch (e: any) {
      Alert.alert('Errore', e.message);
    } finally {
      setBusy(false);
    }
  };

  const deleteForever = () => {
    if (!id || !userEmail || !masterPassword || busy) return;
    Alert.alert(
      'Elimina definitivamente',
      'Il messaggio verrà cancellato in modo permanente. Continuare?',
      [
        { text: 'Annulla', style: 'cancel' },
        {
          text: 'Elimina',
          style: 'destructive',
          onPress: async () => {
            setBusy(true);
            try {
              await api.deleteMessage(id, userEmail, masterPassword);
              router.back();
            } catch (e: any) {
              Alert.alert('Errore', e.message);
            } finally {
              setBusy(false);
            }
          },
        },
      ],
    );
  };

  if (loading || !msg) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color="#4ecdc4" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()}>
          <Text style={styles.link}>← Indietro</Text>
        </TouchableOpacity>
        <View style={styles.headerActions}>
          {!inTrash ? (
            <>
              <TouchableOpacity
                onPress={() =>
                  router.push({
                    pathname: '/compose',
                    params: { replyTo: msg.id, to: msg.from, subject: `Re: ${msg.subject}` },
                  })
                }
              >
                <Text style={styles.link}>Rispondi</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={moveToTrash} disabled={busy}>
                <Text style={styles.danger}>Elimina</Text>
              </TouchableOpacity>
            </>
          ) : (
            <>
              <TouchableOpacity onPress={restore} disabled={busy}>
                <Text style={styles.link}>Ripristina</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={deleteForever} disabled={busy}>
                <Text style={styles.danger}>Elimina definitivamente</Text>
              </TouchableOpacity>
            </>
          )}
        </View>
      </View>
      <ScrollView contentContainerStyle={{ padding: 16 }}>
        <View style={styles.row}>
          {msg.is_pec ? (
            <View style={styles.pecBadge}>
              <Text style={styles.pecText}>PEC</Text>
            </View>
          ) : null}
          {inTrash ? (
            <View style={styles.trashBadge}>
              <Text style={styles.trashText}>Cestino</Text>
            </View>
          ) : null}
          <Text style={styles.subject}>{msg.subject}</Text>
        </View>
        <Text style={styles.meta}>Da: {msg.from}</Text>
        <Text style={styles.meta}>A: {(msg.to || []).join(', ')}</Text>
        <Text style={styles.meta}>{msg.date ? new Date(msg.date).toLocaleString() : ''}</Text>

        {msg.is_pec && msg.receipts?.length ? (
          <View style={styles.receipts}>
            <Text style={styles.receiptTitle}>Ricevute PEC</Text>
            {msg.receipts.map((r: any, i: number) => (
              <Text key={i} style={styles.receiptItem}>
                • {r.type} {r.at ? `— ${r.at}` : ''} {r.status ? `(${r.status})` : ''}
              </Text>
            ))}
          </View>
        ) : null}

        {showHtml ? (
          <EmailHtmlBody html={html} />
        ) : (
          <Text style={styles.body}>{plain || '(vuoto)'}</Text>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0b1220' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#0b1220' },
  header: {
    paddingTop: 56,
    paddingHorizontal: 16,
    paddingBottom: 8,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  headerActions: { flexDirection: 'row', gap: 14, alignItems: 'center' },
  link: { color: '#4ecdc4', fontWeight: '600' },
  danger: { color: '#ff6b6b', fontWeight: '600' },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 8 },
  pecBadge: {
    backgroundColor: '#e040a0',
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  pecText: { color: '#fff', fontSize: 11, fontWeight: '700' },
  trashBadge: {
    backgroundColor: '#666',
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  trashText: { color: '#fff', fontSize: 11, fontWeight: '700' },
  subject: { color: '#fff', fontSize: 20, fontWeight: '700', flex: 1 },
  meta: { color: '#999', marginBottom: 4 },
  receipts: {
    backgroundColor: '#16213e',
    borderRadius: 10,
    padding: 12,
    marginTop: 12,
    marginBottom: 8,
  },
  receiptTitle: { color: '#4ecdc4', fontWeight: '700', marginBottom: 6 },
  receiptItem: { color: '#ccc', fontSize: 13, marginBottom: 2 },
  body: { color: '#ddd', marginTop: 16, lineHeight: 22, fontSize: 15 },
});
