import AsyncStorage from '@react-native-async-storage/async-storage';
import { api, User } from './api';

const KEY = 'gp.user';
const SID_KEY = 'gp.session_id';

export async function saveUser(user: User & { session_id?: string }) {
  // Persist the user object minus session_id (it's stored in its own key so
  // legacy code that calls loadUser() doesn't accidentally surface it).
  const { session_id, ...rest } = user as any;
  await AsyncStorage.setItem(KEY, JSON.stringify(rest));
  if (session_id) {
    await AsyncStorage.setItem(SID_KEY, session_id);
  }
}

export async function saveSessionId(session_id: string) {
  await AsyncStorage.setItem(SID_KEY, session_id);
}

export async function loadSessionId(): Promise<string | null> {
  return await AsyncStorage.getItem(SID_KEY);
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
  await AsyncStorage.removeItem(SID_KEY);
}
