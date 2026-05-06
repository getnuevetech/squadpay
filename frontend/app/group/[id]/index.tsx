import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
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
import { CheckCircle2, Copy, Share2, UserCircle2, Crown, ArrowRight, Users, CreditCard, Pencil, Eye, Receipt, Smartphone } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { api, BACKEND_URL, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { StatusBadge } from '../../../src/StatusBadge';
import { EditMetaModal } from '../../../src/EditMetaModal';
import { RevealCardModal } from '../../../src/RevealCardModal';

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
      Alert.alert('Error', e.message);
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
      <SafeAreaView style={styles.center}>
        <ActivityIndicator color={COLORS.primary} />
      </SafeAreaView>
    );
  }

  const isLead = group.lead_id === userId;
  const joinUrl = `${BACKEND_URL}/join/${group.code}`;

  const copy = async () => {
    await Clipboard.setStringAsync(joinUrl);
    Alert.alert('Copied', 'Link copied to clipboard');
  };

  const share = async () => {
    try {
      await Share.share({
        message: `Join my bill "${group.title}" on GroupPay: ${joinUrl}`,
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
        <View style={styles.headerCard}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flex: 1 }}>
              <Text style={styles.title} testID="lobby-title">{group.title}</Text>
              {userId === group.lead_id && group.derived_status === 'contributing' && (
                <TouchableOpacity
                  testID="lobby-edit-title"
                  onPress={() => setEditTitleVisible(true)}
                  hitSlop={10}
                >
                  <Pencil size={16} color="rgba(255,255,255,0.7)" />
                </TouchableOpacity>
              )}
            </View>
            <StatusBadge status={group.derived_status} testID="lobby-status-badge" />
          </View>
          <Text style={styles.total}>${group.total.toFixed(2)}</Text>
          <Text style={styles.modeLabel}>
            {group.split_mode === 'fast'
              ? 'Equal split'
              : group.split_mode === 'smart'
              ? 'Smart split'
              : 'Itemized split'}
          </Text>
        </View>

        <View style={styles.qrCard}>
          <Text style={styles.qrLabel}>Scan to join</Text>
          <View style={styles.qrBox}>
            <QRCode value={joinUrl} size={200} backgroundColor="white" color={COLORS.text} />
          </View>
          <Text style={styles.codeText} testID="lobby-code">Code: {group.code}</Text>
          <View style={styles.shareRow}>
            <TouchableOpacity testID="lobby-copy-btn" onPress={copy} style={styles.shareBtn}>
              <Copy size={16} color={COLORS.primary} />
              <Text style={styles.shareBtnText}>Copy link</Text>
            </TouchableOpacity>
            <TouchableOpacity testID="lobby-share-btn" onPress={share} style={styles.shareBtn}>
              <Share2 size={16} color={COLORS.primary} />
              <Text style={styles.shareBtnText}>Share</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Virtual card (lead-only) — Real Stripe Issuing card (Phase F1) */}
        {isLead && group.virtual_card && group.virtual_card.stripe_card_id && (
          <View style={styles.cardWrap} testID="lobby-virtual-card">
            <Text style={styles.cardLabel}>
              Virtual card · {group.virtual_card.status === 'inactive' ? 'disabled' :
                (group.funding?.total_contributed >= group.total ? 'active' : 'funding…')}
            </Text>
            <View style={[styles.cardFace, group.virtual_card.status === 'inactive' && { opacity: 0.55 }]}>
              <View style={styles.cardChip} />
              <View style={styles.cardRow}>
                <CreditCard size={20} color="rgba(255,255,255,0.9)" />
                <View>
                  <Text style={styles.cardBrand}>{group.virtual_card.nickname || 'KWIKPAY'}</Text>
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
                  onPress={() => Alert.alert(
                    'Add to Wallet',
                    'Push provisioning to Apple Pay / Google Pay is enabled in production after PSP onboarding. Use "Reveal details" to copy the card manually for now.'
                  )}
                  style={styles.cardActionBtnSecondary}
                  activeOpacity={0.85}
                >
                  <Smartphone size={14} color={COLORS.text} />
                  <Text style={styles.cardActionTextSecondary}>Add to Wallet</Text>
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

        <View style={styles.membersCard}>
          <View style={styles.membersHeader}>
            <Users size={18} color={COLORS.text} />
            <Text style={styles.membersTitle}>
              {group.members.length} {group.members.length === 1 ? 'member' : 'members'}
            </Text>
          </View>
          {group.members.map((m) => (
            <View key={m.user_id} style={styles.memberRow} testID={`lobby-member-${m.user_id}`}>
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>{(m.name || '?').slice(0, 1).toUpperCase()}</Text>
              </View>
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

      <View style={styles.bottomBar}>
        {isLead ? (
          <Button
            title={group.split_mode === 'fast' ? 'Continue to Split' : 'Continue to Items'}
            testID="lobby-continue-btn"
            onPress={continueToItems}
          />
        ) : (
          <Button
            title="See your share"
            testID="lobby-continue-btn"
            onPress={continueToItems}
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
    backgroundColor: COLORS.text,
    borderRadius: RADIUS.xl,
    padding: SPACING.lg,
    marginBottom: SPACING.md,
  },
  title: { color: '#fff', fontSize: FONT.sizes.lg, fontWeight: FONT.weights.semibold },
  total: { color: '#fff', fontSize: 48, fontWeight: FONT.weights.heavy, letterSpacing: -1, marginTop: 2 },
  modeLabel: {
    color: '#9CA3AF',
    fontSize: FONT.sizes.sm,
    marginTop: 4,
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
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: SPACING.md,
    paddingVertical: 10,
    borderRadius: RADIUS.pill,
    backgroundColor: COLORS.primaryLight,
  },
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
