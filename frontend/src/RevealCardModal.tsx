/**
 * RevealCardModal — Phase F2: Stripe Issuing PAN/CVV reveal with OTP gate.
 *
 * Web flow:
 *   1) Send sensitive OTP to the lead's phone.
 *   2) User enters 6-digit code → server returns single-use reveal_token.
 *   3) Client calls /card/ephemeral-key → server returns ephemeral_key_secret + nonce.
 *   4) Stripe.js mounts secure iframes (CardNumber/Cvc/Expiry) using that key.
 *   5) Auto-hide after `ttl_seconds` (default 60s).
 *
 * Native (iOS/Android via Expo): same flow, but step 4 opens a hosted web reveal page
 * because Stripe Issuing iframes don't work in pure RN. We open the same screen
 * in WebBrowser for now (forwarding the freshly-fetched ephemeral key as URL fragment
 * so it never hits the network log).
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  TextInput,
  StyleSheet,
  Platform,
  ActivityIndicator,
  Modal,
} from 'react-native';
import { X, Eye, ShieldCheck, Smartphone } from 'lucide-react-native';
import { api } from './api';
import { COLORS, FONT } from './theme';

interface Props {
  visible: boolean;
  onClose: () => void;
  groupId: string;
  userId: string;
  cardLast4?: string;
  cardNickname?: string;
}

type Phase = 'idle' | 'sending_otp' | 'awaiting_otp' | 'verifying_otp' | 'fetching_key' | 'revealed' | 'error';

export const RevealCardModal: React.FC<Props> = ({ visible, onClose, groupId, userId, cardLast4, cardNickname }) => {
  const [phase, setPhase] = useState<Phase>('idle');
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [otpInfo, setOtpInfo] = useState<string | null>(null);
  const [revealData, setRevealData] = useState<{ ephemeral_key_secret: string; card_id: string; nonce: string; pub_key: string; ttl: number } | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const tickRef = useRef<any>(null);

  // Stripe Issuing iframe holders (web-only)
  const cardNumberRef = useRef<HTMLDivElement | null>(null);
  const cvcRef = useRef<HTMLDivElement | null>(null);
  const expiryRef = useRef<HTMLDivElement | null>(null);

  const reset = () => {
    setPhase('idle');
    setCode('');
    setError(null);
    setOtpInfo(null);
    setRevealData(null);
    setSecondsLeft(0);
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
  };

  useEffect(() => {
    if (!visible) reset();
  }, [visible]);

  // Step 1: send OTP automatically when modal opens
  useEffect(() => {
    if (!visible || phase !== 'idle') return;
    (async () => {
      setPhase('sending_otp');
      setError(null);
      try {
        const r = await api.sendSensitiveOtp(userId);
        setOtpInfo(r.message);
        setPhase('awaiting_otp');
      } catch (e: any) {
        setError(e?.message || 'Failed to send code');
        setPhase('error');
      }
    })();
  }, [visible, userId, phase]);

  // Step 2: verify OTP -> get reveal_token -> fetch ephemeral key
  const submit = async () => {
    if (!code || code.length < 4) { setError('Enter the 6-digit code'); return; }
    setPhase('verifying_otp');
    setError(null);
    try {
      const v = await api.verifySensitiveOtp(userId, code, 'card_reveal');
      setPhase('fetching_key');
      // Fetch the group to grab the real Stripe Issuing card_id (ic_xxx)
      const g = await api.getGroup(groupId);
      const cardId = (g as any)?.virtual_card?.stripe_card_id;
      if (!cardId || !String(cardId).startsWith('ic_')) {
        throw new Error('No active virtual card on this group');
      }
      const stripeJsLoaded = await ensureStripeJsLoaded(process.env.EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY || '');
      if (!stripeJsLoaded || !stripeJsLoaded.stripe) {
        throw new Error('Stripe.js failed to load (web only)');
      }
      const { stripe, version } = stripeJsLoaded;
      const nonceRes = await stripe.createEphemeralKeyNonce({ issuingCard: cardId });
      const nonce = (nonceRes && (nonceRes as any).nonce) || (nonceRes as any).id || '';
      if (!nonce) throw new Error('Could not create Stripe nonce');

      const key = await api.getCardEphemeralKey(groupId, {
        user_id: userId,
        reveal_token: v.reveal_token,
        nonce,
        stripe_version: version,
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

  // Step 3: render Stripe Issuing iframes after revealData arrives
  useEffect(() => {
    if (phase !== 'revealed' || Platform.OS !== 'web' || !revealData) return;
    let mounted = true;
    (async () => {
      try {
        const loaded = await ensureStripeJsLoaded(revealData.pub_key);
        if (!mounted || !loaded?.stripe) return;
        const stripe: any = loaded.stripe;

        // Stripe.js requires retrieveIssuingCard() to register the card with the SDK
        // before display elements can render.
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
            fontSize: '20px',
            fontWeight: '600',
            color: '#FFFFFF',
            letterSpacing: '2px',
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
        // Start countdown
        tickRef.current = setInterval(() => {
          setSecondsLeft((s) => {
            if (s <= 1) {
              try { numEl.unmount(); cvcEl.unmount(); expEl.unmount(); } catch {}
              if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
              setRevealData(null);
              setPhase('idle');
              onClose();
              return 0;
            }
            return s - 1;
          });
        }, 1000);
      } catch (e: any) {
        setError(e?.message || 'Could not mount Stripe iframe');
        setPhase('error');
      }
    })();
    return () => { mounted = false; if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; } };
  }, [phase, revealData, onClose]);

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.header}>
            <View style={styles.titleRow}>
              <ShieldCheck size={18} color={COLORS.primary} />
              <Text style={styles.title}>Reveal card details</Text>
            </View>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn} testID="reveal-close">
              <X size={18} color={COLORS.text} />
            </TouchableOpacity>
          </View>

          <Text style={styles.sub}>
            {cardNickname || 'KWIKPAY card'} ending {cardLast4 ? `•${cardLast4}` : ''}
          </Text>

          {Platform.OS !== 'web' ? (
            // Native: embed the same /reveal/{id} web page in a WebView so everything
            // happens INSIDE the app. Stripe iframes work fine in modern mobile WebViews.
            (() => {
              try {
                const { WebView } = require('react-native-webview');
                const base = (process.env.EXPO_PUBLIC_BACKEND_URL || '').replace(/\/api$/, '');
                const url = `${base}/reveal/${groupId}?uid=${encodeURIComponent(userId)}`;
                return (
                  <View style={styles.webviewWrap}>
                    <WebView
                      source={{ uri: url }}
                      originWhitelist={["*"]}
                      javaScriptEnabled
                      domStorageEnabled
                      thirdPartyCookiesEnabled
                      sharedCookiesEnabled
                      mixedContentMode="always"
                      allowsInlineMediaPlayback
                      style={{ flex: 1, backgroundColor: COLORS.bg }}
                      testID="reveal-webview"
                    />
                  </View>
                );
              } catch (e: any) {
                return (
                  <View style={styles.nativeNotice}>
                    <Text style={styles.errorText}>WebView unavailable: {e?.message || 'unknown'}</Text>
                  </View>
                );
              }
            })()
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
                testID="reveal-otp-input"
              />
              {error ? <Text style={styles.errorText}>{error}</Text> : null}
              <TouchableOpacity
                onPress={submit}
                disabled={phase !== 'awaiting_otp' || code.length < 6}
                style={[styles.primaryBtn, (phase !== 'awaiting_otp' || code.length < 6) && { opacity: 0.5 }]}
                testID="reveal-otp-submit"
              >
                {phase === 'verifying_otp' || phase === 'fetching_key' ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.primaryBtnText}>Verify & reveal</Text>
                )}
              </TouchableOpacity>
              <Text style={styles.metaSmall}>Code is single-use, valid for 5 minutes.</Text>
            </View>
          ) : phase === 'sending_otp' ? (
            <View style={styles.loadingBlock}>
              <ActivityIndicator color={COLORS.primary} />
              <Text style={styles.helper}>Sending verification code…</Text>
            </View>
          ) : phase === 'revealed' && revealData ? (
            <View style={{ gap: 14 }}>
              <View style={styles.cardFace}>
                <Text style={styles.cardFaceLabel}>Card number</Text>
                {/* @ts-ignore Stripe Elements iframe target (web-only) */}
                <div ref={cardNumberRef} style={{ minHeight: 28 }} />
                <View style={styles.cardFooter}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.cardFaceLabel}>Expiry</Text>
                    {/* @ts-ignore */}
                    <div ref={expiryRef} style={{ minHeight: 24 }} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.cardFaceLabel}>CVC</Text>
                    {/* @ts-ignore */}
                    <div ref={cvcRef} style={{ minHeight: 24 }} />
                  </View>
                </View>
              </View>
              <View style={styles.timerRow}>
                <Eye size={14} color={COLORS.warning} />
                <Text style={styles.timerText}>Hides in {secondsLeft}s</Text>
              </View>
              <Text style={styles.metaSmall}>
                Stripe-secured iframe · PAN/CVC never touch the KWIKPAY server. To reveal again, you'll need a fresh code.
              </Text>
            </View>
          ) : phase === 'error' ? (
            <View style={{ gap: 12 }}>
              <Text style={styles.errorText}>{error}</Text>
              <TouchableOpacity onPress={reset} style={styles.primaryBtn}>
                <Text style={styles.primaryBtnText}>Try again</Text>
              </TouchableOpacity>
            </View>
          ) : null}
        </View>
      </View>
    </Modal>
  );
};

