import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, Share, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { ArrowLeft, Gift, Copy, Share2, ShieldCheck, Wallet, UserPlus } from 'lucide-react-native';
import { api, ReferralSummary } from '../src/api';
import { loadUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';

async function copyText(text: string) {
  try {
    if (Platform.OS === 'web' && typeof navigator !== 'undefined' && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    // RN: dynamic import expo-clipboard if installed; fallback to Share
    try {
      const Clipboard = require('expo-clipboard');
      await Clipboard.setStringAsync(text);
      return true;
    } catch {}
  } catch {}
  return false;
}

export default function InviteScreen() {
  const router = useRouter();
  const [user, setUser] = useState<Awaited<ReturnType<typeof loadUser>>>(null);
  const [summary, setSummary] = useState<ReferralSummary | null>(null);
  const [busy, setBusy] = useState(true);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const u = await loadUser();
      setUser(u);
      if (u) {
        const s = await api.getReferralSummary(u.id);
        setSummary(s);
      }
    } catch (e: any) {
      Alert.alert('Error', e?.message || 'Failed to load');
    } finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const code = summary?.referral_code || user?.referral_code || '';
  const enabled = !!summary?.settings?.enabled;
  const referrerCredit = summary?.settings?.referrer_credit || 0;
  const refereeCredit = summary?.settings?.referee_credit || 0;

  const shareMsg = `Join me on GroupPay — easiest way to split bills with friends. Use my code ${code} when you sign up${enabled && refereeCredit > 0 ? ` and get $${refereeCredit.toFixed(2)} welcome credit` : ''}.`;

  const onCopy = async () => {
    if (!code) return;
    const ok = await copyText(code);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } else {
      Alert.alert('Code', code);
    }
  };

  const onShare = async () => {
    try {
      if (Platform.OS === 'web') {
        const ok = await copyText(shareMsg);
        Alert.alert(ok ? 'Copied!' : 'Share', shareMsg);
        return;
      }
      await Share.share({ message: shareMsg });
    } catch {}
  };

  if (busy || !user) {
    return <SafeAreaView style={styles.center}><ActivityIndicator color={COLORS.primary} /></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={{ padding: SPACING.md, paddingBottom: SPACING.xxl }}>
        <TouchableOpacity
          onPress={() => {
            try {
              if ((router as any).canGoBack && (router as any).canGoBack()) {
                router.back();
              } else {
                router.replace('/');
              }
            } catch {
              router.replace('/');
            }
          }}
          style={styles.backBtn}
          activeOpacity={0.7}
          testID="invite-back"
        >
          <ArrowLeft size={18} color={COLORS.text} />
          <Text style={styles.backText}>Home</Text>
        </TouchableOpacity>

        <View style={styles.heroCard} testID="invite-hero">
          <View style={styles.heroIcon}>
            <Gift size={28} color="#fff" />
          </View>
          <Text style={styles.heroTitle}>Invite friends to GroupPay</Text>
          <Text style={styles.heroSub}>Share your code. The next bill splits itself.</Text>
        </View>

        <View style={styles.codeCard}>
          <Text style={styles.codeLabel}>YOUR REFERRAL CODE</Text>
          <Text style={styles.codeValue} testID="invite-code">{code || '—'}</Text>
          <View style={styles.codeBtns}>
            <TouchableOpacity onPress={onCopy} style={styles.codeBtn} activeOpacity={0.85} testID="invite-copy">
              <Copy size={14} color={COLORS.primary} />
              <Text style={styles.codeBtnText}>{copied ? 'Copied!' : 'Copy code'}</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={onShare} style={[styles.codeBtn, styles.codeBtnPrimary]} activeOpacity={0.85} testID="invite-share">
              <Share2 size={14} color="#fff" />
              <Text style={[styles.codeBtnText, { color: '#fff' }]}>Share</Text>
            </TouchableOpacity>
          </View>
          {enabled && (referrerCredit > 0 || refereeCredit > 0) ? (
            <View style={styles.bonusCard}>
              <Wallet size={14} color={COLORS.success} />
              <Text style={styles.bonusText}>
                {referrerCredit > 0 ? `You earn $${referrerCredit.toFixed(2)} per friend who joins.` : ''}
                {referrerCredit > 0 && refereeCredit > 0 ? '\n' : ''}
                {refereeCredit > 0 ? `Your friend gets $${refereeCredit.toFixed(2)} welcome credit.` : ''}
              </Text>
            </View>
          ) : null}
        </View>

        <View style={styles.statsRow}>
          <View style={styles.statBox}>
            <Text style={styles.statValue}>{summary?.referees_count ?? 0}</Text>
            <Text style={styles.statLabel}>Friends invited</Text>
          </View>
          <View style={styles.statBox}>
            <Text style={[styles.statValue, { color: COLORS.success }]}>{summary?.verified_referees_count ?? 0}</Text>
            <Text style={styles.statLabel}>Verified</Text>
          </View>
          <View style={styles.statBox}>
            <Text style={[styles.statValue, { color: COLORS.warning }]}>{summary?.pending_credits ?? 0}</Text>
            <Text style={styles.statLabel}>Pending credits</Text>
          </View>
        </View>

        {summary?.referred_by ? (
          <View style={styles.invitedBy}>
            <UserPlus size={14} color={COLORS.primary} />
            <Text style={styles.invitedByText}>You were invited by <Text style={{ fontWeight: FONT.weights.bold }}>{summary.referred_by.name}</Text></Text>
          </View>
        ) : null}

        <Text style={styles.sectionTitle}>Friends you invited ({summary?.referees?.length || 0})</Text>
        {(summary?.referees || []).length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTxt}>No referrals yet.</Text>
            <Text style={styles.emptySub}>Share your code and watch this list grow.</Text>
          </View>
        ) : (
          summary!.referees.map((r) => (
            <View key={r.id} style={styles.refRow} testID={`invite-referee-${r.id}`}>
              <View style={[styles.avatar, !r.verified && { backgroundColor: COLORS.disabledBg }]}>
                <Text style={[styles.avatarTxt, !r.verified && { color: COLORS.disabledText }]}>
                  {(r.name || '?').slice(0, 1).toUpperCase()}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                  <Text style={styles.refName}>{r.name || '—'}</Text>
                  {r.verified ? <ShieldCheck size={12} color={COLORS.success} /> : null}
                </View>
                <Text style={styles.refMeta}>{r.phone || 'pending'} • joined {new Date(r.created_at).toLocaleDateString()}</Text>
              </View>
              {!r.verified ? <Text style={styles.pendingTag}>Pending</Text> : null}
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  backBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: SPACING.md },
  backText: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  heroCard: { padding: SPACING.lg, backgroundColor: COLORS.primary, borderRadius: RADIUS.lg, alignItems: 'center', marginBottom: SPACING.md },
  heroIcon: { width: 56, height: 56, borderRadius: 28, backgroundColor: 'rgba(255,255,255,0.18)', alignItems: 'center', justifyContent: 'center', marginBottom: SPACING.sm },
  heroTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: '#fff', textAlign: 'center' },
  heroSub: { fontSize: FONT.sizes.sm, color: 'rgba(255,255,255,0.85)', marginTop: 4, textAlign: 'center' },
  codeCard: { padding: SPACING.lg, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, alignItems: 'center', marginBottom: SPACING.md },
  codeLabel: { fontSize: 11, color: COLORS.subtext, fontWeight: FONT.weights.bold, letterSpacing: 1 },
  codeValue: { fontSize: 36, fontWeight: FONT.weights.heavy, color: COLORS.primary, letterSpacing: 6, marginVertical: SPACING.sm },
  codeBtns: { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.sm, width: '100%' },
  codeBtn: { flex: 1, height: 44, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.primary, backgroundColor: COLORS.surface, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 6 },
  codeBtnPrimary: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  codeBtnText: { color: COLORS.primary, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold },
  bonusCard: { flexDirection: 'row', alignItems: 'flex-start', gap: 6, padding: SPACING.sm, marginTop: SPACING.md, backgroundColor: COLORS.successLight, borderRadius: RADIUS.sm, width: '100%' },
  bonusText: { flex: 1, fontSize: FONT.sizes.xs, color: COLORS.success, fontWeight: FONT.weights.semibold, lineHeight: 18 },
  statsRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.md },
  statBox: { flex: 1, padding: SPACING.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, alignItems: 'center' },
  statValue: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  statLabel: { fontSize: 11, color: COLORS.subtext, marginTop: 2, textAlign: 'center' },
  invitedBy: { flexDirection: 'row', alignItems: 'center', gap: 6, padding: SPACING.sm, backgroundColor: COLORS.primaryLight, borderRadius: RADIUS.sm, marginBottom: SPACING.md },
  invitedByText: { color: COLORS.primary, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
  sectionTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text, marginBottom: SPACING.sm },
  empty: { padding: SPACING.lg, alignItems: 'center' },
  emptyTxt: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontWeight: FONT.weights.semibold },
  emptySub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4, textAlign: 'center' },
  refRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginBottom: 8 },
  avatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: COLORS.primaryLight, alignItems: 'center', justifyContent: 'center' },
  avatarTxt: { color: COLORS.primary, fontWeight: FONT.weights.bold },
  refName: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  refMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  pendingTag: { fontSize: 10, color: COLORS.warning, backgroundColor: COLORS.warningLight, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, fontWeight: FONT.weights.bold, textTransform: 'uppercase' },
});
