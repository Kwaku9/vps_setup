import AsyncStorage from '@react-native-async-storage/async-storage';

const KEYS = {
  onboarding: '@aicortex/onboarding',
  experts: '@aicortex/experts',
  agents_cache: '@aicortex/agents_cache',
  conversations: '@aicortex/conversations',
  history: '@aicortex/history',
} as const;

export { KEYS as STORAGE_KEYS };

export async function getItem<T>(key: string): Promise<T | null> {
  const raw = await AsyncStorage.getItem(key);
  if (raw === null) return null;
  return JSON.parse(raw) as T;
}

export async function setItem<T>(key: string, value: T): Promise<void> {
  await AsyncStorage.setItem(key, JSON.stringify(value));
}

export async function removeItem(key: string): Promise<void> {
  await AsyncStorage.removeItem(key);
}
