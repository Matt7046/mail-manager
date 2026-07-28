import React, { createContext, useContext, useMemo, useState, useCallback } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { api } from '@/src/services/api';

type AuthCtx = {
  userEmail: string | null;
  masterPassword: string | null;
  isReady: boolean;
  login: (email: string, password: string) => Promise<void>;
  setup: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  bootstrap: () => Promise<{ setupDone: boolean }>;
};

const Ctx = createContext<AuthCtx | null>(null);
const EMAIL_KEY = 'mm_email';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [masterPassword, setMasterPassword] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);

  const bootstrap = useCallback(async () => {
    const saved = await AsyncStorage.getItem(EMAIL_KEY);
    const check = await api.checkSetup();
    setIsReady(true);
    return { setupDone: check.setup_done, savedEmail: saved || '' } as any;
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    await api.login(email.trim().toLowerCase(), password);
    await AsyncStorage.setItem(EMAIL_KEY, email.trim().toLowerCase());
    setUserEmail(email.trim().toLowerCase());
    setMasterPassword(password);
  }, []);

  const setup = useCallback(async (email: string, password: string) => {
    await api.setup(email.trim().toLowerCase(), password);
    await AsyncStorage.setItem(EMAIL_KEY, email.trim().toLowerCase());
    setUserEmail(email.trim().toLowerCase());
    setMasterPassword(password);
  }, []);

  const logout = useCallback(async () => {
    setMasterPassword(null);
    setUserEmail(null);
  }, []);

  const value = useMemo(
    () => ({ userEmail, masterPassword, isReady, login, setup, logout, bootstrap }),
    [userEmail, masterPassword, isReady, login, setup, logout, bootstrap],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside provider');
  return v;
}
