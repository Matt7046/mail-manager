import React, { useCallback, useEffect, useRef, useState } from 'react';
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
  Linking,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as LocalAuthentication from 'expo-local-authentication';
import { useAuth } from '@/src/contexts/AuthContext';
import { oauthCallbackPathFromQuery } from '@/src/lib/oauthStrayRedirect';

const PERSONALITY_URL = 'https://colorsdev.tech/personality';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [biometricAvailable, setBiometricAvailable] = useState(false);
  const {
    login,
    userEmail,
    masterPassword,
    isReady,
    isBiometricEnabled,
    authenticateWithBiometric,
  } = useAuth();
  const router = useRouter();
  const autoBiometricAttempted = useRef(false);
  const biometricInProgress = useRef(false);

  useEffect(() => {
    const path = oauthCallbackPathFromQuery();
    if (path) router.replace(path as any);
  }, [router]);

  useEffect(() => {
    if (userEmail) setEmail(userEmail);
  }, [userEmail]);

  // Già sbloccato (sessione tab) → home
  useEffect(() => {
    if (isReady && userEmail && masterPassword) {
      router.replace('/home');
    }
  }, [isReady, userEmail, masterPassword, router]);

  const handleBiometricLogin = useCallback(async () => {
    if (biometricInProgress.current || masterPassword) return;
    biometricInProgress.current = true;
    setLoading(true);
    try {
      await authenticateWithBiometric();
      router.replace('/home');
    } catch (error: any) {
      const msg = error?.message || 'Biometrica fallita';
      if (msg.includes('cambiata') || msg.includes('salvata')) {
        Alert.alert('Biometrica disabilitata', msg);
        setBiometricAvailable(false);
      }
    } finally {
      biometricInProgress.current = false;
      setLoading(false);
    }
  }, [authenticateWithBiometric, masterPassword, router]);

  const handleBiometricLoginRef = useRef(handleBiometricLogin);
  handleBiometricLoginRef.current = handleBiometricLogin;

  useEffect(() => {
    if (!isReady || masterPassword) return;

    let cancelled = false;

    const checkBiometric = async () => {
      const hasHardware = await LocalAuthentication.hasHardwareAsync();
      const isEnrolled = await LocalAuthentication.isEnrolledAsync();
      let webOk = false;
      if (Platform.OS === 'web') {
        try {
          const { isWebPlatformAuthAvailable } = await import('@/src/utils/webBiometric');
          webOk = await isWebPlatformAuthAvailable();
        } catch {
          /* ignore */
        }
      }
      if (cancelled) return;

      const canUse = ((hasHardware && isEnrolled) || webOk) && isBiometricEnabled;
      setBiometricAvailable(canUse);

      if (canUse && !autoBiometricAttempted.current) {
        autoBiometricAttempted.current = true;
        await handleBiometricLoginRef.current();
      }
    };

    void checkBiometric();
    return () => {
      cancelled = true;
    };
  }, [isReady, isBiometricEnabled, masterPassword]);

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
        onSubmitEditing={onSubmit}
      />
      <TouchableOpacity style={styles.btn} onPress={onSubmit} disabled={loading}>
        <Text style={styles.btnText}>{loading ? '…' : 'Login'}</Text>
      </TouchableOpacity>

      {biometricAvailable ? (
        <TouchableOpacity
          style={styles.biometricBtn}
          onPress={handleBiometricLogin}
          disabled={loading}
        >
          <Ionicons name="finger-print" size={22} color="#4ecdc4" />
          <Text style={styles.biometricText}>Usa biometrica</Text>
        </TouchableOpacity>
      ) : null}

      <View style={styles.divider}>
        <View style={styles.dividerLine} />
        <Text style={styles.dividerText}>oppure</Text>
        <View style={styles.dividerLine} />
      </View>

      <TouchableOpacity style={styles.createBtn} onPress={() => router.push('/setup')}>
        <Text style={styles.createText}>Crea account</Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.personalityLink}
        onPress={() => Linking.openURL(PERSONALITY_URL)}
        accessibilityRole="link"
      >
        <Text style={styles.personalityText}>Scopri l'analisi IA della personalità</Text>
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
  biometricBtn: {
    marginTop: 14,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 8,
    borderWidth: 1,
    borderColor: '#4ecdc4',
  },
  biometricText: { color: '#4ecdc4', fontSize: 16, fontWeight: '600' },
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
  personalityLink: {
    marginTop: 20,
    alignItems: 'center',
    padding: 8,
  },
  personalityText: {
    color: '#60a5fa',
    fontSize: 14,
    textDecorationLine: 'underline',
  },
});
