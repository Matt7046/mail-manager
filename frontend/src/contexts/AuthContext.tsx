import React, {
  createContext,
  useContext,
  useMemo,
  useState,
  useCallback,
  useEffect,
  useRef,
} from 'react';
import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as LocalAuthentication from 'expo-local-authentication';
import { api } from '@/src/services/api';
import {
  enablePushNotifications,
  registerServiceWorker,
  type PushEnableResult,
} from '@/src/services/push';
import {
  clearVaultSession,
  readVaultSession,
  writeVaultSession,
} from '@/src/lib/vaultSession';
import { storage } from '@/src/utils/storage';

type AuthCtx = {
  userEmail: string | null;
  masterPassword: string | null;
  isReady: boolean;
  isBiometricEnabled: boolean;
  login: (email: string, password: string) => Promise<void>;
  setup: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  bootstrap: () => Promise<{ setupDone: boolean }>;
  enableNotifications: () => Promise<PushEnableResult>;
  enableBiometric: () => Promise<void>;
  disableBiometric: () => Promise<void>;
  authenticateWithBiometric: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);
const EMAIL_KEY = 'mm_email';
const BIO_FLAG = 'mm_biometric_enabled';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [masterPassword, setMasterPassword] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [isBiometricEnabled, setIsBiometricEnabled] = useState(false);
  const biometricAuthInFlight = useRef<Promise<void> | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const enabled = (await storage.getItem(BIO_FLAG, 'false')) === 'true';
      if (!cancelled) setIsBiometricEnabled(enabled);

      if (Platform.OS === 'web') {
        registerServiceWorker().catch(() => undefined);
        // Con biometrica attiva non auto-sbloccare: serve Hello / Face ID su Login
        if (!enabled) {
          const session = readVaultSession();
          if (session) {
            if (!cancelled) {
              setUserEmail(session.email);
              setMasterPassword(session.masterPassword);
              setIsReady(true);
            }
            return;
          }
        } else {
          // Prefill email da vault / storage senza sbloccare la master
          const session = readVaultSession();
          const savedEmail =
            session?.email || (await AsyncStorage.getItem(EMAIL_KEY)) || null;
          if (savedEmail && !cancelled) setUserEmail(savedEmail);
        }
      }
      if (!cancelled) setIsReady(true);
    })().catch(() => {
      if (!cancelled) setIsReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const enableNotifications = useCallback(async (): Promise<PushEnableResult> => {
    if (Platform.OS !== 'web') {
      return {
        ok: false,
        reason: 'unsupported',
        message: 'Le notifiche push sono disponibili nella versione web / PWA.',
      };
    }
    if (!userEmail || !masterPassword) {
      return {
        ok: false,
        reason: 'no-auth',
        message: 'Effettua il login prima di attivare le notifiche.',
      };
    }
    return enablePushNotifications(userEmail, masterPassword);
  }, [userEmail, masterPassword]);

  const bootstrap = useCallback(async () => {
    const saved =
      (Platform.OS === 'web' ? readVaultSession()?.email : null) ||
      (await AsyncStorage.getItem(EMAIL_KEY));
    const check = await api.checkSetup();
    setIsReady(true);
    return { setupDone: check.setup_done, savedEmail: saved || '' } as any;
  }, []);

  const afterAuth = useCallback(async (email: string, password: string) => {
    await AsyncStorage.setItem(EMAIL_KEY, email);
    if (Platform.OS === 'web') {
      writeVaultSession(email, password);
      enablePushNotifications(email, password).catch(() => undefined);
    }
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const e = email.trim().toLowerCase();
      await api.login(e, password);
      setUserEmail(e);
      setMasterPassword(password);
      await afterAuth(e, password);
    },
    [afterAuth],
  );

  const setup = useCallback(
    async (email: string, password: string) => {
      const e = email.trim().toLowerCase();
      await api.setup(e, password);
      setUserEmail(e);
      setMasterPassword(password);
      await afterAuth(e, password);
    },
    [afterAuth],
  );

  const logout = useCallback(async () => {
    setMasterPassword(null);
    // tieni email per prefill login / biometrica
    clearVaultSession();
  }, []);

  const enableBiometric = useCallback(async () => {
    if (!masterPassword || !userEmail) {
      throw new Error('Accedi prima di abilitare la biometrica');
    }

    const hasHardware = await LocalAuthentication.hasHardwareAsync();
    const isEnrolled = await LocalAuthentication.isEnrolledAsync();

    if (hasHardware && isEnrolled) {
      await storage.secureSet('master_password', masterPassword);
      await storage.secureSet('user_email', userEmail);
      await storage.setItem(BIO_FLAG, 'true');
      setIsBiometricEnabled(true);
      return;
    }

    const { isWebPlatformAuthAvailable, registerWebPlatformAuth } = await import(
      '@/src/utils/webBiometric'
    );
    if (await isWebPlatformAuthAvailable()) {
      await registerWebPlatformAuth(userEmail);
      await storage.secureSet('master_password', masterPassword);
      await storage.secureSet('user_email', userEmail);
      await storage.setItem(BIO_FLAG, 'true');
      setIsBiometricEnabled(true);
      return;
    }

    throw new Error(
      'Biometrica non disponibile. Su PC serve Windows Hello (o Touch ID) nel browser.',
    );
  }, [masterPassword, userEmail]);

  const disableBiometric = useCallback(async () => {
    await storage.secureSet('master_password', '');
    await storage.secureSet('user_email', '');
    await storage.setItem(BIO_FLAG, 'false');
    setIsBiometricEnabled(false);
    try {
      const { clearWebPlatformAuth } = await import('@/src/utils/webBiometric');
      clearWebPlatformAuth();
    } catch {
      /* ignore */
    }
  }, []);

  const authenticateWithBiometric = useCallback(async () => {
    if (biometricAuthInFlight.current) {
      return biometricAuthInFlight.current;
    }

    const authPromise = (async () => {
      const hasHardware = await LocalAuthentication.hasHardwareAsync();
      const isEnrolled = await LocalAuthentication.isEnrolledAsync();

      let verified = false;

      if (hasHardware && isEnrolled) {
        const result = await LocalAuthentication.authenticateAsync({
          promptMessage: 'Sblocca Mail Manager',
          fallbackLabel: 'Usa Password Master',
        });
        verified = result.success;
      } else {
        const { authenticateWebPlatformAuth } = await import('@/src/utils/webBiometric');
        verified = await authenticateWebPlatformAuth();
      }

      if (!verified) {
        throw new Error('Autenticazione biometrica fallita o annullata');
      }

      const savedPassword = await storage.secureGet('master_password', null);
      const savedEmail = await storage.secureGet('user_email', null);
      if (savedPassword && savedEmail) {
        try {
          await login(savedEmail, savedPassword);
        } catch {
          await storage.secureSet('master_password', '');
          await storage.secureSet('user_email', '');
          await storage.setItem(BIO_FLAG, 'false');
          setIsBiometricEnabled(false);
          try {
            const { clearWebPlatformAuth } = await import('@/src/utils/webBiometric');
            clearWebPlatformAuth();
          } catch {
            /* ignore */
          }
          throw new Error(
            'La password è stata cambiata. Accedi con la nuova password master e ri-abilita la biometrica.',
          );
        }
      } else {
        await storage.setItem(BIO_FLAG, 'false');
        setIsBiometricEnabled(false);
        throw new Error('Nessuna credenziale salvata. Accedi con la password master.');
      }
    })();

    biometricAuthInFlight.current = authPromise;
    try {
      await authPromise;
    } finally {
      if (biometricAuthInFlight.current === authPromise) {
        biometricAuthInFlight.current = null;
      }
    }
  }, [login]);

  const value = useMemo(
    () => ({
      userEmail,
      masterPassword,
      isReady,
      isBiometricEnabled,
      login,
      setup,
      logout,
      bootstrap,
      enableNotifications,
      enableBiometric,
      disableBiometric,
      authenticateWithBiometric,
    }),
    [
      userEmail,
      masterPassword,
      isReady,
      isBiometricEnabled,
      login,
      setup,
      logout,
      bootstrap,
      enableNotifications,
      enableBiometric,
      disableBiometric,
      authenticateWithBiometric,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside provider');
  return v;
}
