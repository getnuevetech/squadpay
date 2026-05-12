import { useEffect, useState } from 'react';
import { View, Text, ScrollView, TextInput, StyleSheet, ActivityIndicator } from 'react-native';
import { adminApi, AuditEntry } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { formatUid, formatSid } from '../../src/ids';

/** Render the audit row's target identifier in friendly UID/SID form when applicable. */
function formatTarget(targetType?: string | null, targetId?: string | null): string {
  if (!targetId) return '';
  const t = (targetType || '').toLowerCase();
  if (t === 'user' || t === 'admin' || targetId.startsWith('u_')) return formatUid(targetId);
  if (t === 'group' || t === 'squad' || targetId.startsWith('g_')) return formatSid(targetId);
  return `${targetType || 'item'}:${targetId}`;
}

export default function AdminAudit() {
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [busy, setBusy] = useState(true);
  const [filterAction, setFilterAction] = useState('');

  const load = async () => {
    setBusy(true);
    try {
      const r = await adminApi.auditLog({ limit: 200, action: filterAction || undefined });
      setItems(r.items);
    } finally { setBusy(false); }
  };
  useEffect(() => { load(); }, []);

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="admin-audit-heading">Audit log</Text>
      <Text style={styles.subheading}>Every administrative action is recorded immutably.</Text>
      <View style={styles.filterRow}>
        <TextInput style={styles.filter} placeholder="Filter by action (e.g. admin.login)" placeholderTextColor={COLORS.disabledText} value={filterAction} onChangeText={setFilterAction} onSubmitEditing={load} testID="admin-audit-filter" />
      </View>
      {busy ? <ActivityIndicator color={COLORS.primary} style={{ marginTop: 24 }} /> : null}
      {!busy && items.length === 0 ? <Text style={styles.empty}>No entries match.</Text> : null}
      {items.map((r) => (
        <View key={r.id} style={styles.row} testID={`audit-row-${r.id}`}>
          <View style={[styles.dot, { backgroundColor: r.destructive ? COLORS.danger : COLORS.primary }]} />
          <View style={{ flex: 1 }}>
            <Text style={styles.action}>{r.action}</Text>
            <Text style={styles.meta}>by {r.admin_email} • {new Date(r.at).toLocaleString()}</Text>
            {r.target_id ? (
              <Text style={styles.target} selectable>
                target {r.target_type || 'item'} · {formatTarget(r.target_type, r.target_id)}
              </Text>
            ) : null}
            {r.payload && Object.keys(r.payload).length > 0 ? (
              <Text style={styles.payload}>{JSON.stringify(r.payload)}</Text>
            ) : null}
          </View>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.md },
  filterRow: { marginBottom: SPACING.md },
  filter: { height: 40, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.surface },
  empty: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic', marginTop: 24 },
  row: { flexDirection: 'row', gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  action: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  meta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  target: {
    fontSize: 11,
    color: COLORS.subtext,
    marginTop: 2,
    fontFamily: 'monospace',
    letterSpacing: 0.5,
  },
  payload: { fontSize: 11, color: COLORS.subtext, marginTop: 4, fontFamily: 'monospace' },
});