// --- Stripe.js loader (web only) ---
let _stripeJsCache: { stripe: any; version: string } | null = null;
async function ensureStripeJsLoaded(pubKey: string): Promise<{ stripe: any; version: string } | null> {
  if (Platform.OS !== 'web') return null;
  if (_stripeJsCache) return _stripeJsCache;
  if (!pubKey) throw new Error('Missing Stripe publishable key');
  // Stripe Issuing reveal requires a specific apiVersion that supports Issuing card display.
  const STRIPE_API_VERSION = '2024-09-30.acacia';
  // Inject script tag if not present
  if (typeof window !== 'undefined' && !(window as any).Stripe) {
    await new Promise<void>((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://js.stripe.com/v3/';
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('Stripe.js script failed to load'));
      document.head.appendChild(s);
    });
  }
  // @ts-ignore
  const Stripe = typeof window !== 'undefined' ? (window as any).Stripe : null;
  if (!Stripe) throw new Error('Stripe.js global not available');
  const stripe = Stripe(pubKey, { betas: ['issuing_elements_2'], apiVersion: STRIPE_API_VERSION });
  _stripeJsCache = { stripe, version: STRIPE_API_VERSION };
  return _stripeJsCache;
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'center', alignItems: 'center', padding: 16 },
  sheet: { backgroundColor: COLORS.surface, borderRadius: 16, padding: 16, width: '100%', maxWidth: 480, gap: 8, ...(Platform.OS !== 'web' ? { height: '92%' as any, maxHeight: 900 } : {}) },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  closeBtn: { padding: 6, borderRadius: 8 },
  sub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: 8 },
  helper: { fontSize: FONT.sizes.sm, color: COLORS.subtext },
  label: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold },
  codeInput: {
    height: 52, borderRadius: 12, borderWidth: 1, borderColor: COLORS.border,
    backgroundColor: COLORS.bg, paddingHorizontal: 14, color: COLORS.text,
    fontSize: 22, letterSpacing: 8, textAlign: 'center', fontWeight: '700' as any,
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
    backgroundColor: '#0F172A', borderRadius: 14, padding: 18, gap: 14,
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)',
  },
  cardFaceLabel: { color: 'rgba(255,255,255,0.6)', fontSize: 11, marginBottom: 4, letterSpacing: 1.2 },
  cardFooter: { flexDirection: 'row', gap: 16 },
  timerRow: { flexDirection: 'row', alignItems: 'center', gap: 6, justifyContent: 'center' },
  timerText: { color: COLORS.warning, fontSize: 12, fontWeight: '600' as any },
  nativeNotice: {
    backgroundColor: COLORS.bg, borderRadius: 12, padding: 16, gap: 12, alignItems: 'center',
    borderWidth: 1, borderColor: COLORS.border,
  },
  nativeText: { fontSize: FONT.sizes.sm, color: COLORS.subtext, textAlign: 'center' },
  webviewWrap: {
    flex: 1,
    minHeight: 480,
    borderRadius: 12,
    overflow: 'hidden',
    backgroundColor: COLORS.bg,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
});
