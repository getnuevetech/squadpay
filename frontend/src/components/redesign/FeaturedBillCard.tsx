/**
 * FeaturedBillCard — the violet-gradient panel from Image 2 (adapted, lighter
 * than full-dark navy). Renders title, big amount, stacked avatars + dashed +,
 * progress bar, and dual CTAs (Pay Now / Share). Used at the top of the home
 * screen for the most-recent active bill.
 */
import { View, Text, StyleSheet, TouchableOpacity, Pressable } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Plus, Link2, CreditCard, PlusSquare } from 'lucide-react-native';
import { COLORS, FONT, RADIUS } from '../../theme';
import { AvatarRing } from '../AvatarRing';

type Member = { user_id: string; name: string };

type Props = {
  title: string;
  total: number;
  paidAmount?: number;
  remainingAmount?: number;
  paidCount?: number;
  totalCount?: number;
  leadId?: string;
  members?: Member[];
  onPay?: () => void;
  onShare?: () => void;
  onPress?: () => void;
  onAddMember?: () => void;
  onSplit?: () => void;          // new — "Split a Bill" sub-link / fallback CTA
  onJoin?: () => void;           // new — "Join a Bill" sub-link / fallback CTA
  testID?: string;
};

export function FeaturedBillCard({
  title,
  total,
  paidAmount = 0,
  remainingAmount,
  paidCount = 0,
  totalCount = 0,
  leadId,
  members = [],
  onPay,
  onShare,
  onPress,
  onAddMember,
  onSplit,
  onJoin,
  testID,
}: Props) {
  const remaining = remainingAmount !== undefined ? remainingAmount : Math.max(0, total - paidAmount);
  const pct = total > 0 ? Math.min(1, paidAmount / total) : 0;
  const dollars = Math.floor(total);
  const cents = Math.round((total - dollars) * 100).toString().padStart(2, '0');
  // "pay" mode = bill still has unpaid balance. "idle" mode = bill fully paid.
  const isPayMode = remaining > 0.005;

  return (
    <Pressable onPress={onPress} testID={testID} style={({ pressed }) => [{ opacity: pressed ? 0.96 : 1 }]}>
      <LinearGradient
        colors={['#3F1F8C', '#5B2BC8', '#7C3AED']}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.card}
      >
        {/* Top accent line (subtle highlight, like the image) */}
        <View style={styles.accentLine} />

        {/* Title + big amount row */}
        <View style={styles.headerRow}>
          <Text style={styles.title} numberOfLines={1}>{title.toUpperCase()}</Text>
          <Text style={styles.amount}>
            <Text style={styles.dollarSign}>$</Text>
            {dollars}
            <Text style={styles.cents}>.{cents}</Text>
          </Text>
        </View>

        {/* Avatars + dashed + */}
        <View style={styles.avatarsRow}>
          <View style={styles.avatarsStack}>
            {members.slice(0, 4).map((m, i) => (
              <View
                key={m.user_id}
                style={[
                  styles.avatarItem,
                  { marginLeft: i === 0 ? 0 : -10, zIndex: 10 - i },
                ]}
              >
                <AvatarRing
                  name={m.name || '?'}
                  seed={m.user_id}
                  size={36}
                  showLeadCrown={leadId ? m.user_id === leadId : false}
                />
              </View>
            ))}
          </View>
          <TouchableOpacity
            onPress={onAddMember}
            style={styles.addBtn}
            activeOpacity={0.7}
            testID={`${testID}-add-member`}
            accessibilityLabel="Add member"
          >
            <Plus size={18} color="#fff" />
          </TouchableOpacity>
        </View>

        {/* Status meta */}
        <View style={styles.metaRow}>
          <Text style={styles.metaPrimary}>
            {paidCount} of {totalCount} paid
          </Text>
          <Text style={styles.metaSecondary}>
            ${paidAmount.toFixed(0)} paid · ${remaining.toFixed(0)} remaining
          </Text>
        </View>

        {/* Progress bar */}
        <View style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${Math.round(pct * 100)}%` }]} />
        </View>

        {/* CTAs — switch labels based on whether bill still has remaining balance.
            PAY mode: primary=Pay Now, secondary=Share + small "Split a Bill" / "Join a Bill" sub-links.
            IDLE mode: primary=Split a Bill, secondary=Join a Bill (no sub-links). */}
        <View style={styles.ctaRow}>
          <View style={{ flex: 1.4 }}>
            <TouchableOpacity
              onPress={isPayMode ? onPay : onSplit}
              style={styles.payBtn}
              activeOpacity={0.85}
              testID={`${testID}-${isPayMode ? 'pay' : 'split'}-btn`}
            >
              {isPayMode ? <CreditCard size={16} color="#fff" /> : <Plus size={16} color="#fff" />}
              <Text style={styles.payText}>{isPayMode ? 'Pay Now' : 'Split a Bill'}</Text>
            </TouchableOpacity>
            {isPayMode ? (
              <TouchableOpacity
                onPress={onSplit}
                activeOpacity={0.7}
                style={styles.subLinkWrap}
                testID={`${testID}-split-sublink`}
              >
                <Text style={styles.subLinkText}>Split a Bill</Text>
              </TouchableOpacity>
            ) : null}
          </View>
          <View style={{ flex: 1 }}>
            <TouchableOpacity
              onPress={isPayMode ? onShare : onJoin}
              style={styles.shareBtn}
              activeOpacity={0.85}
              testID={`${testID}-${isPayMode ? 'share' : 'join'}-btn`}
            >
              {isPayMode ? <Link2 size={16} color="#fff" /> : <PlusSquare size={16} color="#fff" />}
              <Text style={styles.shareText}>{isPayMode ? 'Share' : 'Join a Bill'}</Text>
            </TouchableOpacity>
            {isPayMode ? (
              <TouchableOpacity
                onPress={onJoin}
                activeOpacity={0.7}
                style={styles.subLinkWrap}
                testID={`${testID}-join-sublink`}
              >
                <Text style={styles.subLinkText}>Join a Bill</Text>
              </TouchableOpacity>
            ) : null}
          </View>
        </View>
      </LinearGradient>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 24,
    padding: 18,
    paddingTop: 22,
    overflow: 'hidden',
    shadowColor: '#3F1F8C',
    shadowOpacity: 0.32,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 16 },
    elevation: 10,
  },
  accentLine: {
    position: 'absolute',
    top: 0,
    left: 24,
    right: 24,
    height: 3,
    borderRadius: 999,
    backgroundColor: 'rgba(255,255,255,0.45)',
  },
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14 },
  title: {
    color: '#D7C7FB',
    fontWeight: FONT.weights.bold,
    fontSize: 12,
    letterSpacing: 1.2,
    flex: 1,
    marginTop: 8,
    marginRight: 8,
  },
  amount: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 36, lineHeight: 40, letterSpacing: -1 },
  dollarSign: { fontSize: 24, fontWeight: FONT.weights.bold },
  cents: { fontSize: 18, fontWeight: FONT.weights.bold, color: '#E2D6FB' },
  avatarsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  avatarsStack: { flexDirection: 'row', alignItems: 'center' },
  avatarItem: { borderWidth: 2, borderColor: '#fff', borderRadius: 999 },
  addBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 2,
    borderStyle: 'dashed',
    borderColor: 'rgba(255,255,255,0.55)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  metaRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 14 },
  metaPrimary: { color: '#fff', fontWeight: FONT.weights.semibold, fontSize: 13 },
  metaSecondary: { color: '#D7C7FB', fontSize: 12 },
  progressTrack: {
    height: 6,
    borderRadius: 999,
    backgroundColor: 'rgba(255,255,255,0.18)',
    marginTop: 10,
    overflow: 'hidden',
  },
  progressFill: { height: '100%', backgroundColor: '#fff', borderRadius: 999 },
  ctaRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, marginTop: 18 },
  payBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 18,
    borderRadius: RADIUS.pill,
    backgroundColor: '#7C3AED',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.45)',
    shadowColor: '#7C3AED',
    shadowOpacity: 0.5,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 },
    elevation: 8,
  },
  payText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 17 },
  shareBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 18,
    borderRadius: RADIUS.pill,
    backgroundColor: 'transparent',
    borderWidth: 1.5,
    borderColor: 'rgba(255,255,255,0.55)',
  },
  shareText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 17 },
  // Small sub-links rendered under each main CTA when bill is in PAY mode.
  subLinkWrap: { alignItems: 'center', marginTop: 8 },
  subLinkText: {
    color: '#E2D6FB',
    fontSize: 12,
    fontWeight: FONT.weights.semibold,
    textDecorationLine: 'underline',
  },
});

export default FeaturedBillCard;
