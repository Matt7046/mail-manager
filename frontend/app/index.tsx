import { Redirect } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { useAuth } from '@/src/contexts/AuthContext';
import { oauthCallbackPathFromQuery } from '@/src/lib/oauthStrayRedirect';

export default function Index() {
  const { masterPassword, bootstrap, isReady } = useAuth();
  const [target, setTarget] = useState<string | null>(null);

  useEffect(() => {
    if (!isReady) return;
    (async () => {
      const oauthPath = oauthCallbackPathFromQuery();
      if (oauthPath) {
        setTarget(oauthPath);
        return;
      }
      if (masterPassword) {
        setTarget('/home');
        return;
      }
      await bootstrap();
      // Always show login (Accedi + Crea nuovo account) — never force setup alone.
      setTarget('/login');
    })().catch(() => setTarget('/login'));
  }, [masterPassword, bootstrap, isReady]);

  if (!target) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#0b1220' }}>
        <ActivityIndicator color="#4ecdc4" />
      </View>
    );
  }
  return <Redirect href={target as any} />;
}
