import React, { useState } from 'react';
import {
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Image,
} from 'react-native';
import { useRouter } from 'expo-router';
import { useAuth } from '@/src/contexts/AuthContext';

export default function Setup() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const { setup } = useAuth();
  const router = useRouter();

  const onSubmit = async () => {
    if (password.length < 8) {
      Alert.alert('Password', 'Minimo 8 caratteri');
      return;
    }
    setLoading(true);
    try {
      await setup(email, password);
      router.replace('/home');
    } catch (e: any) {
      Alert.alert('Errore', e.message || 'Setup fallito');
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
      <Text style={styles.brand}>Nuovo account</Text>
      <Text style={styles.sub}>Crea un vault con email e master password</Text>
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
        placeholder="Master password (min 8)"
        placeholderTextColor="#666"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
      />
      <TouchableOpacity style={styles.btn} onPress={onSubmit} disabled={loading}>
        <Text style={styles.btnText}>{loading ? 'Creazione...' : 'Crea account'}</Text>
      </TouchableOpacity>
      <TouchableOpacity style={styles.loginLink} onPress={() => router.replace('/login')}>
        <Text style={styles.loginLinkText}>Hai già un account? Accedi</Text>
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
    height: 100,
    marginBottom: 12,
    alignSelf: 'center',
  },
  brand: { color: '#fff', fontSize: 28, fontWeight: '700', marginBottom: 4, textAlign: 'center' },
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
  loginLink: { alignItems: 'center', marginTop: 24, padding: 12 },
  loginLinkText: { color: '#4ecdc4', fontSize: 14, textDecorationLine: 'underline' },
});
