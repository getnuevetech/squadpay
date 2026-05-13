/**
 * Push notification registration + delivery (June 2025).
 *
 * Call `registerForPushAsync(userId)` once after auth so we capture the
 * device's Expo push token and persist it on the user record. The backend
 * uses these tokens to dispatch pushes via expo-server-sdk when admin
 * Notification Config enables push for an event.
 *
 * Notes:
 *  - Push works in development builds + production builds, NOT Expo Go
 *    on iOS (Apple restriction since SDK 53). Android Expo Go still works.
 *  - On web, this is a no-op (we don't support web push yet).
 *  - Foreground notifications use the default behavior (show alert + sound).
 */
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform } from 'react-native';
import Constants from 'expo-constants';
import { api } from './api';

// Show notifications even when app is in foreground.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

async function _ensureAndroidChannel() {
  if (Platform.OS !== 'android') return;
  try {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'SquadPay',
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: '#7C3AED',
    });
  } catch {}
}

export async function registerForPushAsync(userId: string): Promise<string | null> {
  // Web isn't supported — silently skip.
  if (Platform.OS === 'web') return null;
  // Push requires a real device for tokens.
  if (!Device.isDevice) return null;

  await _ensureAndroidChannel();

  // Ask for permission if not yet granted.
  try {
    const settings = await Notifications.getPermissionsAsync();
    let status = settings.status;
    if (status !== 'granted') {
      const req = await Notifications.requestPermissionsAsync();
      status = req.status;
    }
    if (status !== 'granted') return null;

    // EAS projectId is required for getting an ExponentPushToken in SDK 49+.
    const projectId =
      (Constants?.expoConfig as any)?.extra?.eas?.projectId ||
      (Constants as any)?.easConfig?.projectId;

    const tokenResp = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined,
    );
    const token = tokenResp?.data;
    if (!token) return null;

    // Persist on the backend (idempotent by token).
    try {
      await api.registerPushToken(userId, token, Platform.OS);
    } catch (e) {
      // Don't blow up the app if backend isn't reachable yet — token
      // can be re-registered next launch.
      // eslint-disable-next-line no-console
      console.warn('[push] backend register failed:', e);
    }
    return token;
  } catch (e) {
    // Permissions denied / dev build issue — silently skip.
    // eslint-disable-next-line no-console
    console.warn('[push] register failed:', e);
    return null;
  }
}

export async function unregisterPushAsync(userId: string, token: string) {
  if (Platform.OS === 'web') return;
  try {
    await api.unregisterPushToken(userId, token);
  } catch {}
}
