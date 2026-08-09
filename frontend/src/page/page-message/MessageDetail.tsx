import React, { useEffect, useState } from 'react';

import {

  View,

  Text,

  ScrollView,

  StyleSheet,

  TouchableOpacity,

  ActivityIndicator,

  Alert,

} from 'react-native';

import { useLocalSearchParams, useRouter } from 'expo-router';

import { useAuth } from '@/src/contexts/AuthContext';

import { api } from '@/src/services/api';



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



        <Text style={styles.body}>{msg.body_text || '(vuoto)'}</Text>

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

    gap: 12,

  },

  headerActions: { flexDirection: 'row', gap: 14, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' },

  link: { color: '#4ecdc4', fontWeight: '600' },

  danger: { color: '#e07070', fontWeight: '600' },

  row: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 12 },

  pecBadge: {

    backgroundColor: '#e040a0',

    paddingHorizontal: 8,

    paddingVertical: 2,

    borderRadius: 6,

  },

  pecText: { color: '#fff', fontSize: 11, fontWeight: '700' },

  trashBadge: {

    backgroundColor: '#555',

    paddingHorizontal: 8,

    paddingVertical: 2,

    borderRadius: 6,

  },

  trashText: { color: '#fff', fontSize: 11, fontWeight: '700' },

  subject: { color: '#fff', fontSize: 22, fontWeight: '700', flex: 1 },

  meta: { color: '#999', marginBottom: 4 },

  receipts: {

    marginTop: 16,

    marginBottom: 8,

    padding: 12,

    borderRadius: 12,

    backgroundColor: '#16213e',

    borderColor: '#e040a0',

    borderWidth: 1,

  },

  receiptTitle: { color: '#e040a0', fontWeight: '700', marginBottom: 8 },

  receiptItem: { color: '#ccc', marginBottom: 4, fontSize: 13 },

  body: { color: '#ddd', marginTop: 20, fontSize: 16, lineHeight: 24 },

});


