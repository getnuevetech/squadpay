import { useEffect, useState, useCallback, useMemo } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, Platform, TextInput } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { ArrowLeft, Ban, ShieldCheck, Crown, Users as UsersIcon, ListChecks, Wallet, Percent, DollarSign, X as XIcon, Tag, RefreshCw } from 'lucide-react-native';
import { adminApi, AdminGroupDetail, getProfile, AdminProfile } from '../../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { formatSid, formatUid } from '../../../src/ids';

function confirm(title: string, message: string, onYes: () => void) {
  if (Platform.OS === 'web') {
    if (typeof window !== 'undefined' && window.confirm(`${title}\n\n${message}`)) onYes();
  } else {
    Alert.alert(title, message, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Yes', style: 'destructive', onPress: onYes },
    ]);
  }
}

export default function AdminGroupDetailPage() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [group, setGroup] = useState<AdminGroupDetail | null>(null);
  const [busy, setBusy] = useState(true);
  const [reason, setReason] = useState('');
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [reassignOpen, setReassignOpen] = useState(false);
  // C2: discount form
  const [dType, setDType] = useState<'flat' | 'percent'>('percent');
  const [dValue, setDValue] = useState('');
  const [dNote, setDNote] = useState('');

  useEffect(() => { (async () => { setProfile(await getProfile()); })(); }, []);

  const load = useCallback(async () => {
    if (!id) return;
    setBusy(true);
    try { setGroup(await adminApi.getGroup(id)); }
    catch (e: any) { Alert.alert('Error', e?.message || 'Failed to load group'); }
    finally { setBusy(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const onBlock = () => {
    if (!group) return;
    confirm(
      'Block group?',
      `This freezes contributions and merchant payment for "${group.title}". The group becomes read-only.`,
      async () => {
        try { await adminApi.blockGroup(group.id, true, reason || undefined); setReason(''); await load(); }
        catch (e: any) { Alert.alert('Error', e?.message || 'Failed to block'); }
      }
    );
  };
  const onUnblock = () => {
    if (!group) return;
    confirm('Unblock group?', `"${group.title}" will accept contributions and payments again.`, async () => {
      try { await adminApi.blockGroup(group.id, false); await load(); }
      catch (e: any) { Alert.alert('Error', e?.message || 'Failed to unblock'); }
    });
  };

  const onSetDiscount = async () => {
    const v = parseFloat(dValue);
    if (!v || v <= 0) { Alert.alert('Invalid', 'Value must be > 0'); return; }
    if (dType === 'percent' && v > 100) { Alert.alert('Invalid', 'Percent must be ≤ 100'); return; }
    try {
      await adminApi.setGroupDiscount(group!.id, { type: dType, value: v, note: dNote || undefined });
      setDValue(''); setDNote('');
      await load();
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
  };
  const onClearDiscount = () => {
    confirm('Clear discount?', 'The bill total will revert to the original amount.', async () => {
      try { await adminApi.clearGroupDiscount(group!.id); await load(); }
      catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    });
  };

  const itemMap = useMemo(() => {
    const m: Record<string, { name: string; price: number }> = {};
    (group?.items || []).forEach((it) => { m[it.id] = { name: it.name, price: it.price }; });
    return m;
  }, [group]);

  const userMap = useMemo(() => {
    const m: Record<string, string> = {};
    (group?.members || []).forEach((mb) => { m[mb.user_id] = mb.name || mb.user_id; });
    return m;
  }, [group]);

  if (busy || !group) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  const subtotal = (group.items || []).reduce((s, it) => s + it.price * it.quantity, 0);
  const collected = group.contributions_total;
  const remaining = Math.max(0, group.total_amount - collected);

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} activeOpacity={0.7} testID="admin-group-back">
        <ArrowLeft size={16} color={COLORS.subtext} />
        <Text style={styles.backText}>All groups</Text>
      </TouchableOpacity>

      <View style={styles.headerCard}>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Text style={styles.title}>{group.title}</Text>
            <View style={[styles.statusBadge, group.is_blocked ? styles.blockedBadge : null]}>
              <Text style={[styles.statusBadgeText, group.is_blocked && { color: COLORS.danger }]}>{group.is_blocked ? 'BLOCKED' : group.status?.toUpperCase()}</Text>
            </View>
          </View>

          {/* Labeled info table — each field labeled and spaced for clear scanning */}
          <View style={styles.infoTable} testID="admin-group-info-table">
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Join code</Text>
              <Text style={[styles.infoValue, styles.mono]} selectable>{group.code}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Squad ID</Text>
              <Text style={[styles.infoValue, styles.mono]} selectable testID="admin-group-sid">{formatSid(group.id)}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Split mode</Text>
              <Text style={styles.infoValue}>{group.split_mode || 'itemized'}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Lead</Text>
              <TouchableOpacity style={{ flex: 1 }} onPress={() => router.push(`/admin/users/${group.lead_id}` as any)} activeOpacity={0.7}>
                <Text style={[styles.infoValue, { color: COLORS.primary, fontWeight: FONT.weights.semibold }]}>
                  <Crown size={11} color={COLORS.warning} /> {group.lead_name || group.lead_id}
                </Text>
                {group.lead_phone ? <Text style={styles.infoValueSm}>{group.lead_phone}</Text> : null}
                <Text style={[styles.infoValueSm, styles.mono]} testID="admin-group-lead-uid">
                  {formatUid(group.lead_id)}
                </Text>
              </TouchableOpacity>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Created</Text>
              <Text style={styles.infoValue}>{new Date(group.created_at).toLocaleString()}</Text>
            </View>
            {group.is_blocked && group.blocked_reason ? (
              <View style={styles.infoRow}>
                <Text style={styles.infoLabel}>Block reason</Text>
                <Text style={[styles.infoValue, { color: COLORS.danger, fontStyle: 'italic' }]}>{group.blocked_reason}</Text>
              </View>
            ) : null}
          </View>
        </View>
      </View>

      <View style={styles.statsRow}>
        <View style={styles.statCard}><Text style={styles.statLabel}>Subtotal</Text><Text style={styles.statValue}>${subtotal.toFixed(2)}</Text></View>
        <View style={styles.statCard}><Text style={styles.statLabel}>Tax + Tip</Text><Text style={styles.statValue}>${((group.tax || 0) + (group.tip || 0)).toFixed(2)}</Text></View>
        <View style={styles.statCard}><Text style={styles.statLabel}>Total</Text><Text style={styles.statValue}>${group.total_amount.toFixed(2)}</Text></View>
        <View style={styles.statCard}><Text style={styles.statLabel}>Collected</Text><Text style={[styles.statValue, { color: COLORS.success }]}>${collected.toFixed(2)}</Text></View>
        <View style={styles.statCard}><Text style={styles.statLabel}>Remaining</Text><Text style={[styles.statValue, { color: remaining > 0 ? COLORS.danger : COLORS.subtext }]}>${remaining.toFixed(2)}</Text></View>
      </View>

      <View style={styles.actionsCard}>
        {group.is_blocked ? (
          <TouchableOpacity onPress={onUnblock} style={[styles.actionBtn, { backgroundColor: COLORS.success }]} activeOpacity={0.85} testID="admin-group-unblock">
            <ShieldCheck size={16} color="#fff" /><Text style={styles.actionBtnText}>Unblock group</Text>
          </TouchableOpacity>
        ) : (
          <View style={{ gap: 8 }}>
            <Text style={styles.label}>Reason (optional)</Text>
            <TextInput
              style={styles.input}
              placeholder="e.g. dispute, fraud, abandoned…"
              placeholderTextColor={COLORS.disabledText}
              value={reason}
              onChangeText={setReason}
              testID="admin-group-block-reason"
            />
            <TouchableOpacity onPress={onBlock} style={[styles.actionBtn, { backgroundColor: COLORS.danger }]} activeOpacity={0.85} testID="admin-group-block">
              <Ban size={16} color="#fff" /><Text style={styles.actionBtnText}>Block group</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>

      {/* Phase F1: Stripe Issuing virtual card */}
      {(group as any).virtual_card?.stripe_card_id ? (
        <View style={styles.section}>
          <View style={styles.sectionHeader}><Crown size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Virtual card · {(group as any).virtual_card.nickname || 'SquadPay'}</Text></View>
          <Text style={styles.metaSmall}>
            {(group as any).virtual_card.brand} •••• {(group as any).virtual_card.last4} · exp {String((group as any).virtual_card.exp_month).padStart(2,'0')}/{String((group as any).virtual_card.exp_year).slice(-2)} · status {(group as any).virtual_card.status}
          </Text>
          <Text style={styles.metaSmall}>
            Spent ${((group as any).virtual_card.spent || 0).toFixed(2)} / cap ${((group as any).virtual_card.spend_cap || 0).toFixed(2)} · stripe id {(group as any).virtual_card.stripe_card_id}
          </Text>
          {(group as any).virtual_card.status === 'active' ? (
            <TouchableOpacity
              onPress={() => confirm(
                'Disable virtual card?',
                'The card will be set to inactive on Stripe (kept in history, not deleted). This cannot be re-enabled from here.',
                async () => {
                  try { await adminApi.disableGroupCard(group.id); await load(); }
                  catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
                },
              )}
              style={[styles.actionBtn, { backgroundColor: COLORS.danger, marginTop: 8 }]} activeOpacity={0.85}
              testID="admin-group-disable-card"
            >
              <Ban size={16} color="#fff" /><Text style={styles.actionBtnText}>Disable virtual card</Text>
            </TouchableOpacity>
          ) : (
            <Text style={[styles.metaSmall, { color: COLORS.warning, marginTop: 6 }]}>
              Disabled {(group as any).virtual_card.disabled_at ? new Date((group as any).virtual_card.disabled_at).toLocaleString() : ''} by {(group as any).virtual_card.disabled_by || '—'}
            </Text>
          )}
        </View>
      ) : null}

      <View style={styles.section}>
        <View style={styles.sectionHeader}><Tag size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Discount</Text></View>
        {group.discount ? (
          <View style={styles.discountActive} testID="admin-group-discount-active">
            <View style={{ flex: 1 }}>
              <Text style={styles.discountValueText}>
                -{group.discount.type === 'percent' ? `${group.discount.value}%` : `$${group.discount.value.toFixed(2)}`}
                {' '}({`-$${group.discount.amount.toFixed(2)}`})
              </Text>
              <Text style={styles.metaSmall}>{group.discount.note || 'No note'} • applied by {group.discount.applied_by}</Text>
              {group.original_total_amount ? (
                <Text style={styles.metaSmall}>Original ${group.original_total_amount.toFixed(2)} → New ${group.total_amount.toFixed(2)}</Text>
              ) : null}
            </View>
            <TouchableOpacity onPress={onClearDiscount} style={[styles.smallBtn, { backgroundColor: COLORS.danger }]} activeOpacity={0.85} testID="admin-group-discount-clear">
              <XIcon size={14} color="#fff" />
              <Text style={styles.smallBtnText}>Clear</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <View style={{ gap: 8 }}>
            <Text style={styles.metaSmall}>Reduces total amount before split. One discount per group.</Text>
            <View style={styles.formRow}>
              <TouchableOpacity onPress={() => setDType('flat')} style={[styles.toggle, dType === 'flat' && styles.toggleActive]} activeOpacity={0.85}>
                <DollarSign size={12} color={dType === 'flat' ? '#fff' : COLORS.text} /><Text style={[styles.toggleText, dType === 'flat' && { color: '#fff' }]}>Flat</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => setDType('percent')} style={[styles.toggle, dType === 'percent' && styles.toggleActive]} activeOpacity={0.85}>
                <Percent size={12} color={dType === 'percent' ? '#fff' : COLORS.text} /><Text style={[styles.toggleText, dType === 'percent' && { color: '#fff' }]}>Percent</Text>
              </TouchableOpacity>
              <TextInput
                style={[styles.input, { flex: 1 }]}
                placeholder={dType === 'percent' ? '20' : '5'}
                placeholderTextColor={COLORS.disabledText}
                keyboardType="decimal-pad"
                value={dValue}
                onChangeText={setDValue}
                testID="admin-group-discount-value"
              />
              <TextInput
                style={[styles.input, { flex: 2 }]}
                placeholder="Note (e.g. promo)"
                placeholderTextColor={COLORS.disabledText}
                value={dNote}
                onChangeText={setDNote}
                testID="admin-group-discount-note"
              />
              <TouchableOpacity onPress={onSetDiscount} style={[styles.smallBtn, { backgroundColor: COLORS.primary }]} activeOpacity={0.85} testID="admin-group-discount-apply">
                <Text style={styles.smallBtnText}>Apply</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <UsersIcon size={14} color={COLORS.text} />
          <Text style={styles.sectionTitle}>Squad ({group.members.length})</Text>
          {profile?.role === 'super_admin' && (
            <TouchableOpacity
              onPress={() => setReassignOpen((v) => !v)}
              style={[styles.smallBtn, { backgroundColor: COLORS.primary, marginLeft: 'auto' }]}
              activeOpacity={0.85}
              testID="admin-group-reassign-toggle"
            >
              <RefreshCw size={12} color="#fff" />
              <Text style={styles.smallBtnText}>{reassignOpen ? 'Cancel' : 'Reassign Lead'}</Text>
            </TouchableOpacity>
          )}
        </View>

        {profile?.role === 'super_admin' && reassignOpen && (
          <View style={styles.reassignPanel} testID="admin-group-reassign-panel">
            <Text style={styles.reassignTitle}>Pick a new lead</Text>
            <Text style={styles.metaSmall}>
              The new lead must already be a member of this group. Once reassigned, the new
              lead gets full access to dashboard, items, virtual card and member management.
            </Text>
            {group.members.map((m) => {
              const isCurrentLead = m.user_id === group.lead_id;
              return (
                <TouchableOpacity
                  key={`reassign-${m.user_id}`}
                  disabled={isCurrentLead}
                  onPress={() => {
                    confirm(
                      'Reassign lead?',
                      `Transfer leadership of "${group.title}" to ${m.name || m.user_id}? This change is logged.`,
                      async () => {
                        try {
                          await adminApi.reassignGroupLead(group.id, m.user_id);
                          setReassignOpen(false);
                          await load();
                        } catch (e: any) {
                          Alert.alert('Error', e?.message || 'Failed to reassign lead');
                        }
                      },
                    );
                  }}
                  style={[styles.reassignRow, isCurrentLead && { opacity: 0.5 }]}
                  activeOpacity={0.7}
                  testID={`admin-group-reassign-pick-${m.user_id}`}
                >
                  <View style={{ flex: 1 }}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                      <Text style={styles.memberName}>{m.name || m.user_id}</Text>
                      {isCurrentLead ? (
                        <View style={[styles.smallBtn, { backgroundColor: COLORS.warning, paddingHorizontal: 6, paddingVertical: 2 }]}>
                          <Crown size={10} color="#fff" />
                          <Text style={styles.smallBtnText}>CURRENT</Text>
                        </View>
                      ) : null}
                    </View>
                    <Text style={styles.metaSmall}>{m.phone || 'no phone'}</Text>
                  </View>
                  {!isCurrentLead && (
                    <Text style={[styles.smallBtnText, { color: COLORS.primary }]}>Make Lead →</Text>
                  )}
                </TouchableOpacity>
              );
            })}
          </View>
        )}

        {group.members.map((m) => (
          <TouchableOpacity
            key={m.user_id}
            style={styles.memberRow}
            onPress={() => router.push(`/admin/users/${m.user_id}` as any)}
            activeOpacity={0.85}
            testID={`admin-group-member-${m.user_id}`}
          >
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <Text style={styles.memberName}>{m.name || m.user_id}</Text>
                {m.role === 'lead' ? <Crown size={11} color={COLORS.warning} /> : null}
                {m.verified ? <ShieldCheck size={11} color={COLORS.success} /> : null}
                {m.is_blocked ? <View style={styles.blockedPill}><Text style={styles.blockedPillText}>BLOCKED</Text></View> : null}
              </View>
              <Text style={styles.metaSmall}>{m.phone || 'no phone'} • joined {new Date(m.joined_at).toLocaleDateString()}</Text>
            </View>
          </TouchableOpacity>
        ))}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}><ListChecks size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Items ({group.items.length})</Text></View>
        {group.items.length === 0 ? <Text style={styles.empty}>No items.</Text> : group.items.map((it) => (
          <View key={it.id} style={styles.itemRow}>
            <Text style={styles.itemName} numberOfLines={1}>{it.name}</Text>
            <Text style={styles.metaSmall}>x{it.quantity}</Text>
            <Text style={styles.itemPrice}>${(it.price * it.quantity).toFixed(2)}</Text>
          </View>
        ))}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}><Wallet size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Contributions ({group.contributions.length})</Text></View>
        {group.contributions.length === 0 ? <Text style={styles.empty}>No contributions yet.</Text> : group.contributions.map((c) => (
          <View key={c.id} style={styles.contribRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.itemName}>{userMap[c.user_id] || c.user_id}</Text>
              <Text style={styles.metaSmall}>{new Date(c.at).toLocaleString()}</Text>
            </View>
            <Text style={[styles.itemPrice, { color: COLORS.success }]}>+${c.amount.toFixed(2)}</Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  backBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: SPACING.md },
  backText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.medium },
  headerCard: { padding: SPACING.lg, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginBottom: SPACING.md },
  title: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  statusBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4, backgroundColor: COLORS.primaryLight },
  statusBadgeText: { fontSize: 10, fontWeight: FONT.weights.bold, color: COLORS.primary, letterSpacing: 0.4 },
  blockedBadge: { backgroundColor: COLORS.dangerLight },
  meta: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 4 },
  leadLink: { fontSize: FONT.sizes.sm, color: COLORS.primary, marginTop: 2, fontWeight: FONT.weights.medium },
  metaSmall: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  // Labeled info table — narrow label column with stacked rows + room to breathe.
  infoTable: { marginTop: SPACING.md, gap: 10 },
  infoRow: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACING.sm },
  infoLabel: { width: 100, fontSize: 11, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.bold, letterSpacing: 0.4, paddingTop: 1 },
  infoValue: { flex: 1, fontSize: FONT.sizes.sm, color: COLORS.text, lineHeight: 18 },
  infoValueSm: { flex: 1, fontSize: 11, color: COLORS.subtext, lineHeight: 16, marginTop: 1 },
  mono: { fontFamily: 'monospace', letterSpacing: 0.4 },
  sidLine: {
    fontSize: 12,
    color: COLORS.subtext,
    marginTop: 4,
    fontFamily: 'monospace',
    letterSpacing: 0.6,
    fontWeight: FONT.weights.semibold,
  },
  uidLine: {
    fontSize: 11,
    color: COLORS.subtext,
    marginTop: 2,
    fontFamily: 'monospace',
    letterSpacing: 0.4,
  },
  blockedReason: { fontSize: FONT.sizes.xs, color: COLORS.danger, marginTop: 6, fontStyle: 'italic' },
  statsRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.md, flexWrap: 'wrap' },
  statCard: { flex: 1, minWidth: 100, padding: SPACING.sm, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md },
  statLabel: { fontSize: 10, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.medium },
  statValue: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 2 },
  actionsCard: { padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginBottom: SPACING.md },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.medium },
  input: { height: 40, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.bg },
  actionBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, height: 42, borderRadius: RADIUS.md },
  actionBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  section: { marginBottom: SPACING.md, padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: SPACING.sm },
  sectionTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  empty: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic' },
  memberRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  memberName: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  itemRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  itemName: { flex: 1, fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.medium },
  itemPrice: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold, color: COLORS.text },
  contribRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  blockedPill: { backgroundColor: COLORS.dangerLight, paddingHorizontal: 6, paddingVertical: 1, borderRadius: 4 },
  blockedPillText: { fontSize: 9, color: COLORS.danger, fontWeight: FONT.weights.bold },
  // C2 styles
  formRow: { flexDirection: 'row', gap: 8, alignItems: 'center', flexWrap: 'wrap' },
  smallBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 12, height: 38, borderRadius: RADIUS.md, justifyContent: 'center' },
  smallBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, height: 38, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  toggleActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  toggleText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold, color: COLORS.text },
  discountActive: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: SPACING.sm, backgroundColor: COLORS.successLight, borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.success },
  discountValueText: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.success },
  reassignPanel: {
    marginTop: SPACING.sm,
    backgroundColor: COLORS.primaryLight,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    gap: 6,
    borderWidth: 1,
    borderColor: COLORS.primary,
  },
  reassignTitle: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold, color: COLORS.primary },
  reassignRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.surface,
    paddingHorizontal: SPACING.sm,
    paddingVertical: 10,
    borderRadius: RADIUS.sm,
    marginTop: 6,
    gap: 8,
  },
});
