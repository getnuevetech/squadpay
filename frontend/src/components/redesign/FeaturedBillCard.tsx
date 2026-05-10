/**
 * FeaturedBillCard — the violet-gradient hero panel on the home screen.
 *
 * Two modes:
 *   • IDLE  — user has no active bill. Shows $0.00, no title, ONLY the
 *             signed-in user's avatar, a greyed-out + button (disabled).
 *             CTAs are "Split a Bill" (primary) + "Join a Bill" (secondary).
 *   • ACTIVE — user has an active bill. Shows user's expected contribution
 *             alongside the group total, the bill title, user + member
 *             avatars, an enabled + button that routes to the items list.
 *             CTAs are "Pay Now" (primary) + "+ Friend" (secondary, opens
 *             QR-code drawer).
 */
import { View, Text, StyleSheet, TouchableOpacity, Pressable } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Plus, CreditCard, UserPlus, PlusSquare } from 'lucide-react-native';
import { COLORS, FONT, RADIUS } from '../../theme';
import { AvatarRing } from '../AvatarRing';

type Member = { user_id: string; name: string };

type CommonProps = {
  testID?: string;
};

type IdleProps = CommonProps & {
  mode: 'idle';
  selfId: string;
  selfName: string;
  onSplit: () => void;
  onJoin: () => void;
};

type ActiveProps = CommonProps & {
  mode: 'active';
  title: string;
  userShare: number;
  groupTotal: number;
  paidAmount: number;
  paidCount: number;
  totalCount: number;
  leadId?: string;
  members: Member[];
  selfId: string;
  selfName: string;
  onPay: () => void;          // → /pay if contributed; else → /items (handled by parent)
  onAddFriend: () => void;     // → opens QR-code drawer
  onPlusToItems: () => void;   // → /group/[id]/items
  onPress?: () => void;
};

type Props = IdleProps | ActiveProps;

export function FeaturedBillCard(props: Props) {
  const dollars = (n: number) => {
    const d = Math.floor(n);
    const c = Math.round((n - d) * 100).toString().padStart(2, '0');
    return { d, c };
  };

  if (props.mode === 'idle') {
    return <IdleCard {...props} />;
  }
  return <ActiveCard {...props} />;
}

// ───────────────────────────── Idle ─────────────────────────────
function IdleCard({ selfId, selfName, onSplit, onJoin, testID }: IdleProps) {
  return (
    <LinearGradient
      colors={['#3F1F8C', '#5B2BC8', '#7C3AED']}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.card}
      testID={testID}
    >
      <View style={styles.accentLine} />

      <View style={styles.headerRow}>
        <Text style={styles.titleMuted} numberOfLines={1}>NO ACTIVE BILL</Text>
        <Text style={styles.amount}>
          <Text style={styles.dollarSign}>$</Text>0
          <Text style={styles.cents}>.00</Text>
        </Text>
      </View>

      {/* Just the signed-in user's avatar + a greyed-out plus */}
      <View style={styles.avatarsRow}>
        <View style={styles.avatarsStack}>
          <View style={styles.avatarItem}>
            <AvatarRing name={selfName || '?'} seed={selfId} size={36} />
          </View>
        </View>
        <View
          style={[styles.addBtn, styles.addBtnDisabled]}
          testID={`${testID}-add-disabled`}
          accessibilityState={{ disabled: true }}
        >
          <Plus size={18} color="rgba(255,255,255,0.35)" />
        </View>
      </View>

      <View style={styles.metaRow}>
        <Text style={styles.metaSecondary}>Start a new split or join one with code/QR.</Text>
      </View>

      {/* Idle CTAs */}
      <View style={styles.ctaRow}>
        <TouchableOpacity
          onPress={onSplit}
          style={styles.payBtn}
          activeOpacity={0.85}
          testID={`${testID}-split-btn`}
        >
          <Plus size={16} color="#fff" />
          <Text style={styles.payText}>Split a Bill</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={onJoin}
          style={styles.shareBtn}
          activeOpacity={0.85}
          testID={`${testID}-join-btn`}
        >
          <PlusSquare size={16} color="#fff" />
          <Text style={styles.shareText}>Join a Bill</Text>
        </TouchableOpacity>
      </View>
    </LinearGradient>
  );
}

