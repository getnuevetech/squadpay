import { useEffect, useState, useCallback, useMemo } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, Platform, TextInput } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { ArrowLeft, Ban, ShieldCheck, Crown, Users as UsersIcon, ListChecks, Wallet } from 'lucide-react-native';
import { adminApi, AdminGroupDetail } from '../../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';

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
          <Text style={styles.meta}>code {group.code} • split mode {group.split_mode || 'itemized'}</Text>
          <TouchableOpacity onPress={() => router.push(`/admin/users/${group.lead_id}` as any)} activeOpacity={0.7}>
            <Text style={styles.leadLink}><Crown size={11} color={COLORS.warning} />  Lead: {group.lead_name || group.lead_id}{group.lead_phone ? ` • ${group.lead_phone}` : ''}</Text>
          </TouchableOpacity>
          <Text style={styles.metaSmall}>created {new Date(group.created_at).toLocaleString()}</Text>
          {group.is_blocked && group.blocked_reason ? (
            <Text style={styles.blockedReason}>Reason: {group.blocked_reason}</Text>
          ) : null}
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

      <View style={styles.section}>
        <View style={styles.sectionHeader}><UsersIcon size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Members ({group.members.length})</Text></View>
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
  headerCard: { padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginBottom: SPACING.md },
  title: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  statusBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4, backgroundColor: COLORS.primaryLight },
  statusBadgeText: { fontSize: 10, fontWeight: FONT.weights.bold, color: COLORS.primary, letterSpacing: 0.4 },
  blockedBadge: { backgroundColor: COLORS.dangerLight },
  meta: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 4 },
  leadLink: { fontSize: FONT.sizes.sm, color: COLORS.primary, marginTop: 2, fontWeight: FONT.weights.medium },
  metaSmall: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
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
});
