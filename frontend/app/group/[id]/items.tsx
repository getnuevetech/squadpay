import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CheckCircle2, AlertCircle, UserCircle2, Plus, Lock, Trash2, Minus, ArrowLeft, X } from 'lucide-react-native';
import { Swipeable } from 'react-native-gesture-handler';
import { Button } from '../../../src/Button';
import { api, Group, Item } from '../../../src/api';
import { loadUser } from '../../../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { toast } from '../../../src/components/Toast';
import { Skeleton, SkeletonGroupRow } from '../../../src/components/Skeleton';

export default function ItemsScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<Group | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  // Item currently being assigned via the lead's "Assign to a member" picker.
  // Null while the modal is closed. Native Alert.alert can only render two
  // buttons on web, so the legacy Alert-driven picker silently broke for
  // groups with > 2 members. The Modal below works on every platform.
  const [assignTarget, setAssignTarget] = useState<Item | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Lead-only "add item" form
  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newPrice, setNewPrice] = useState('');
  const [newQty, setNewQty] = useState('1');
  const [adding, setAdding] = useState(false);

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
      toast.error(e?.message || 'Could not load items');
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

  const claimed = (item: Item, uid: string) => {
    return group?.assignments
      .filter((a) => a.item_id === item.id && a.user_id === uid)
      .reduce((s, a) => s + a.quantity, 0) || 0;
  };

  const totalClaimed = (item: Item) =>
    group?.assignments.filter((a) => a.item_id === item.id).reduce((s, a) => s + a.quantity, 0) || 0;

  const setQty = async (item: Item, qty: number) => {
    if (!userId || !group) return;
    setSaving(item.id);
    try {
      const g = await api.assign(group.id, userId, item.id, qty);
      setGroup(g);
    } catch (e: any) {
      toast.error(e?.message || 'Cannot claim');
    } finally {
      setSaving(null);
    }
  };

  const leadAssignToMember = (item: Item) => {
    if (!group || !userId) return;
    const remaining =
      item.quantity -
      group.assignments
        .filter((a) => a.item_id === item.id)
        .reduce((s, a) => s + a.quantity, 0);
    if (remaining <= 0) {
      toast.info('Item already fully claimed');
      return;
    }
    setAssignTarget(item);
  };

  const doAssignToUser = async (uid: string) => {
    if (!group || !assignTarget) return;
    const item = assignTarget;
    setAssignTarget(null);
    try {
      const existing = group.assignments
        .filter((a) => a.user_id === uid && a.item_id === item.id)
        .reduce((s, a) => s + a.quantity, 0);
      const g = await api.assign(group.id, uid, item.id, existing + 1);
      setGroup(g);
      toast.success('Assigned');
    } catch (e: any) {
      toast.error(e?.message || 'Failed to assign');
    }
  };

  if (!group || !userId) {
    return (
      <SafeAreaView style={styles.center} testID="items-loading">
        <View style={{ width: '90%', gap: 12 }}>
          <Skeleton width={'60%'} height={22} />
          <Skeleton width={'100%'} height={80} radius={16} />
          <SkeletonGroupRow />
          <SkeletonGroupRow />
          <SkeletonGroupRow />
        </View>
      </SafeAreaView>
    );
  }

  const isLead = group.lead_id === userId;
  // Lead can add items as long as the bill is not yet closed/settled.
  // (Previously locked once any contribution was made — relaxed per UX.)
  const itemsLocked = group.status === 'closed';

  const submitNewItem = async () => {
    if (!newName.trim()) {
      toast.error('Item name required');
      return;
    }
    const priceNum = parseFloat(newPrice);
    if (!priceNum || priceNum <= 0) {
      toast.error('Enter a valid price');
      return;
    }
    setAdding(true);
    try {
      const g = await api.appendItems(group.id, userId, [
        { name: newName.trim(), price: priceNum, quantity: parseInt(newQty || '1', 10) || 1 },
      ]);
      setGroup(g);
      setNewName('');
      setNewPrice('');
      setNewQty('1');
      setShowAddForm(false);
    } catch (e: any) {
      toast.error(e?.message || 'Failed to add item');
    } finally {
      setAdding(false);
    }
  };

  const confirmDelete = (itemId: string, name: string) => {
    Alert.alert('Delete item?', `Remove "${name}" from the bill? This cannot be undone.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            const g = await api.deleteItem(group.id, itemId, userId);
            setGroup(g);
          } catch (e: any) {
            toast.error(e?.message || 'Failed to delete item');
          }
        },
      },
    ]);
  };

  const renderRightActions = (itemId: string, name: string) => (
    <TouchableOpacity
      testID={`items-delete-${itemId}`}
      onPress={() => confirmDelete(itemId, name)}
      activeOpacity={0.85}
      style={styles.swipeDelete}
    >
      <Trash2 size={20} color="#fff" />
      <Text style={styles.swipeDeleteText}>Delete</Text>
    </TouchableOpacity>
  );

  const patchQty = async (itemId: string, delta: number) => {
    try {
      const g = await api.patchItemQty(group!.id, itemId, userId!, delta);
      setGroup(g);
    } catch (e: any) {
      toast.error(e?.message || 'Cannot change quantity');
    }
  };

  const renderLeftActions = (itemId: string) => (
    <View style={styles.swipeQty}>
      <TouchableOpacity
        testID={`items-qty-dec-${itemId}`}
        onPress={() => patchQty(itemId, -1)}
        style={[styles.swipeQtyBtn, { backgroundColor: COLORS.warning }]}
      >
        <Minus size={18} color="#fff" />
        <Text style={styles.swipeDeleteText}>−1</Text>
      </TouchableOpacity>
      <TouchableOpacity
        testID={`items-qty-inc-${itemId}`}
        onPress={() => patchQty(itemId, +1)}
        style={[styles.swipeQtyBtn, { backgroundColor: COLORS.success }]}
      >
        <Plus size={18} color="#fff" />
        <Text style={styles.swipeDeleteText}>+1</Text>
      </TouchableOpacity>
    </View>
  );

  const myTotal =
    group.per_user.find((p) => p.user_id === userId)?.total || 0;

  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
        contentContainerStyle={{ padding: SPACING.md, paddingBottom: 140 }}
      >
        <View style={styles.itemsHeader}>
          <TouchableOpacity
            onPress={() => router.replace('/')}
            style={styles.itemsBackBtn}
            activeOpacity={0.7}
            testID="items-home-btn"
          >
            <ArrowLeft size={20} color={COLORS.text} />
          </TouchableOpacity>
          <Text style={[styles.title, { flex: 1, marginLeft: 8 }]}>Who ordered what?</Text>
          {isLead && group.status !== 'closed' && (
            <TouchableOpacity
              testID="items-header-add-btn"
              onPress={() => {
                const hasContribs = (group.contributions || []).length > 0;
                if (hasContribs) {
                  Alert.alert(
                    'Heads up',
                    'Items you add now CANNOT be deleted because contributions have already started. Continue?',
                    [
                      { text: 'Cancel', style: 'cancel' },
                      { text: 'Continue', onPress: () => setShowAddForm(true) },
                    ],
                  );
                } else {
                  setShowAddForm(true);
                }
              }}
              activeOpacity={0.85}
              style={styles.headerPlusBtn}
            >
              <Plus size={20} color="#fff" />
            </TouchableOpacity>
          )}
        </View>
        <Text style={styles.sub}>Tap the quantity you had.</Text>

        {isLead && itemsLocked && (
          <View style={styles.lockBanner} testID="items-lock-banner">
            <Lock size={14} color={COLORS.primary} />
            <Text style={styles.lockText}>
              Existing items are locked — contributions started. You can still add new items below.
            </Text>
          </View>
        )}

        {/* Lead-only inline add-item form (shown via the + button) */}
        {isLead && showAddForm && group.status !== 'closed' && (
          <View style={styles.addCard} testID="items-add-form">
            <Text style={styles.addTitle}>Add a new item</Text>
            <TextInput
              testID="items-new-name"
              value={newName}
              onChangeText={setNewName}
              placeholder="Item name (e.g. Salad)"
              placeholderTextColor={COLORS.disabledText}
              style={styles.addInput}
              autoFocus
            />
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <TextInput
                testID="items-new-price"
                value={newPrice}
                onChangeText={setNewPrice}
                placeholder="Price"
                placeholderTextColor={COLORS.disabledText}
                keyboardType="decimal-pad"
                style={[styles.addInput, { flex: 2 }]}
              />
              <TextInput
                testID="items-new-qty"
                value={newQty}
                onChangeText={setNewQty}
                placeholder="x1"
                placeholderTextColor={COLORS.disabledText}
                keyboardType="number-pad"
                style={[styles.addInput, { flex: 1 }]}
              />
            </View>
            <View style={{ flexDirection: 'row', gap: 8, marginTop: 4 }}>
              <TouchableOpacity
                testID="items-new-cancel"
                onPress={() => setShowAddForm(false)}
                style={[styles.addBtn, { backgroundColor: COLORS.disabledBg, flex: 1 }]}
              >
                <Text style={{ color: COLORS.text, fontWeight: FONT.weights.semibold }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                testID="items-new-submit"
                onPress={submitNewItem}
                disabled={adding}
                style={[styles.addBtn, { backgroundColor: COLORS.primary, flex: 2, opacity: adding ? 0.6 : 1 }]}
              >
                {adding ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text style={{ color: '#fff', fontWeight: FONT.weights.semibold }}>Add to bill</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        )}

        {group.items.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No items to claim.</Text>
          </View>
        ) : (
          group.items.map((it) => {
            const mine = claimed(it, userId);
            const total = totalClaimed(it);
            const others = total - mine;
            const remaining = it.quantity - total;
            const othersList = group.assignments
              .filter((a) => a.item_id === it.id && a.user_id !== userId && a.quantity > 0)
              .map((a) => {
                const m = group.members.find((x) => x.user_id === a.user_id);
                return { name: m?.name || '?', qty: a.quantity };
              });

            return (
              <Swipeable
                key={it.id}
                enabled={isLead && group.status !== 'closed' && !itemsLocked}
                renderLeftActions={() => renderRightActions(it.id, it.name)}
                renderRightActions={() => renderLeftActions(it.id)}
                overshootLeft={false}
                overshootRight={false}
                leftThreshold={40}
                rightThreshold={40}
              >
                <View style={styles.itemCard} testID={`items-item-${it.id}`}>
                <View style={styles.itemHeader}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.itemName}>
                      {it.name} {it.quantity > 1 ? `×${it.quantity}` : ''}
                    </Text>
                    <Text style={styles.itemPrice}>${it.price.toFixed(2)} each</Text>
                  </View>
                  {remaining === 0 ? (
                    <View style={styles.claimedBadge}>
                      <CheckCircle2 size={14} color={COLORS.success} />
                      <Text style={styles.claimedBadgeText}>Claimed</Text>
                    </View>
                  ) : (
                    <View style={styles.remainingBadge}>
                      <Text style={styles.remainingBadgeText}>{remaining} left</Text>
                    </View>
                  )}
                </View>

                <View style={styles.qtyRow}>
                  {Array.from({ length: it.quantity + 1 }).map((_, q) => {
                    const allowed = q <= mine + (it.quantity - total);
                    const active = mine === q;
                    return (
                      <TouchableOpacity
                        key={q}
                        testID={`items-qty-${it.id}-${q}`}
                        disabled={!allowed || saving === it.id}
                        onPress={() => setQty(it, q)}
                        style={[
                          styles.qtyBtn,
                          active && styles.qtyBtnActive,
                          !allowed && styles.qtyBtnDisabled,
                        ]}
                      >
                        <Text
                          style={[
                            styles.qtyBtnText,
                            active && { color: '#fff' },
                            !allowed && { color: COLORS.disabledText },
                          ]}
                        >
                          {q}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>

                {othersList.length > 0 && (
                  <View style={styles.othersRow}>
                    <UserCircle2 size={12} color={COLORS.subtext} />
                    <Text style={styles.othersText}>
                      {othersList.map((o) => `${o.name} ×${o.qty}`).join(', ')}
                    </Text>
                  </View>
                )}
                {isLead && remaining > 0 && (
                  <TouchableOpacity
                    testID={`items-lead-assign-${it.id}`}
                    onPress={() => leadAssignToMember(it)}
                    style={styles.leadAssignRow}
                  >
                    <UserCircle2 size={12} color={COLORS.primary} />
                    <Text style={styles.leadAssignText}>
                      Assign {remaining} unclaimed to a member →
                    </Text>
                  </TouchableOpacity>
                )}
                </View>
              </Swipeable>
            );
          })
        )}

        {isLead && group.items.length > 0 && group.status !== 'closed' && !itemsLocked && (
          <Text style={styles.swipeHint}>
            ← Swipe right to delete   ·   Swipe left to change quantity →
          </Text>
        )}
        {isLead && itemsLocked && (
          <Text style={styles.swipeHint}>🔒 Items locked — contributions started</Text>
        )}

        {group.unclaimed.length > 0 && (
          <View style={styles.warnCard}>
            <AlertCircle size={18} color={COLORS.warning} />
            <Text style={styles.warnText}>
              {group.unclaimed.length} item{group.unclaimed.length === 1 ? '' : 's'} still unclaimed
            </Text>
          </View>
        )}
      </ScrollView>

      <View style={styles.bottomBar}>
        <View style={{ flex: 1 }}>
          <Text style={styles.bottomLabel}>Your share</Text>
          <Text style={styles.bottomValue} testID="items-my-total">${myTotal.toFixed(2)}</Text>
        </View>
        <Button
          title="Done"
          testID="items-done-btn"
          onPress={() => router.push(`/group/${group.id}/summary`)}
        />
      </View>

      {/* Member picker — opens when the lead taps "Assign N unclaimed to a member".
          Replaces the legacy Alert.alert flow that silently failed on web. */}
      <Modal
        visible={!!assignTarget}
        transparent
        animationType="fade"
        onRequestClose={() => setAssignTarget(null)}
      >
        <Pressable style={styles.assignBackdrop} onPress={() => setAssignTarget(null)}>
          <Pressable style={styles.assignSheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.assignHeader}>
              <View style={{ flex: 1 }}>
                <Text style={styles.assignTitle}>
                  Assign 1× {assignTarget?.name || 'item'} to…
                </Text>
                <Text style={styles.assignSub}>Pick who ordered this</Text>
              </View>
              <TouchableOpacity onPress={() => setAssignTarget(null)} hitSlop={10}>
                <X size={20} color={COLORS.text} />
              </TouchableOpacity>
            </View>
            <ScrollView style={{ maxHeight: 360 }}>
              {group.members.map((m) => (
                <TouchableOpacity
                  key={m.user_id}
                  style={styles.assignRow}
                  onPress={() => doAssignToUser(m.user_id)}
                  activeOpacity={0.7}
                  testID={`items-assign-pick-${m.user_id}`}
                >
                  <View style={styles.assignAvatar}>
                    <Text style={styles.assignAvatarText}>
                      {(m.name || '?').slice(0, 1).toUpperCase()}
                    </Text>
                  </View>
                  <Text style={styles.assignName}>
                    {m.name}{m.user_id === userId ? ' (You)' : ''}
                    {m.user_id === group.lead_id ? '  · LEAD' : ''}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg },
  title: { fontSize: FONT.sizes.xxl, fontWeight: FONT.weights.bold, color: COLORS.text, letterSpacing: -0.5 },
  sub: { fontSize: FONT.sizes.md, color: COLORS.subtext, marginTop: 4, marginBottom: SPACING.lg },
  empty: { padding: SPACING.lg, alignItems: 'center' },
  emptyText: { color: COLORS.subtext },
  itemCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginBottom: SPACING.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  swipeDelete: {
    backgroundColor: COLORS.danger,
    width: 96,
    marginBottom: SPACING.sm,
    borderTopLeftRadius: RADIUS.md,
    borderBottomLeftRadius: RADIUS.md,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  swipeQty: {
    flexDirection: 'row',
    marginBottom: SPACING.sm,
    borderTopRightRadius: RADIUS.md,
    borderBottomRightRadius: RADIUS.md,
    overflow: 'hidden',
  },
  swipeQtyBtn: {
    width: 72,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  swipeDeleteText: {
    color: '#fff',
    fontWeight: FONT.weights.semibold,
    fontSize: FONT.sizes.xs,
  },
  swipeHint: {
    color: COLORS.subtext,
    fontSize: FONT.sizes.xs,
    fontStyle: 'italic',
    textAlign: 'center',
    marginTop: 4,
  },
  itemsHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  itemsBackBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerPlusBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: COLORS.primary,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: COLORS.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  itemHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACING.sm },
  itemName: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  itemPrice: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 2 },
  claimedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: COLORS.successLight,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: RADIUS.pill,
  },
  claimedBadgeText: { color: COLORS.success, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
  remainingBadge: {
    backgroundColor: COLORS.warningLight,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: RADIUS.pill,
  },
  remainingBadgeText: { color: COLORS.warning, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
  qtyRow: {
    flexDirection: 'row',
    backgroundColor: COLORS.disabledBg,
    borderRadius: RADIUS.md,
    padding: 4,
    gap: 4,
  },
  qtyBtn: {
    flex: 1,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: RADIUS.sm,
  },
  qtyBtnActive: {
    backgroundColor: COLORS.primary,
  },
  qtyBtnDisabled: { opacity: 0.5 },
  qtyBtnText: { color: COLORS.text, fontWeight: FONT.weights.semibold },
  othersRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: SPACING.sm },
  othersText: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
  leadAssignRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: SPACING.sm,
    paddingVertical: 6,
  },
  leadAssignText: { color: COLORS.primary, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
  warnCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: COLORS.warningLight,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    marginTop: SPACING.md,
  },
  warnText: { color: '#92400E', fontSize: FONT.sizes.sm, fontWeight: FONT.weights.medium, flex: 1 },
  lockBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: COLORS.primaryLight,
    padding: SPACING.md,
    borderRadius: RADIUS.md,
    marginBottom: SPACING.md,
  },
  lockText: { color: COLORS.primary, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.medium, flex: 1, lineHeight: 16 },
  addCard: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    borderStyle: 'dashed',
    marginTop: SPACING.md,
  },
  addTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text, marginBottom: SPACING.sm },
  addInput: {
    height: 44,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    backgroundColor: COLORS.bg,
    paddingHorizontal: SPACING.md,
    fontSize: FONT.sizes.sm,
    color: COLORS.text,
    marginBottom: 8,
  },
  addBtn: { height: 44, borderRadius: RADIUS.md, alignItems: 'center', justifyContent: 'center' },
  addToggleBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: SPACING.sm,
  },
  addToggleText: { color: COLORS.primary, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.md },
  bottomBar: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
  },
  bottomLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, textTransform: 'uppercase', letterSpacing: 1 },
  bottomValue: { fontSize: FONT.sizes.xxl, fontWeight: FONT.weights.bold, color: COLORS.text },
  // Assign-to-member picker modal (replaces the legacy Alert.alert flow).
  assignBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(15,23,42,0.55)',
    justifyContent: 'flex-end',
  },
  assignSheet: {
    backgroundColor: COLORS.surface,
    borderTopLeftRadius: RADIUS.xl,
    borderTopRightRadius: RADIUS.xl,
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.lg,
    paddingBottom: SPACING.xl,
    gap: SPACING.sm,
  },
  assignHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: SPACING.sm,
  },
  assignTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.heavy, color: COLORS.text },
  assignSub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 2 },
  assignRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.sm,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
  },
  assignAvatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  assignAvatarText: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  assignName: { color: COLORS.text, fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, flex: 1 },
});
