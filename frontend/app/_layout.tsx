import { Stack } from 'expo-router';
import { AuthProvider } from '@/src/contexts/AuthContext';

export default function RootLayout() {
  return (
    <AuthProvider>
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: '#0b1220' } }} />
    </AuthProvider>
  );
}
