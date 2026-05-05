import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, Platform, TextInput } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { ArrowLeft, Ban, ShieldCheck, Crown, Users as UsersIcon } from 'lucide-react-native';
import { adminApi, AdminUserDetail, AdminGroupRow } from '../../../src/adminApi';
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

export default function AdminUserDetailPage() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [user, setUser] = useState<AdminUserDetail | null>(null);
  const [busy, setBusy] = useState(true);
  const [reason, setReason] = useState('');

  const load = useCallback(async () => {
    if (!id) return;
    setBusy(true);
    try { setUser(await adminApi.getUser(id)); }
    catch (e: any) { Alert.alert('Error', e?.message || 'Failed to load user'); }
    finally { setBusy(false); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const onBlock = () => {
    if (!user) return;
    confirm(
      'Block user?',
      `This will prevent ${user.name} from logging in or contributing to bills. They can be unblocked later.`,
      async () => {
        try { await adminApi.blockUser(user.id, true, reason || undefined); setReason(''); await load(); }
        catch (e: any) { Alert.alert('Error', e?.message || 'Failed to block'); }
      }
    );
  };

  const onUnblock = () => {
    if (!user) return;
    confirm(
      'Unblock user?',
      `${user.name} will be able to log in and contribute again.`,
      async () => {
        try { await adminApi.blockUser(user.id, false); await load(); }
        catch (e: any) { Alert.alert('Error', e?.message || 'Failed to unblock'); }
      }
    );
  };

  if (busy || !user) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  const renderGroup = (g: AdminGroupRow, i: number) => (
    <TouchableOpacity
      key={g.id || i}
      style={styles.groupRow}
      onPress={() => router.push(`/admin/groups/${g.id}` as any)}
      activeOpacity={0.85}
      testID={`admin-user-group-${g.id}`}
    >
      <View style={{ flex: 1 }}>
        <Text style={styles.groupTitle} numberOfLines={1}>{g.title || 'Untitled bill'}</Text>
        <Text style={styles.groupMeta}>{g.code} • {g.status} • {g.members_count} members</Text>
      </View>
      <Text style={styles.groupAmount}>${(g.total_amount || 0).toFixed(2)}</Text>
    </TouchableOpacity>
  );

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} activeOpacity={0.7} testID="admin-user-back">
        <ArrowLeft size={16} color={COLORS.subtext} />
        <Text style={styles.backText}>All users</Text>
      </TouchableOpacity>

      <View style={styles.headerCard}>
        <View style={[styles.avatar, user.is_blocked && { backgroundColor: COLORS.dangerLight }]}>
          <Text style={[styles.avatarText, user.is_blocked && { color: COLORS.danger }]}>{(user.name || '?').slice(0, 1).toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <Text style={styles.name}>{user.name}</Text>
            {user.verified ? <ShieldCheck size={14} color={COLORS.success} /> : null}
            {user.is_blocked ? (
              <View style={styles.blockedPill}><Ban size={11} color={COLORS.danger} /><Text style={styles.blockedPillText}>Blocked</Text></View>
            ) : null}
          </View>
          <Text style={styles.meta}>{user.phone || 'no phone on file'}</Text>
          <Text style={styles.metaSmall}>id {user.id} • joined {new Date(user.created_at).toLocaleDateString()}</Text>
          {user.is_blocked && user.blocked_reason ? (
            <Text style={styles.blockedReason}>Reason: {user.blocked_reason}</Text>
          ) : null}
        </View>
      </View>

      <View style={styles.statsRow}>
        <View style={styles.statCard}><Text style={styles.statLabel}>As lead</Text><Text style={styles.statValue}>{user.led_groups.length}</Text></View>
        <View style={styles.statCard}><Text style={styles.statLabel}>As member</Text><Text style={styles.statValue}>{user.joined_groups.length}</Text></View>
        <View style={styles.statCard}><Text style={styles.statLabel}>Lead billed</Text><Text style={styles.statValue}>${user.total_billed_as_lead.toFixed(2)}</Text></View>
      </View>

      <View style={styles.actionsCard}>
        {user.is_blocked ? (
          <TouchableOpacity onPress={onUnblock} style={[styles.actionBtn, { backgroundColor: COLORS.success }]} activeOpacity={0.85} testID="admin-user-unblock">
            <ShieldCheck size={16} color="#fff" /><Text style={styles.actionBtnText}>Unblock user</Text>
          </TouchableOpacity>
        ) : (
          <View style={{ gap: 8 }}>
            <Text style={styles.label}>Reason (optional)</Text>
            <TextInput
              style={styles.input}
              placeholder="e.g. fraud, abuse, requested by user…"
              placeholderTextColor={COLORS.disabledText}
              value={reason}
              onChangeText={setReason}
              testID="admin-user-block-reason"
            />
            <TouchableOpacity onPress={onBlock} style={[styles.actionBtn, { backgroundColor: COLORS.danger }]} activeOpacity={0.85} testID="admin-user-block">
              <Ban size={16} color="#fff" /><Text style={styles.actionBtnText}>Block user</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}><Crown size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Groups led ({user.led_groups.length})</Text></View>
        {user.led_groups.length === 0 ? <Text style={styles.empty}>None.</Text> : user.led_groups.map(renderGroup)}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}><UsersIcon size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Groups joined ({user.joined_groups.length})</Text></View>
        {user.joined_groups.length === 0 ? <Text style={styles.empty}>None.</Text> : user.joined_groups.map(renderGroup)}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  backBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: SPACING.md },
  backText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.medium },
  headerCard: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginBottom: SPACING.md },
  avatar: { width: 56, height: 56, borderRadius: 28, backgroundColor: COLORS.primaryLight, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: COLORS.primary, fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold },
  name: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  meta: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 2 },
  metaSmall: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  blockedPill: { flexDirection: 'row', alignItems: 'center', gap: 3, backgroundColor: COLORS.dangerLight, paddingHorizontal: 6, paddingVertical: 2, borderRadius: RADIUS.pill },
  blockedPillText: { fontSize: 10, color: COLORS.danger, fontWeight: FONT.weights.bold },
  blockedReason: { fontSize: FONT.sizes.xs, color: COLORS.danger, marginTop: 6, fontStyle: 'italic' },
  statsRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.md, flexWrap: 'wrap' },
  statCard: { flex: 1, minWidth: 120, padding: SPACING.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md },
  statLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.medium },
  statValue: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 4 },
  actionsCard: { padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginBottom: SPACING.md },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.medium },
  input: { height: 40, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.bg },
  actionBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, height: 42, borderRadius: RADIUS.md },
  actionBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  section: { marginBottom: SPACING.md, padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: SPACING.sm },
  sectionTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  empty: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic' },
  groupRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  groupTitle: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  groupMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  groupAmount: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold, color: COLORS.text },
});
