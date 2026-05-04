import AsyncStorage from '@react-native-async-storage/async-storage';
import { api, User } from './api';

const KEY = 'gp.user';

export async function saveUser(user: User) {
  await AsyncStorage.setItem(KEY, JSON.stringify(user));
}

export async function loadUser(): Promise<User | null> {
  const raw = await AsyncStorage.getItem(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export async function refreshUser(): Promise<User | null> {
  const u = await loadUser();
  if (!u) return null;
  try {
    const fresh = await api.getUser(u.id);
    await saveUser(fresh);
    return fresh;
  } catch {
    return u;
  }
}

export async function clearUser() {
  await AsyncStorage.removeItem(KEY);
}
