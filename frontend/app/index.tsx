import { Redirect } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { useAuth } from '@/src/contexts/AuthContext';
import { api } from '@/src/services/api';

export default function Index() {
  const { masterPassword, bootstrap } = useAuth();
  const [target, setTarget] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      if (masterPassword) {
        setTarget('/home');
        return;
      }
      const check = await api.checkSetup();
      await bootstrap();
      setTarget(check.setup_done ? '/login' : '/setup');
    })().catch(() => setTarget('/setup'));
  }, [masterPassword, bootstrap]);

  if (!target) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#0b1220' }}>
        <ActivityIndicator color="#4ecdc4" />
      </View>
    );
  }
  return <Redirect href={target as any} />;
}
