/**
 * KV + secure storage (come Password Manager, versione snella).
 * Web: AsyncStorage/IndexedDB. Native: SecureStore per i secret.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';

async function secureStore() {
  return import('expo-secure-store');
}

export const storage = {
  async getItem(key: string, fallback: string | null = null): Promise<string | null> {
    try {
      const raw = await AsyncStorage.getItem(key);
      if (raw == null) return fallback;
      try {
        return JSON.parse(raw) as string;
      } catch {
        return raw;
      }
    } catch {
      return fallback;
    }
  },

  async setItem(key: string, value: string): Promise<void> {
    await AsyncStorage.setItem(key, JSON.stringify(value));
  },

  async secureGet(key: string, fallback: string | null = null): Promise<string | null> {
    try {
      if (Platform.OS === 'web') {
        return this.getItem(`sec_${key}`, fallback);
      }
      const SecureStore = await secureStore();
      const raw = await SecureStore.getItemAsync(key);
      if (raw == null) return fallback;
      try {
        return JSON.parse(raw) as string;
      } catch {
        return raw;
      }
    } catch {
      return fallback;
    }
  },

  async secureSet(key: string, value: string): Promise<void> {
    if (Platform.OS === 'web') {
      await this.setItem(`sec_${key}`, value);
      return;
    }
    const SecureStore = await secureStore();
    await SecureStore.setItemAsync(key, JSON.stringify(value));
  },
};
