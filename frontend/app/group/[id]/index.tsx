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
import { CheckCircle2, Copy, Share2, UserCircle2, Crown, ArrowRight, Users, CreditCard } from 'lucide-react-native';
import { Button } from '../../../src/Button';
import { api, BACKEND_URL, Group } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';

export default function GroupLobbyScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

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
          <Text style={styles.title} testID="lobby-title">{group.title}</Text>
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

        {/* Virtual card (lead-only) */}
        {isLead && group.virtual_card && (
          <View style={styles.cardWrap} testID="lobby-virtual-card">
            <Text style={styles.cardLabel}>Virtual card · {group.funding?.total_contributed >= group.total ? 'fully funded' : 'funding…'}</Text>
            <View style={styles.cardFace}>
              <View style={styles.cardChip} />
              <View style={styles.cardRow}>
                <CreditCard size={20} color="rgba(255,255,255,0.9)" />
                <Text style={styles.cardBrand}>GroupPay</Text>
              </View>
              <Text style={styles.cardNumber}>•••• •••• •••• {group.virtual_card.last4}</Text>
              <View style={styles.cardFooter}>
                <View>
                  <Text style={styles.cardTinyLabel}>Balance</Text>
                  <Text style={styles.cardValue}>${group.virtual_card.balance.toFixed(2)}</Text>
                </View>
                <View>
                  <Text style={styles.cardTinyLabel}>Exp</Text>
                  <Text style={styles.cardValue}>
                    {String(group.virtual_card.exp_month).padStart(2, '0')}/{String(group.virtual_card.exp_year).slice(-2)}
                  </Text>
                </View>
                <View>
                  <Text style={styles.cardTinyLabel}>CVV</Text>
                  <Text style={styles.cardValue}>{group.virtual_card.cvv}</Text>
                </View>
              </View>
            </View>
            <Text style={styles.cardHint}>
              Funded by group contributions. Use it to pay the merchant.
            </Text>
          </View>
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
