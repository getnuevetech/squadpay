/**
 * Standalone web reveal page (Phase F2).
 * Opened from native app via system browser:
 *   ${EXPO_PUBLIC_BACKEND_URL}/reveal/{group_id}?uid={user_id}
 *
 * Flow: send sensitive OTP → user enters code → verify → fetch ephemeral key →
 * mount Stripe Issuing iframes (PAN/CVV/Exp) → 60s auto-hide.
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  TextInput,
  StyleSheet,
  Platform,
  ActivityIndicator,
  ScrollView,
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { ShieldCheck, Eye } from 'lucide-react-native';
import { api } from '../../src/api';
import { COLORS, FONT, RADIUS } from '../../src/theme';

type Phase = 'idle' | 'sending_otp' | 'awaiting_otp' | 'verifying_otp' | 'fetching_key' | 'revealed' | 'error';

let _stripeJsCache: { stripe: any; version: string } | null = null;
async function ensureStripeJsLoaded(pubKey: string): Promise<{ stripe: any; version: string } | null> {
  if (Platform.OS !== 'web') return null;
  if (_stripeJsCache) return _stripeJsCache;
  if (!pubKey) throw new Error('Missing Stripe publishable key');
  const STRIPE_API_VERSION = '2024-09-30.acacia';
  if (typeof window !== 'undefined' && !(window as any).Stripe) {
    await new Promise<void>((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://js.stripe.com/v3/';
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('Stripe.js script failed to load'));
      document.head.appendChild(s);
    });
  }
  const Stripe = typeof window !== 'undefined' ? (window as any).Stripe : null;
  if (!Stripe) throw new Error('Stripe.js global not available');
  const stripe = Stripe(pubKey, { betas: ['issuing_elements_2'], apiVersion: STRIPE_API_VERSION });
  _stripeJsCache = { stripe, version: STRIPE_API_VERSION };
  return _stripeJsCache;
}

export default function RevealPage() {
  const params = useLocalSearchParams<{ id: string; uid?: string }>();
  const groupId = params.id;
  const userId = params.uid;
  const [phase, setPhase] = useState<Phase>('idle');
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [otpInfo, setOtpInfo] = useState<string | null>(null);
  const [revealData, setRevealData] = useState<any>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const tickRef = useRef<any>(null);

  const cardNumberRef = useRef<HTMLDivElement | null>(null);
  const cvcRef = useRef<HTMLDivElement | null>(null);
  const expiryRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!userId || !groupId || phase !== 'idle') return;
    (async () => {
      setPhase('sending_otp');
      try {
        const r = await api.sendSensitiveOtp(userId);
        setOtpInfo(r.message);
        setPhase('awaiting_otp');
      } catch (e: any) {
        setError(e?.message || 'Failed to send code');
        setPhase('error');
      }
    })();
  }, [userId, groupId, phase]);

  const submit = async () => {
    if (!code || code.length < 4 || !userId || !groupId) {
      setError('Enter the 6-digit code');
      return;
    }
    setPhase('verifying_otp');
    setError(null);
    try {
      const v = await api.verifySensitiveOtp(userId, code, 'card_reveal');
      setPhase('fetching_key');
      // Fetch the group first to get the real Stripe card_id (ic_xxx) — Stripe rejects 'placeholder'.
      const g = await api.getGroup(groupId);
      const cardId = (g as any)?.virtual_card?.stripe_card_id;
      if (!cardId || !String(cardId).startsWith('ic_')) {
        throw new Error('No active virtual card on this group');
      }
      const loaded = await ensureStripeJsLoaded(process.env.EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY || '');
      if (!loaded?.stripe) throw new Error('Stripe.js failed to load');
      const nonceRes = await loaded.stripe.createEphemeralKeyNonce({ issuingCard: cardId });
      const nonce = (nonceRes as any).nonce || (nonceRes as any).id;
      if (!nonce) throw new Error('Could not generate Stripe nonce');
      const key = await api.getCardEphemeralKey(groupId, {
        user_id: userId,
        reveal_token: v.reveal_token,
        nonce,
        stripe_version: loaded.version,
      });
      setRevealData({
        ephemeral_key_secret: key.ephemeral_key_secret,
        card_id: key.card_id,
        nonce: key.nonce,
        pub_key: key.stripe_publishable_key,
        ttl: key.ttl_seconds || 60,
      });
      setSecondsLeft(key.ttl_seconds || 60);
      setPhase('revealed');
    } catch (e: any) {
      setError(e?.message || 'Verification failed');
      setPhase('awaiting_otp');
    }
  };

  useEffect(() => {
    if (phase !== 'revealed' || Platform.OS !== 'web' || !revealData) return;
    let mounted = true;
    (async () => {
      try {
        const loaded = await ensureStripeJsLoaded(revealData.pub_key);
        if (!mounted || !loaded?.stripe) return;
        const stripe: any = loaded.stripe;

        // CRITICAL: Stripe.js requires retrieveIssuingCard() to register the card with the
        // SDK BEFORE the display elements can render. Otherwise the iframe says
        // "Issuing card ic_xxx has not been retrieved."
        try {
          await stripe.retrieveIssuingCard(revealData.card_id, {
            nonce: revealData.nonce,
            ephemeralKeySecret: revealData.ephemeral_key_secret,
          });
        } catch (rerr: any) {
          throw new Error(`retrieveIssuingCard failed: ${rerr?.message || rerr}`);
        }

        const elements = stripe.elements();
        const styles = {
          base: {
            fontFamily: 'system-ui, -apple-system, sans-serif',
            fontSize: '15px',
            fontWeight: '600',
            color: '#FFFFFF',
            letterSpacing: '0.5px',
          },
        };
        const numEl = elements.create('issuingCardNumberDisplay', {
          issuingCard: revealData.card_id,
          nonce: revealData.nonce,
          ephemeralKeySecret: revealData.ephemeral_key_secret,
          style: styles,
        });
        const cvcEl = elements.create('issuingCardCvcDisplay', {
          issuingCard: revealData.card_id,
          nonce: revealData.nonce,
          ephemeralKeySecret: revealData.ephemeral_key_secret,
          style: styles,
        });
        const expEl = elements.create('issuingCardExpiryDisplay', {
          issuingCard: revealData.card_id,
          nonce: revealData.nonce,
          ephemeralKeySecret: revealData.ephemeral_key_secret,
          style: styles,
        });
        if (cardNumberRef.current) numEl.mount(cardNumberRef.current);
        if (cvcRef.current) cvcEl.mount(cvcRef.current);
        if (expiryRef.current) expEl.mount(expiryRef.current);
        tickRef.current = setInterval(() => {
          setSecondsLeft((s) => {
            if (s <= 1) {
              try { numEl.unmount(); cvcEl.unmount(); expEl.unmount(); } catch {}
              if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
              setRevealData(null);
              setPhase('idle');
              return 0;
            }
            return s - 1;
          });
        }, 1000);
      } catch (e: any) {
        setError(e?.message || 'Could not mount iframe');
        setPhase('error');
      }
    })();
    return () => { mounted = false; if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; } };
  }, [phase, revealData]);

  if (Platform.OS !== 'web') {
    return (
      <View style={styles.center}>
        <Text style={styles.errorText}>This page can only be opened in a browser.</Text>
      </View>
    );
  }
  if (!userId || !groupId) {
    return (
      <View style={styles.center}>
        <Text style={styles.errorText}>Missing parameters. Please reopen this page from the KWIKPAY app.</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.scroll}>
      <View style={styles.sheet}>
        <View style={styles.header}>
          <ShieldCheck size={20} color={COLORS.primary} />
          <Text style={styles.title}>Reveal card details</Text>
        </View>
        <Text style={styles.sub}>Group · {String(groupId).slice(0, 14)}</Text>

        {phase === 'sending_otp' ? (
          <View style={styles.loadingBlock}>
            <ActivityIndicator color={COLORS.primary} />
            <Text style={styles.helper}>Sending verification code…</Text>
          </View>
        ) : phase === 'awaiting_otp' || phase === 'verifying_otp' || phase === 'fetching_key' ? (
          <View style={{ gap: 14 }}>
            {otpInfo ? <Text style={styles.helper}>{otpInfo}</Text> : null}
            <Text style={styles.label}>Enter 6-digit code from SMS</Text>
            <TextInput
              style={styles.codeInput}
              value={code}
              onChangeText={(t) => setCode(t.replace(/[^0-9]/g, '').slice(0, 6))}
              keyboardType="number-pad"
              placeholder="000000"
              placeholderTextColor={COLORS.disabledText}
              autoFocus
            />
            {error ? <Text style={styles.errorText}>{error}</Text> : null}
            <TouchableOpacity
              onPress={submit}
              disabled={phase !== 'awaiting_otp' || code.length < 6}
              style={[styles.primaryBtn, (phase !== 'awaiting_otp' || code.length < 6) && { opacity: 0.5 }]}
            >
              {phase === 'verifying_otp' || phase === 'fetching_key' ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.primaryBtnText}>Verify & reveal</Text>
              )}
            </TouchableOpacity>
            <Text style={styles.metaSmall}>Code is single-use, valid for 5 minutes.</Text>
          </View>
        ) : phase === 'revealed' && revealData ? (
          <View style={{ gap: 14 }}>
            <View style={styles.cardFace}>
              <Text style={styles.cardFaceLabel}>Card number</Text>
              {/* @ts-ignore */}
              <div ref={cardNumberRef} style={{ minHeight: 32 }} />
              <View style={styles.cardFooter}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardFaceLabel}>Expiry</Text>
                  {/* @ts-ignore */}
                  <div ref={expiryRef} style={{ minHeight: 28 }} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardFaceLabel}>CVC</Text>
                  {/* @ts-ignore */}
                  <div ref={cvcRef} style={{ minHeight: 28 }} />
                </View>
              </View>
            </View>
            <View style={styles.timerRow}>
              <Eye size={14} color={COLORS.warning} />
              <Text style={styles.timerText}>Hides in {secondsLeft}s · then close this tab</Text>
            </View>
            <Text style={styles.metaSmall}>
              Stripe-secured iframe. PAN/CVC never touch the KWIKPAY server. To reveal again, close
              this tab and tap "Reveal" again from the app.
            </Text>
          </View>
        ) : phase === 'error' ? (
          <View style={{ gap: 12 }}>
            <Text style={styles.errorText}>{error}</Text>
            <TouchableOpacity onPress={() => { setError(null); setCode(''); setPhase('idle'); }} style={styles.primaryBtn}>
              <Text style={styles.primaryBtnText}>Try again</Text>
            </TouchableOpacity>
          </View>
        ) : null}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flexGrow: 1, backgroundColor: COLORS.bg, justifyContent: 'flex-start', alignItems: 'center', padding: 12 },
  sheet: { backgroundColor: COLORS.surface, borderRadius: 16, padding: 16, width: '100%', maxWidth: 460, gap: 12, marginTop: 8 },
  header: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  title: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  sub: { fontSize: FONT.sizes.xs, color: COLORS.subtext },
  helper: { fontSize: FONT.sizes.sm, color: COLORS.subtext },
  label: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold },
  codeInput: {
    height: 56, borderRadius: 12, borderWidth: 1, borderColor: COLORS.border,
    backgroundColor: COLORS.bg, paddingHorizontal: 14, color: COLORS.text,
    fontSize: 24, letterSpacing: 8, textAlign: 'center', fontWeight: '700' as any,
  },
  primaryBtn: {
    backgroundColor: COLORS.primary, borderRadius: 12, paddingVertical: 14,
    alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 8,
  },
  primaryBtnText: { color: '#fff', fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold },
  errorText: { color: COLORS.danger, fontSize: FONT.sizes.sm },
  metaSmall: { fontSize: FONT.sizes.xs, color: COLORS.subtext },
  loadingBlock: { alignItems: 'center', gap: 10, paddingVertical: 18 },
  cardFace: {
    backgroundColor: '#0F172A', borderRadius: 14, paddingVertical: 16, paddingHorizontal: 12, gap: 14,
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)',
  },
  cardFaceLabel: { color: 'rgba(255,255,255,0.6)', fontSize: 10, marginBottom: 4, letterSpacing: 1.2, textTransform: 'uppercase' as any },
  cardFooter: { flexDirection: 'row', gap: 12 },
  timerRow: { flexDirection: 'row', alignItems: 'center', gap: 6, justifyContent: 'center' },
  timerText: { color: COLORS.warning, fontSize: 13, fontWeight: '600' as any },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 20, backgroundColor: COLORS.bg },
});
