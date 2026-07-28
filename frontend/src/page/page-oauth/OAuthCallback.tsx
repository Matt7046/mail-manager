import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { api } from '@/src/services/api';

const OAUTH_KEY = 'mm_oauth_pending';

type Pending = {
  email: string;
  master_password: string;
  provider: 'google' | 'microsoft';
};

function readQuery(): { code?: string; state?: string; error?: string; errorDesc?: string } {
  if (typeof window === 'undefined') return {};
  const sp = new URLSearchParams(window.location.search);
  return {
    code: sp.get('code') || undefined,
    state: sp.get('state') || undefined,
    error: sp.get('error') || undefined,
    errorDesc: sp.get('error_description') || undefined,
  };
}

export default function OAuthCallback({ provider }: { provider: 'google' | 'microsoft' }) {
  const router = useRouter();
  const params = useLocalSearchParams<{ code?: string; state?: string; error?: string }>();
  const [msg, setMsg] = useState('Completamento OAuth…');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const q = {
        code: (params.code as string) || readQuery().code,
        state: (params.state as string) || readQuery().state,
        error: (params.error as string) || readQuery().error,
        errorDesc: readQuery().errorDesc,
      };
      if (q.error) {
        setMsg(`OAuth annullato: ${q.errorDesc || q.error}`);
        return;
      }
      if (!q.code || !q.state) {
        setMsg('Parametri OAuth mancanti (code/state).');
        return;
      }
      let pending: Pending | null = null;
      try {
        const raw =
          (typeof sessionStorage !== 'undefined' && sessionStorage.getItem(OAUTH_KEY)) ||
          (typeof localStorage !== 'undefined' && localStorage.getItem(OAUTH_KEY)) ||
          null;
        pending = raw ? JSON.parse(raw) : null;
      } catch {
        pending = null;
      }
      if (!pending?.email || !pending?.master_password) {
        setMsg('Sessione vault persa. Torna in Account, rifai login e riprova OAuth.');
        return;
      }
      try {
        const acc = await api.oauthComplete(provider, {
          email: pending.email,
          master_password: pending.master_password,
          code: q.code,
          state: q.state,
        });
        try {
          sessionStorage.removeItem(OAUTH_KEY);
          localStorage.removeItem(OAUTH_KEY);
        } catch {
          /* ignore */
        }
        if (cancelled) return;
        setMsg(`Collegato ${acc.address}. Reindirizzo…`);
        setTimeout(() => router.replace('/accounts'), 800);
      } catch (e: any) {
        if (!cancelled) setMsg(e.message || 'OAuth fallito');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params.code, params.state, params.error, provider, router]);

  return (
    <View style={styles.box}>
      <ActivityIndicator color="#4ecdc4" />
      <Text style={styles.text}>{msg}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    flex: 1,
    backgroundColor: '#0b1220',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  text: { color: '#eee', marginTop: 16, textAlign: 'center', lineHeight: 22 },
});

export { OAUTH_KEY };
