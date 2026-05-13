import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Platform,
  RefreshControl,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import QRCode from 'react-native-qrcode-svg';
import * as Clipboard from 'expo-clipboard';
import { CheckCircle2, Copy, Share2, Crown, Users, CreditCard, Pencil, Eye, Receipt, Smartphone, ArrowLeft } from 'lucide-react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Button } from '../../../src/Button';
import { api, BACKEND_URL, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING, SHADOW } from '../../../src/theme';
import { StatusBadge } from '../../../src/StatusBadge';
import { EditMetaModal } from '../../../src/EditMetaModal';
import { RevealCardModal } from '../../../src/RevealCardModal';
import { toast } from '../../../src/components/Toast';
import { Skeleton, SkeletonGroupRow } from '../../../src/components/Skeleton';
import { PressableScale } from '../../../src/components/PressableScale';
import { AvatarRing } from '../../../src/components/AvatarRing';

export default function GroupLobbyScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [editTitleVisible, setEditTitleVisible] = useState(false);
  const [revealOpen, setRevealOpen] = useState(false);

  const load = useCallback(async () => {
    const u = await loadUser();
    if (!u) {
      router.replace('/auth');
      return;
    }
    setUserId(u.id);
    try {
      const g = await api.getGroup(id);
      setGroup(g);
    } catch (e: any) {
      toast.error(e?.message || 'Could not load bill');
    }
  }, [id, router]);

  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  if (!group || !userId) {
    return (
      <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
        <ScrollView contentContainerStyle={{ padding: SPACING.md, paddingBottom: 120 }} testID="lobby-loading">
          {/* Header skeleton */}
          <View style={{ marginBottom: SPACING.md, padding: SPACING.lg, borderRadius: RADIUS.xl, backgroundColor: COLORS.slate900 }}>
            <Skeleton width={140} height={16} style={{ backgroundColor: 'rgba(255,255,255,0.18)' }} />
            <View style={{ height: 14 }} />
            <Skeleton width={180} height={42} style={{ backgroundColor: 'rgba(255,255,255,0.22)' }} />
            <View style={{ height: 8 }} />
            <Skeleton width={90} height={12} style={{ backgroundColor: 'rgba(255,255,255,0.15)' }} />
          </View>
          {/* QR skeleton */}
          <View style={[styles.qrCard, SHADOW.sm]}>
            <Skeleton width={80} height={10} />
            <View style={{ height: SPACING.md }} />
            <Skeleton width={200} height={200} radius={RADIUS.md} />
            <View style={{ height: SPACING.md }} />
            <Skeleton width={120} height={18} />
          </View>
          {/* Members skeleton */}
          <SkeletonGroupRow testID="lobby-skel-row" />
          <SkeletonGroupRow />
        </ScrollView>
      </SafeAreaView>
    );
  }

  const isLead = group.lead_id === userId;
  // Share link must point at the WEB FRONTEND (not the backend API host).
  // Priority: EXPO_PUBLIC_WEB_BASE_URL env var → browser origin (web) → backend
  // host (legacy fallback for dev so old test links still resolve).
  const webBase = (() => {
    const fromEnv = process.env.EXPO_PUBLIC_WEB_BASE_URL;
    if (fromEnv && fromEnv.trim()) return fromEnv.replace(/\/$/, '');
    if (typeof window !== 'undefined' && window?.location?.origin) {
      return window.location.origin.replace(/\/$/, '');
    }
    return (BACKEND_URL || '').replace(/\/$/, '');
  })();
  const joinUrl = `${webBase}/join/${group.code}`;

  const copy = async () => {
    await Clipboard.setStringAsync(joinUrl);
    toast.success('Link copied to clipboard');
  };

  const share = async () => {
    try {
      await Share.share({
        message: `Join my bill "${group.title}" on SquadPay: ${joinUrl}`,
      });
    } catch {}
  };

  const continueToItems = () => {
    if (group.split_mode === 'fast') {
      router.push(`/group/${group.id}/summary`);
    } else {
      router.push(`/group/${group.id}/items`);
    }
  };

  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: 120 }}
      >
        <LinearGradient
          colors={[COLORS.gradientStart, COLORS.gradientEnd]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={[styles.headerCard, SHADOW.lg]}
        >
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4, gap: 8 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flex: 1 }}>
              <Text style={styles.title} testID="lobby-title">{group.title}</Text>
              {userId === group.lead_id && group.status !== 'closed' && (group.contributions?.length || 0) === 0 && (
                <TouchableOpacity
                  testID="lobby-edit-title"
                  onPress={() => setEditTitleVisible(true)}
                  hitSlop={10}
                >
                  <Pencil size={16} color="rgba(255,255,255,0.85)" />
                </TouchableOpacity>
              )}
            </View>
            <StatusBadge status={group.derived_status} testID="lobby-status-badge" />
          </View>
          <Text style={styles.totalLabel}>Bill total</Text>
          <Text style={styles.total}>${group.total.toFixed(2)}</Text>
          <View style={styles.headerFooter}>
            <View style={styles.headerChip}>
              <Text style={styles.headerChipText}>
                {group.split_mode === 'fast'
                  ? 'Equal split'
                  : group.split_mode === 'smart'
                  ? 'Smart split'
                  : 'Itemized split'}
              </Text>
            </View>
            <Text style={styles.headerCount}>
              {group.members.length} Squad {group.members.length === 1 ? 'member' : 'members'}
            </Text>
          </View>
          {/* Item 8 (June 2025) — Surface the squad's creation date directly
              on the lobby header so members can spot stale squads or recall
              the night out without digging into the activity feed. Uses
              en-US locale-light formatting (e.g. "Jun 14, 2025 · 7:42 PM"). */}
          {group.created_at ? (
            <Text style={styles.headerTimestamp} testID="lobby-created-at">
              Created {new Date(group.created_at).toLocaleString(undefined, {
                month: 'short', day: 'numeric', year: 'numeric',
                hour: 'numeric', minute: '2-digit',
              })}
            </Text>
          ) : null}
        </LinearGradient>

        <View style={[styles.qrCard, SHADOW.sm]}>
          <Text style={styles.qrLabel}>Scan to join</Text>
          <View style={styles.qrBox}>
            <QRCode value={joinUrl} size={240} backgroundColor="white" color={COLORS.text} />
          </View>
          <Text style={styles.codeText} testID="lobby-code">Code: {group.code}</Text>
          <View style={styles.shareRow}>
            <PressableScale testID="lobby-copy-btn" onPress={copy} style={styles.shareBtn}>
              <View style={styles.shareBtnInner}>
                <Copy size={16} color={COLORS.primary} />
                <Text style={styles.shareBtnText} numberOfLines={1}>Copy link</Text>
              </View>
            </PressableScale>
            <PressableScale testID="lobby-share-btn" onPress={share} style={styles.shareBtn}>
              <View style={styles.shareBtnInner}>
                <Share2 size={16} color={COLORS.primary} />
                <Text style={styles.shareBtnText} numberOfLines={1}>Share</Text>
              </View>
            </PressableScale>
          </View>
        </View>

        {/* Phase H7 — Overpayment refund banner (visible only to the
             overpaid user; e.g. lead paid full bill, then group expanded) */}
        {(() => {
          const me = group.per_user.find((p) => p.user_id === userId);
          const overpaid = me?.overpaid || 0;
          if (overpaid <= 0.01) return null;
          return (
            <PressableScale
              onPress={async () => {
                try {
                  const r = await api.refundOverpayment(group.id, userId!);
                  setGroup(r.group);
                  if (r.refunded > 0.01) {
                    const breakdown = r.breakdown || [];
                    const stripeCount = breakdown.filter((b) => b.via === 'stripe').length;
                    const creditCount = breakdown.filter((b) => b.via === 'wallet_credit').length;
                    let msg = `Refunded $${r.refunded.toFixed(2)}`;
                    if (stripeCount && !creditCount) msg += ' to your card (5–10 days)';
                    else if (creditCount && !stripeCount) msg += ' to your wallet';
                    else if (stripeCount && creditCount) msg += ' (mixed: card + wallet)';
                    toast.success(msg);
                  } else {
                    toast.error(r.info || 'Refund failed');
                  }
                } catch (e: any) {
                  toast.error(e?.message || 'Could not request refund');
                }
              }}
              testID="lobby-refund-overpayment"
              style={[styles.refundBanner, SHADOW.sm]}
            >
              <View style={styles.refundIcon}>
                <Receipt size={20} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.refundTitle}>Refund overpayment</Text>
                <Text style={styles.refundSub}>
                  You paid ${(me!.contributed + me!.repaid).toFixed(2)} but your share is only ${me!.total.toFixed(2)}.
                  Tap to refund ${overpaid.toFixed(2)} back to your card.
                </Text>
              </View>
            </PressableScale>
          );
        })()}

        {/* Virtual card (lead-only) — Real Stripe Issuing card (Phase F1) */}
        {isLead && group.virtual_card && group.virtual_card.stripe_card_id && (
          <View style={styles.cardWrap} testID="lobby-virtual-card">
            <Text style={styles.cardLabel}>
              Squad card · {group.virtual_card.status === 'inactive' ? 'disabled' :
                (group.funding?.total_contributed >= group.total ? 'active' : 'funding…')}
            </Text>
            <View style={[styles.cardFace, SHADOW.lg, group.virtual_card.status === 'inactive' && { opacity: 0.55 }]}>
              <View style={styles.cardChip} />
              <View style={styles.cardRow}>
                <CreditCard size={20} color="rgba(255,255,255,0.9)" />
                <View>
                  <Text style={styles.cardBrand}>{group.virtual_card.nickname || 'SquadPay'}</Text>
                  <Text style={styles.cardGroupName} numberOfLines={1}>{group.title}</Text>
                </View>
              </View>
              <Text style={styles.cardNumber}>•••• •••• •••• {group.virtual_card.last4}</Text>
              <View style={styles.cardFooter}>
                <View>
                  <Text style={styles.cardTinyLabel}>Spent</Text>
                  <Text style={styles.cardValue}>${(group.virtual_card.spent || 0).toFixed(2)}</Text>
                </View>
                <View>
                  <Text style={styles.cardTinyLabel}>Cap</Text>
                  <Text style={styles.cardValue}>${(group.virtual_card.spend_cap || 0).toFixed(2)}</Text>
                </View>
                <View>
                  <Text style={styles.cardTinyLabel}>Exp</Text>
                  <Text style={styles.cardValue}>
                    {String(group.virtual_card.exp_month).padStart(2, '0')}/{String(group.virtual_card.exp_year).slice(-2)}
                  </Text>
                </View>
              </View>
            </View>
            <Text style={styles.cardHint}>
              {group.virtual_card.status === 'inactive'
                ? 'Card disabled. Transactions visible in admin history.'
                : 'Real Stripe-issued virtual card · use "Reveal" to view PAN/CVV.'}
            </Text>
            {group.virtual_card.status === 'active' && (
              <View style={styles.cardActions}>
                <TouchableOpacity
                  onPress={() => setRevealOpen(true)}
                  style={styles.cardActionBtnPrimary}
                  activeOpacity={0.85}
                  testID="lobby-reveal-card"
                >
                  <Eye size={14} color="#fff" />
                  <Text style={styles.cardActionTextPrimary}>Reveal details</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={async () => {
                    const isIOS = Platform.OS === 'ios';
                    const provider = isIOS ? 'apple' : 'google';
                    try {
                      const res = await fetch(
                        `${BACKEND_URL}/api/groups/${group.id}/card/push-provisioning/${provider}`,
                        {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            user_id: userId,
                            // SDK-specific fields would be filled by the native side:
                            // iOS: nonce + certificates from PKAddPaymentPassViewController
                            // Android: wallet_account_id + stable_hardware_id from TapAndPayClient
                            stripe_version: '2024-06-20',
                          }),
                        },
                      );
                      const data = await res.json();
                      if (res.status === 409 && !data.available) {
                        Alert.alert(
                          'Add to Wallet — not yet enabled',
                          `${data.reason}\n\nIn the meantime, use "Reveal details" to copy the card manually.`,
                        );
                        return;
                      }
                      if (res.status === 400 && (data.detail || '').toLowerCase().includes('required')) {
                        Alert.alert(
                          'Add to Wallet — SDK call needed',
                          `${data.detail}\n\nThe backend is wire-ready. Once Apple/Google SDK enrollment is approved, the native side will provide the missing fields automatically.`,
                        );
                        return;
                      }
                      if (!res.ok) {
                        Alert.alert(`${isIOS ? 'Apple Pay' : 'Google Pay'} error`, data.reason || data.detail || 'Request failed');
                        return;
                      }
                      Alert.alert(
                        `Add to ${isIOS ? 'Apple' : 'Google'} Wallet`,
                        `Ephemeral key minted (id ${data.card_id?.slice(-8)}). Native SDK can now hand off to ${isIOS ? 'PassKit' : 'TapAndPayClient'}.`,
                      );
                    } catch (e: any) {
                      Alert.alert('Network error', e?.message || 'Failed to start push provisioning');
                    }
                  }}
                  style={styles.cardActionBtnSecondary}
                  activeOpacity={0.85}
                  testID="lobby-add-wallet"
                >
                  <Smartphone size={14} color={COLORS.text} />
                  <Text style={styles.cardActionTextSecondary}>
                    Add to {Platform.OS === 'ios' ? 'Apple Wallet' : 'Google Pay'}
                  </Text>
                </TouchableOpacity>
              </View>
            )}
            {/* Spend feed */}
            {Array.isArray((group.virtual_card as any).transactions) && (group.virtual_card as any).transactions.length > 0 && (
              <View style={styles.txnList}>
                <Text style={styles.txnHeader}>
                  <Receipt size={12} color={COLORS.subtext} /> Recent spend
                </Text>
                {(group.virtual_card as any).transactions.slice().reverse().slice(0, 5).map((t: any, idx: number) => (
                  <View key={t.id || idx} style={styles.txnRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.txnMerchant} numberOfLines={1}>{t.merchant_name || 'Merchant'}</Text>
                      <Text style={styles.txnMeta}>{t.merchant_category || ''} · {new Date(t.created_at).toLocaleDateString()}</Text>
                    </View>
                    <Text style={[styles.txnAmount, t.type === 'refund' && { color: COLORS.success }]}>
                      {t.type === 'refund' ? '+' : '-'}${(t.amount || 0).toFixed(2)}
                    </Text>
                  </View>
                ))}
              </View>
            )}
          </View>
        )}
        {isLead && group.virtual_card && group.virtual_card.stripe_card_id && userId && (
          <RevealCardModal
            visible={revealOpen}
            onClose={() => setRevealOpen(false)}
            groupId={group.id}
            userId={userId}
            cardLast4={group.virtual_card.last4}
            cardNickname={group.virtual_card.nickname}
          />
        )}

        <View style={[styles.membersCard, SHADOW.sm]}>
          <View style={styles.membersHeader}>
            <Users size={18} color={COLORS.text} />
            <Text style={styles.membersTitle}>
              {group.members.length} Squad {group.members.length === 1 ? 'member' : 'members'}
            </Text>
          </View>
          {group.members.map((m) => (
            <View key={m.user_id} style={styles.memberRow} testID={`lobby-member-${m.user_id}`}>
              <AvatarRing name={m.name || '?'} seed={m.user_id} size={44} showLeadCrown={m.role === 'lead'} />
              <View style={{ flex: 1 }}>
                <Text style={styles.memberName}>
                  {m.name} {m.user_id === userId ? '(You)' : ''}
                </Text>
                <Text style={styles.memberSub}>
                  {m.verified ? 'Verified' : 'Not verified'}
                </Text>
              </View>
              {m.role === 'lead' ? (
                <Crown size={16} color={COLORS.warning} />
              ) : (
                <CheckCircle2 size={16} color={COLORS.success} />
              )}
            </View>
          ))}
        </View>
      </ScrollView>

      <View style={[styles.bottomBar, SHADOW.lg]}>
        {isLead ? (
          <Button
            title="Lead Dashboard"
            testID="lobby-continue-btn"
            onPress={() => router.replace(`/group/${group.id}/dashboard`)}
          />
        ) : (
          <Button
            title="Squad Dashboard"
            testID="lobby-continue-btn"
            onPress={() => router.replace(`/group/${group.id}/summary`)}
          />
        )}
      </View>
      {userId && (
        <EditMetaModal
          visible={editTitleVisible}
          onClose={() => setEditTitleVisible(false)}
          onSaved={(g) => setGroup(g)}
          group={group}
          userId={userId}
          field="title"
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  headerCard: {
    borderRadius: RADIUS.xl,
    padding: SPACING.lg,
    marginBottom: SPACING.md,
    overflow: 'hidden',
  },
  title: { color: '#fff', fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold },
  totalLabel: {
    color: 'rgba(255,255,255,0.75)',
    fontSize: FONT.sizes.xs,
    textTransform: 'uppercase',
    letterSpacing: 1.4,
    fontWeight: FONT.weights.semibold,
    marginTop: SPACING.sm,
  },
  total: { color: '#fff', fontSize: 48, fontWeight: FONT.weights.heavy, letterSpacing: -1, marginTop: 2 },
  modeLabel: {
    color: COLORS.slate400,
    fontSize: FONT.sizes.sm,
    marginTop: 4,
    fontWeight: FONT.weights.medium,
  },
  headerFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: SPACING.md,
  },
  headerChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: RADIUS.pill,
    backgroundColor: 'rgba(255,255,255,0.18)',
  },
  headerChipText: {
    color: '#fff',
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.bold,
    letterSpacing: 0.3,
  },
  headerCount: {
    color: 'rgba(255,255,255,0.85)',
    fontSize: FONT.sizes.sm,
    fontWeight: FONT.weights.medium,
  },
  headerTimestamp: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.medium,
    marginTop: SPACING.xs,
  },
  qrCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    alignItems: 'center',
    marginBottom: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  qrLabel: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: SPACING.md,
    fontWeight: FONT.weights.semibold,
  },
  qrBox: {
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    backgroundColor: '#fff',
  },
  codeText: {
    marginTop: SPACING.md,
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    letterSpacing: 2,
  },
  shareRow: { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.md },
  shareBtn: {
    paddingHorizontal: SPACING.md,
    paddingVertical: 10,
    borderRadius: RADIUS.pill,
    backgroundColor: COLORS.primaryLight,
  },
  shareBtnInner: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  shareBtnText: { color: COLORS.primary, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  cardWrap: { marginBottom: SPACING.md },
  cardLabel: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: FONT.weights.semibold,
    marginBottom: 8,
  },
  cardFace: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    overflow: 'hidden',
    minHeight: 180,
    justifyContent: 'space-between',
  },
  cardChip: {
    position: 'absolute',
    right: -40,
    top: -40,
    width: 160,
    height: 160,
    borderRadius: 80,
    backgroundColor: 'rgba(255,255,255,0.07)',
  },
  cardRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cardBrand: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md, letterSpacing: 0.5 },
  cardGroupName: { color: 'rgba(255,255,255,0.85)', fontSize: FONT.sizes.xs, fontWeight: FONT.weights.medium, marginTop: 1, maxWidth: 220 },
  cardNumber: {
    color: '#fff',
    fontSize: FONT.sizes.lg,
    letterSpacing: 3,
    fontWeight: FONT.weights.medium,
    marginTop: SPACING.md,
  },
  cardFooter: { flexDirection: 'row', justifyContent: 'space-between', marginTop: SPACING.md },
  cardTinyLabel: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 2,
  },
  cardValue: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  cardHint: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 8, lineHeight: 16 },
  cardActions: { flexDirection: 'row', gap: 8, marginTop: 12 },
  cardActionBtnPrimary: {
    flex: 1, backgroundColor: COLORS.primary, borderRadius: 10, paddingVertical: 10,
    alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 6,
  },
  cardActionTextPrimary: { color: '#fff', fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold },
  cardActionBtnSecondary: {
    flex: 1, backgroundColor: COLORS.bg, borderRadius: 10, paddingVertical: 10,
    alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 6,
    borderWidth: 1, borderColor: COLORS.border,
  },
  cardActionTextSecondary: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  txnList: { marginTop: 14, gap: 8 },
  txnHeader: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase' as any, letterSpacing: 0.5 },
  txnRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: 8, borderTopWidth: 1, borderTopColor: COLORS.border,
  },
  txnMerchant: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold },
  txnMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  txnAmount: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.bold, fontVariant: ['tabular-nums'] as any },
  membersCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  // Phase H7 — Overpayment refund CTA banner
  refundBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    padding: SPACING.md,
    backgroundColor: COLORS.success,
    borderRadius: RADIUS.lg,
    marginBottom: SPACING.md,
  },
  refundIcon: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.22)',
    alignItems: 'center', justifyContent: 'center',
  },
  refundTitle: { color: '#fff', fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, marginBottom: 2 },
  refundSub: { color: 'rgba(255,255,255,0.92)', fontSize: FONT.sizes.xs, lineHeight: 16, fontWeight: FONT.weights.medium },
  membersHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: SPACING.md },
  membersTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  memberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: SPACING.sm,
    gap: SPACING.md,
  },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: { color: COLORS.primary, fontWeight: FONT.weights.bold },
  memberName: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  memberSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  bottomBar: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
  },
});
