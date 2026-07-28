import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  TextInput,
  RefreshControl,
  Alert,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { useAuth } from '@/src/contexts/AuthContext';
import { api, MessageListItem } from '@/src/services/api';

type Filter = 'all' | 'unread' | 'pec';

export default function Home() {
  const { userEmail, masterPassword, logout } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<MessageListItem[]>([]);
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!userEmail || !masterPassword) return;
    const data = await api.listMessages({
      email: userEmail,
      master_password: masterPassword,
      q: q.trim() || undefined,
      unread: filter === 'unread' ? true : undefined,
      pec: filter === 'pec' ? true : undefined,
    });
    setItems(data.items);
  }, [userEmail, masterPassword, q, filter]);

  useFocusEffect(
    useCallback(() => {
      load().catch((e) => Alert.alert('Errore', e.message));
    }, [load]),
  );

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      if (userEmail && masterPassword) {
        await api.syncRun(userEmail, masterPassword);
      }
      await load();
    } catch (e: any) {
      Alert.alert('Sync', e.message);
    } finally {
      setRefreshing(false);
    }
  };

  const seed = async () => {
    if (!userEmail || !masterPassword) return;
    try {
      await api.seedDemo(userEmail, masterPassword);
      await load();
    } catch (e: any) {
      Alert.alert('Demo', e.message);
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
          <TouchableOpacity
            onPress={async () => {
              await logout();
              router.replace('/login');
            }}
          >
            <Text style={[styles.link, { color: '#ff6b6b' }]}>Esci</Text>
          </TouchableOpacity>
        </View>
      </View>

      <TextInput
        style={styles.search}
        placeholder="Cerca oggetto o mittente…"
        placeholderTextColor="#666"
        value={q}
        onChangeText={setQ}
        onSubmitEditing={() => load()}
      />

      <View style={styles.chips}>
        {([
          ['all', 'Tutti'],
          ['unread', 'Non lette'],
          ['pec', 'Solo PEC'],
        ] as const).map(([k, label]) => (
          <TouchableOpacity
            key={k}
            style={[styles.chip, filter === k && styles.chipOn]}
            onPress={() => setFilter(k)}
          >
            <Text style={[styles.chipText, filter === k && styles.chipTextOn]}>{label}</Text>
          </TouchableOpacity>
        ))}
        <TouchableOpacity style={styles.chip} onPress={seed}>
          <Text style={styles.chipText}>+ Demo</Text>
        </TouchableOpacity>
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
            Nessun messaggio. Aggiungi un account PEC/IMAP e premi + Demo per dati di prova.
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
    paddingTop: 56,
    paddingHorizontal: 16,
    paddingBottom: 8,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  title: { color: '#fff', fontSize: 22, fontWeight: '700' },
  headerActions: { flexDirection: 'row', gap: 14 },
  link: { color: '#4ecdc4', fontWeight: '600' },
  search: {
    marginHorizontal: 16,
    marginBottom: 10,
    backgroundColor: '#16213e',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: '#fff',
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingHorizontal: 16, marginBottom: 8 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: '#16213e',
  },
  chipOn: { backgroundColor: '#4ecdc4' },
  chipText: { color: '#aaa', fontSize: 13 },
  chipTextOn: { color: '#0b1220', fontWeight: '700' },
  card: {
    backgroundColor: '#16213e',
    borderRadius: 14,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#1e2a44',
  },
  cardUnread: { borderColor: '#4ecdc4' },
  cardTop: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  from: { color: '#ccc', flex: 1, fontSize: 13 },
  pecBadge: {
    backgroundColor: '#e040a0',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
  },
  pecText: { color: '#fff', fontSize: 11, fontWeight: '700' },
  subject: { color: '#fff', fontSize: 16, fontWeight: '600', marginTop: 4 },
  snippet: { color: '#888', marginTop: 4, fontSize: 13 },
  empty: { color: '#666', textAlign: 'center', marginTop: 48, paddingHorizontal: 24 },
});