// ───────────────────────────── Active ─────────────────────────────
function ActiveCard({
  title,
  userShare,
  groupTotal,
  paidAmount,
  paidCount,
  totalCount,
  leadId,
  members,
  selfId,
  selfName,
  onPay,
  onAddFriend,
  onPlusToItems,
  onPress,
  testID,
}: ActiveProps) {
  const pct = groupTotal > 0 ? Math.min(1, paidAmount / groupTotal) : 0;
  const userD = Math.floor(userShare);
  const userC = Math.round((userShare - userD) * 100).toString().padStart(2, '0');

  // Combine self + group members; ensure self appears first if not in member list.
  const seen = new Set(members.map((m) => m.user_id));
  const fullMembers: Member[] = seen.has(selfId)
    ? members
    : [{ user_id: selfId, name: selfName }, ...members];

  return (
    <Pressable
      onPress={onPress}
      testID={testID}
      style={({ pressed }) => [{ opacity: pressed ? 0.96 : 1 }]}
    >
      <LinearGradient
        colors={['#3F1F8C', '#5B2BC8', '#7C3AED']}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.card}
      >
        <View style={styles.accentLine} />

        <View style={styles.headerRow}>
          <Text style={styles.title} numberOfLines={1}>{title.toUpperCase()}</Text>
          <Text style={styles.amount}>
            <Text style={styles.dollarSign}>$</Text>
            {userD}
            <Text style={styles.cents}>.{userC}</Text>
          </Text>
        </View>
        <Text style={styles.amountMeta}>
          your share · group total ${groupTotal.toFixed(2)}
        </Text>

        {/* Avatars + enabled + (routes to items) */}
        <View style={styles.avatarsRow}>
          <View style={styles.avatarsStack}>
            {fullMembers.slice(0, 4).map((m, i) => (
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
            {fullMembers.length > 4 ? (
              <View style={[styles.avatarItem, styles.avatarMore, { marginLeft: -10, zIndex: 0 }]}>
                <Text style={styles.avatarMoreText}>+{fullMembers.length - 4}</Text>
              </View>
            ) : null}
          </View>
          <TouchableOpacity
            onPress={onPlusToItems}
            style={styles.addBtn}
            activeOpacity={0.7}
            testID={`${testID}-add-items`}
            accessibilityLabel="View bill items"
          >
            <Plus size={18} color="#fff" />
          </TouchableOpacity>
        </View>

        <View style={styles.metaRow}>
          <Text style={styles.metaPrimary}>
            {paidCount} of {totalCount} paid
          </Text>
          <Text style={styles.metaSecondary}>
            ${paidAmount.toFixed(0)} of ${groupTotal.toFixed(0)}
          </Text>
        </View>

        <View style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${Math.round(pct * 100)}%` }]} />
        </View>

        {/* Active CTAs */}
        <View style={styles.ctaRow}>
          <TouchableOpacity
            onPress={onPay}
            style={styles.payBtn}
            activeOpacity={0.85}
            testID={`${testID}-pay-btn`}
          >
            <CreditCard size={16} color="#fff" />
            <Text style={styles.payText}>Pay Now</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={onAddFriend}
            style={styles.shareBtn}
            activeOpacity={0.85}
            testID={`${testID}-friend-btn`}
          >
            <UserPlus size={16} color="#fff" />
            <Text style={styles.shareText}>+ Friend</Text>
          </TouchableOpacity>
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
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 6 },
  title: {
    color: '#D7C7FB',
    fontWeight: FONT.weights.bold,
    fontSize: 12,
    letterSpacing: 1.2,
    flex: 1,
    marginTop: 8,
    marginRight: 8,
  },
  titleMuted: {
    color: 'rgba(215,199,251,0.6)',
    fontWeight: FONT.weights.bold,
    fontSize: 11,
    letterSpacing: 1.6,
    flex: 1,
    marginTop: 8,
    marginRight: 8,
  },
  amount: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: 36, lineHeight: 40, letterSpacing: -1 },
  dollarSign: { fontSize: 24, fontWeight: FONT.weights.bold },
  cents: { fontSize: 18, fontWeight: FONT.weights.bold, color: '#E2D6FB' },
  amountMeta: {
    color: '#D7C7FB',
    fontSize: 11,
    textAlign: 'right',
    marginBottom: 6,
  },
  avatarsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  avatarsStack: { flexDirection: 'row', alignItems: 'center' },
  avatarItem: { borderWidth: 2, borderColor: '#fff', borderRadius: 999 },
  avatarMore: {
    minWidth: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: 'rgba(255,255,255,0.18)',
    paddingHorizontal: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarMoreText: { color: '#fff', fontSize: 11, fontWeight: FONT.weights.bold },
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
  addBtnDisabled: {
    borderColor: 'rgba(255,255,255,0.18)',
    backgroundColor: 'rgba(255,255,255,0.04)',
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
  ctaRow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 18 },
  payBtn: {
    flex: 1.4,
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
    flex: 1,
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
});

export default FeaturedBillCard;
