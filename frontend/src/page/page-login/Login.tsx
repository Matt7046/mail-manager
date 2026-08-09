import React, { useEffect, useState } from 'react';
import {
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Image,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { useAuth } from '@/src/contexts/AuthContext';
import { oauthCallbackPathFromQuery } from '@/src/lib/oauthStrayRedirect';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const router = useRouter();

  useEffect(() => {
    const path = oauthCallbackPathFromQuery();
    if (path) router.replace(path as any);
  }, [router]);

  const onSubmit = async () => {
    if (!email.trim() || !password) {
      Alert.alert('Errore', 'Inserisci email e password');
      return;
    }
    setLoading(true);
    try {
      await login(email.trim().toLowerCase(), password);
      router.replace('/home');
    } catch (e: any) {
      Alert.alert('Errore', e.message || 'Login fallito');
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Image
        source={{ uri: '/logo-mail-manager.png' }}
        style={styles.logo}
        resizeMode="contain"
        accessibilityLabel="Mail Manager"
      />
      <Text style={styles.title}>Mail Manager</Text>
      <Text style={styles.sub}>Accedi al tuo account</Text>
      <TextInput
        style={styles.input}
        placeholder="Email"
        placeholderTextColor="#666"
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
      />
      <TextInput
        style={styles.input}
        placeholder="Master password"
        placeholderTextColor="#666"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
      />
      <TouchableOpacity style={styles.btn} onPress={onSubmit} disabled={loading}>
        <Text style={styles.btnText}>{loading ? '…' : 'Login'}</Text>
      </TouchableOpacity>

      <View style={styles.divider}>
        <View style={styles.dividerLine} />
        <Text style={styles.dividerText}>oppure</Text>
        <View style={styles.dividerLine} />
      </View>

      <TouchableOpacity style={styles.createBtn} onPress={() => router.push('/setup')}>
        <Text style={styles.createText}>Crea account</Text>
      </TouchableOpacity>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0b1220',
    justifyContent: 'center',
    padding: 24,
  },
  logo: {
    width: '100%',
    height: 120,
    marginBottom: 8,
    alignSelf: 'center',
  },
  title: {
    color: '#fff',
    fontSize: 28,
    fontWeight: '700',
    textAlign: 'center',
    marginBottom: 4,
  },
  sub: { color: '#999', marginBottom: 32, textAlign: 'center' },
  input: {
    backgroundColor: '#16213e',
    borderRadius: 12,
    padding: 14,
    color: '#fff',
    marginBottom: 12,
  },
  btn: {
    backgroundColor: '#4ecdc4',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  btnText: { color: '#0b1220', fontWeight: '700', fontSize: 16 },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 24,
    marginBottom: 16,
  },
  dividerLine: { flex: 1, height: 1, backgroundColor: '#1e2a44' },
  dividerText: { color: '#666', fontSize: 13, marginHorizontal: 12 },
  createBtn: {
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#4ecdc4',
  },
  createText: { color: '#4ecdc4', fontSize: 16, fontWeight: '600' },
});
