/**
 * HomeWidgets — admin-configurable widget cards rendered on the home page
 * below the FeaturedBillCard.
 *
 * Two widgets:
 *   1. <WhatsNextCard>  — picks the first matching rule from an admin-
 *                          editable ordered list based on user state.
 *   2. <PromoBanner>    — single evergreen card with optional × dismiss.
 *
 * Both pull config from GET /api/runtime/home-widgets. The config is
 * cached in module-scope memory for 60s so navigating between tabs
 * doesn't refetch on every focus.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useRouter } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  ShieldAlert, ShieldCheck, AlertCircle, AlertTriangle, Info, PlusCircle,
  Gift, Camera, Sparkles, Zap, Target, Users, DollarSign, CreditCard,
  Bell, Heart, Star, Award, TrendingUp, Rocket, MessageCircle, LifeBuoy,
  ChevronRight, X,
} from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../theme';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || '';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────
type WhatsNextRule = {
  key: 'verify_phone' | 'outstanding_owed' | 'no_squads' | 'invite_friends' | string;
  enabled: boolean;
  title: string;
  subtitle: string;
  icon: string;
  route: string;
};
type Config = {
  whats_next_card: { enabled: boolean; rules: WhatsNextRule[] };
  promo_banner: {
    enabled: boolean;
    title: string;
    body: string;
    icon: string;
    route: string;
    dismissible: boolean;
    dismiss_days: number;
  };
};

export type UserState = {
  verified: boolean;
  outstandingCents: number;
  outstandingGroupsCount: number;
  hasAnySquad: boolean;
  inviteEnabled: boolean;
};

// ─────────────────────────────────────────────────────────────────────────────
// Icon resolver — matches the backend ALLOWED_ICONS allow-list.
// ─────────────────────────────────────────────────────────────────────────────
const ICONS: Record<string, any> = {
  'shield-alert': ShieldAlert, 'shield-check': ShieldCheck,
  'alert-circle': AlertCircle, 'alert-triangle': AlertTriangle,
  info: Info, 'plus-circle': PlusCircle, gift: Gift, camera: Camera,
  sparkles: Sparkles, zap: Zap, target: Target, users: Users,
  'dollar-sign': DollarSign, 'credit-card': CreditCard, bell: Bell,
  heart: Heart, star: Star, award: Award, 'trending-up': TrendingUp,
  rocket: Rocket, 'message-circle': MessageCircle, 'life-buoy': LifeBuoy,
};
function IconFor({ name, size = 22, color = COLORS.primary }: { name: string; size?: number; color?: string }) {
  const C = ICONS[name] || Sparkles;
  return <C size={size} color={color} />;
}

// ─────────────────────────────────────────────────────────────────────────────
// Cached fetcher (module-scope; 60s TTL).
// ─────────────────────────────────────────────────────────────────────────────
let _cache: { at: number; cfg: Config | null } = { at: 0, cfg: null };
async function fetchConfig(): Promise<Config | null> {
  const now = Date.now();
  if (_cache.cfg && now - _cache.at < 60_000) return _cache.cfg;
  try {
    const r = await fetch(`${BACKEND}/api/runtime/home-widgets?t=${now}`, { cache: 'no-store' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const cfg = (await r.json()) as Config;
    _cache = { at: now, cfg };
    return cfg;
  } catch {
    return _cache.cfg; // serve stale on error
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Template substitution for the "outstanding_owed" rule.
// ─────────────────────────────────────────────────────────────────────────────
function applyTemplate(s: string, vars: Record<string, string>) {
  return Object.keys(vars).reduce((acc, k) => acc.replaceAll(`{${k}}`, vars[k]), s);
}

// ─────────────────────────────────────────────────────────────────────────────
// Rule matching logic — returns the first ENABLED rule whose trigger fires
// for the given user state.
// ─────────────────────────────────────────────────────────────────────────────
function pickWhatsNextRule(rules: WhatsNextRule[], st: UserState): { rule: WhatsNextRule; vars: Record<string, string> } | null {
  for (const r of rules) {
    if (!r.enabled) continue;
    switch (r.key) {
      case 'verify_phone':
        if (!st.verified) return { rule: r, vars: {} };
        break;
      case 'outstanding_owed':
        if (st.outstandingCents > 0) {
          const amount = (st.outstandingCents / 100).toFixed(2);
          const count = String(st.outstandingGroupsCount || 1);
          const plural = st.outstandingGroupsCount === 1 ? '' : 's';
          return { rule: r, vars: { amount, count, plural } };
        }
        break;
      case 'no_squads':
        if (!st.hasAnySquad) return { rule: r, vars: {} };
        break;
      case 'invite_friends':
        if (st.inviteEnabled) return { rule: r, vars: {} };
        break;
    }
  }
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// <HomeWidgets> — wraps both widgets; caller passes userState.
// ─────────────────────────────────────────────────────────────────────────────
type Props = { userState: UserState };

export function HomeWidgets({ userState }: Props) {
  const router = useRouter();
  const [cfg, setCfg] = useState<Config | null>(null);
  const [promoHidden, setPromoHidden] = useState(true); // start hidden until we check AsyncStorage
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const c = await fetchConfig();
      if (cancelled) return;
      setCfg(c);
      // Check promo dismiss state
      if (c?.promo_banner?.enabled && c.promo_banner.dismissible) {
        try {
          const until = await AsyncStorage.getItem('home.promo.dismissedUntil');
          if (until && Date.now() < Number(until)) {
            setPromoHidden(true);
          } else {
            setPromoHidden(false);
          }
        } catch {
          setPromoHidden(false);
        }
      } else {
        setPromoHidden(false);
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const picked = useMemo(() => {
    if (!cfg?.whats_next_card?.enabled) return null;
    return pickWhatsNextRule(cfg.whats_next_card.rules || [], userState);
  }, [cfg, userState]);

  const dismissPromo = useCallback(async () => {
    setPromoHidden(true);
    try {
      const days = cfg?.promo_banner?.dismiss_days ?? 7;
      const until = Date.now() + Math.max(0, days) * 24 * 60 * 60 * 1000;
      await AsyncStorage.setItem('home.promo.dismissedUntil', String(until));
    } catch {
      /* ignore */
    }
  }, [cfg]);

  if (loading) {
    return (
      <View style={styles.loadingPad}>
        <ActivityIndicator size="small" color={COLORS.primary} />
      </View>
    );
  }

  // Defensive guard — if userState is somehow missing or malformed (e.g.
  // parent passed undefined during a render race), bail out gracefully
  // instead of crashing the entire home screen.
  if (!userState) return null;

  const showWhatsNext = Boolean(picked);
  const showPromo = Boolean(cfg?.promo_banner?.enabled) && !promoHidden;
  if (!showWhatsNext && !showPromo) return null;

  return (
    <View style={styles.wrap}>
      {showWhatsNext && picked && (
        <Pressable
          onPress={() => router.push(picked.rule.route as any)}
          style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}
          testID="home-widget-whats-next"
        >
          <View style={styles.iconWrap}>
            <IconFor name={picked.rule.icon} />
          </View>
          <View style={styles.body}>
            <Text style={styles.title} numberOfLines={1}>
              {applyTemplate(picked.rule.title, picked.vars)}
            </Text>
            <Text style={styles.sub} numberOfLines={2}>
              {applyTemplate(picked.rule.subtitle, picked.vars)}
            </Text>
          </View>
          <ChevronRight size={18} color={COLORS.subtext} />
        </Pressable>
      )}

      {showPromo && cfg && (
        <Pressable
          onPress={() => router.push(cfg.promo_banner.route as any)}
          style={({ pressed }) => [styles.card, styles.cardPromo, pressed && styles.cardPressed]}
          testID="home-widget-promo"
        >
          <View style={[styles.iconWrap, styles.iconWrapPromo]}>
            <IconFor name={cfg.promo_banner.icon} color="#fff" />
          </View>
          <View style={styles.body}>
            <Text style={styles.title} numberOfLines={1}>{cfg.promo_banner.title}</Text>
            <Text style={styles.sub} numberOfLines={2}>{cfg.promo_banner.body}</Text>
          </View>
          {cfg.promo_banner.dismissible ? (
            <TouchableOpacity
              onPress={dismissPromo}
              hitSlop={10}
              style={styles.dismissBtn}
              testID="home-widget-promo-dismiss"
            >
              <X size={16} color={COLORS.subtext} />
            </TouchableOpacity>
          ) : (
            <ChevronRight size={18} color={COLORS.subtext} />
          )}
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: SPACING.md,
    paddingTop: SPACING.md,
    gap: SPACING.sm,
  },
  loadingPad: { paddingVertical: SPACING.lg, alignItems: 'center' },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.md,
    gap: SPACING.md,
  },
  cardPressed: { opacity: 0.85 },
  cardPromo: {
    backgroundColor: COLORS.primaryLight,
    borderColor: 'rgba(124, 58, 237, 0.18)',
  },
  iconWrap: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center', justifyContent: 'center',
  },
  iconWrapPromo: { backgroundColor: COLORS.primary },
  body: { flex: 1 },
  title: { fontSize: FONT.body, fontWeight: '700', color: COLORS.text },
  sub: { fontSize: FONT.small, color: COLORS.subtext, marginTop: 2 },
  dismissBtn: { padding: 4 },
});

export default HomeWidgets;
