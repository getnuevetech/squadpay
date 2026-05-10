/**
 * SessionGuard
 * ─────────────────────────────────────────────────────────────────────────
 * Mounts at the app root and enforces single-active-session by polling
 * /auth/check-session every 30s plus on every app-foreground transition.
 *
 * If the backend reports the device's stored session_id no longer matches
 * the user's `current_session_id` (because they signed in on another device),
 * we clear local credentials and bounce the user to /auth with a friendly
 * "you've been signed in elsewhere" message.
 *
 * Design notes:
 * - Pure check-only. Doesn't intercept regular API calls (those continue to
 *   work for the brief window between sign-out-on-other-device and the next
 *   poll — acceptable for SquadPay since money moves go through Stripe which
 *   has its own auth).
 * - Silent failure on network errors (don't punish offline users).
 * - Triggers exactly ONCE per "kicked-out" event so the user doesn't see
 *   stacked alerts when poll + foreground fire close together.
 */
import React, { useEffect, useRef } from 'react';
import { AppState, AppStateStatus, Alert, Platform } from 'react-native';
import { useRouter, useSegments } from 'expo-router';
import { api } from '../api';
import { loadUser, loadSessionId, clearUser } from '../session';

const POLL_INTERVAL_MS = 30_000; // 30 seconds

export function SessionGuard() {
  const router = useRouter();
  const segments = useSegments();
  const kickedRef = useRef(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Track the current route so we don't bounce out of /auth or /admin.
  const segmentsRef = useRef<string[]>([]);
  useEffect(() => {
    segmentsRef.current = segments as unknown as string[];
  }, [segments]);

  const onKickedOut = async (reason?: string) => {
    if (kickedRef.current) return;
    kickedRef.current = true;
    try {
      await clearUser();
    } catch {
      // ignore storage errors
    }
    const message =
      'Your account was signed in on another device. Please log in again.';
    if (Platform.OS === 'web') {
      // RN's Alert is a toast on web; window.alert is more reliable.
      try {
        // eslint-disable-next-line no-alert
        window.alert(message);
      } catch {
        Alert.alert('Signed out', message);
      }
    } else {
      Alert.alert('Signed out', message);
    }
    try {
      router.replace('/auth?intent=signin');
    } catch {
      // best-effort; if router unavailable we already cleared storage
    }
  };

  const onSignedIn = () => {
    // Reset the kicked flag whenever the app reaches a state where there's a
    // valid local session again (covers re-login flow inside the same JS
    // session).
    kickedRef.current = false;
  };

  const checkOnce = async () => {
    const segs = segmentsRef.current || [];
    // Skip checks while the user is still on /auth or in admin (admin uses a
    // separate auth surface).
    if (segs.includes('auth') || segs.includes('admin')) return;
    let user, sid;
    try {
      [user, sid] = await Promise.all([loadUser(), loadSessionId()]);
    } catch {
      return;
    }
    if (!user || !sid) {
      // No active session locally — nothing to protect; reset flag so a
      // subsequent login can be re-protected.
      onSignedIn();
      return;
    }
    try {
      const res = await api.checkSession(user.id, sid);
      if (!res?.valid) {
        await onKickedOut(res?.reason);
      } else {
        // Healthy session — make sure the kicked flag stays false.
        if (kickedRef.current) onSignedIn();
      }
    } catch {
      // Network error or backend unreachable — silently ignore.
    }
  };

  // Mount: start polling + AppState listener.
  useEffect(() => {
    // First check fires after a short delay to avoid hammering during cold
    // boot when the user record may be loading anyway.
    const bootTimer = setTimeout(checkOnce, 1500);

    pollingRef.current = setInterval(checkOnce, POLL_INTERVAL_MS);

    const onAppState = (status: AppStateStatus) => {
      if (status === 'active') {
        // App returned to foreground — check immediately.
        checkOnce();
      }
    };
    const sub = AppState.addEventListener('change', onAppState);

    // Web only: react to tab refocus (AppState doesn't fire reliably on web).
    let visibilityHandler: (() => void) | null = null;
    if (Platform.OS === 'web' && typeof document !== 'undefined') {
      visibilityHandler = () => {
        if (document.visibilityState === 'visible') checkOnce();
      };
      document.addEventListener('visibilitychange', visibilityHandler);
    }

    return () => {
      clearTimeout(bootTimer);
      if (pollingRef.current) clearInterval(pollingRef.current);
      sub.remove();
      if (visibilityHandler && typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', visibilityHandler);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // No UI — purely behavioral.
  return null;
}

export default SessionGuard;
