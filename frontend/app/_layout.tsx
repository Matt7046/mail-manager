import { Stack, useRouter } from 'expo-router';
import { useEffect } from 'react';
import { Platform } from 'react-native';
import { AuthProvider, useAuth } from '@/src/contexts/AuthContext';

/** Focus da Service Worker: porta all'inbox e forza sync IMAP. */
function NotificationClickBridge() {
  const router = useRouter();
  const { masterPassword, isReady } = useAuth();

  useEffect(() => {
    if (Platform.OS !== 'web' || typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
      return;
    }
    const onMessage = (event: MessageEvent) => {
      if (!event.data || event.data.type !== 'NOTIFICATION_CLICK') return;
      if (!isReady) return;
      try {
        sessionStorage.setItem('mm_force_sync', '1');
      } catch {
        /* ignore */
      }
      if (masterPassword) {
        router.replace('/home');
      } else {
        router.replace('/login');
      }
    };
    navigator.serviceWorker.addEventListener('message', onMessage);
    return () => navigator.serviceWorker.removeEventListener('message', onMessage);
  }, [router, masterPassword, isReady]);

  return null;
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <NotificationClickBridge />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: '#0b1220' } }} />
    </AuthProvider>
  );
}
