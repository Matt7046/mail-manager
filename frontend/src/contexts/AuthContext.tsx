import React, { createContext, useContext, useMemo, useState, useCallback, useEffect } from 'react';
import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { api } from '@/src/services/api';
import {
  enablePushNotifications,
  registerServiceWorker,
  type PushEnableResult,
} from '@/src/services/push';

type AuthCtx = {
  userEmail: string | null;
  masterPassword: string | null;
  isReady: boolean;
  login: (email: string, password: string) => Promise<void>;
  setup: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  bootstrap: () => Promise<{ setupDone: boolean }>;
  enableNotifications: () => Promise<PushEnableResult>;
};

const Ctx = createContext<AuthCtx | null>(null);
const EMAIL_KEY = 'mm_email';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [masterPassword, setMasterPassword] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    if (Platform.OS === 'web') {
      registerServiceWorker().catch(() => undefined);
    }
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
    const saved = await AsyncStorage.getItem(EMAIL_KEY);
    const check = await api.checkSetup();
    setIsReady(true);
    return { setupDone: check.setup_done, savedEmail: saved || '' } as any;
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const e = email.trim().toLowerCase();
    await api.login(e, password);
    await AsyncStorage.setItem(EMAIL_KEY, e);
    setUserEmail(e);
    setMasterPassword(password);
    if (Platform.OS === 'web') {
      // Best-effort: su iOS fallisce senza gesto utente / senza PWA — ok silenzioso
      enablePushNotifications(e, password).catch(() => undefined);
    }
  }, []);

  const setup = useCallback(async (email: string, password: string) => {
    const e = email.trim().toLowerCase();
    await api.setup(e, password);
    await AsyncStorage.setItem(EMAIL_KEY, e);
    setUserEmail(e);
    setMasterPassword(password);
    if (Platform.OS === 'web') {
      enablePushNotifications(e, password).catch(() => undefined);
    }
  }, []);

  const logout = useCallback(async () => {
    setMasterPassword(null);
    setUserEmail(null);
  }, []);

  const value = useMemo(
    () => ({
      userEmail,
      masterPassword,
      isReady,
      login,
      setup,
      logout,
      bootstrap,
      enableNotifications,
    }),
    [userEmail, masterPassword, isReady, login, setup, logout, bootstrap, enableNotifications],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside provider');
  return v;
}
