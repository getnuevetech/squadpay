import { useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, ActivityIndicator, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { adminApi, AdminMetrics, AuditEntry, AdminProfile, getProfile } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { Receipt, Users, ScrollText, Wallet, Activity, KeyRound, ChevronRight } from 'lucide-react-native';

function Tile({ icon, label, value, sub, color = COLORS.primary }: any) {
  return (
    <View style={styles.tile}>
      <View style={[styles.tileIcon, { backgroundColor: color + '22' }]}>{icon}</View>
      <View style={{ flex: 1 }}>
        <Text style={styles.tileLabel}>{label}</Text>
        <Text style={styles.tileValue}>{value}</Text>
        {sub ? <Text style={styles.tileSub}>{sub}</Text> : null}
      </View>
    </View>
  );
}

export default function AdminDashboard() {
  const router = useRouter();
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [recent, setRecent] = useState<AuditEntry[]>([]);
  const [busy, setBusy] = useState(true);
  const [profile, setProfile] = useState<AdminProfile | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [m, a, me] = await Promise.all([
          adminApi.metrics(),
          adminApi.auditLog({ limit: 8 }).catch(() => ({ items: [] as AuditEntry[] })),
          adminApi.me().catch(() => null),
        ]);
        setMetrics(m);
        setRecent((a as any).items || []);
        if (me) setProfile(me);
        else {
          const cached = await getProfile();
          if (cached) setProfile(cached);
        }
      } finally { setBusy(false); }
    })();
  }, []);

  if (busy) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="admin-dashboard-heading">Dashboard</Text>
      <Text style={styles.subheading}>Live metrics across the platform</Text>

      {/* P2 — Soft nudge: prompt seeded super-admins to rotate the default password. */}
      {profile?.must_change_default_password ? (
        <TouchableOpacity
          onPress={() => router.push('/admin/change-password')}
          style={styles.nudgeBanner}
          activeOpacity={0.85}
          testID="admin-default-password-banner"
        >
          <View style={styles.nudgeIcon}>
            <KeyRound size={16} color={COLORS.warning} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.nudgeTitle}>Rotate the default password</Text>
            <Text style={styles.nudgeSub}>
              You're still using the seeded super-admin password. Change it now to secure the dashboard.
            </Text>
          </View>
          <Text style={styles.nudgeCta} testID="admin-default-password-banner-cta">Change</Text>
          <ChevronRight size={14} color={COLORS.warning} />
        </TouchableOpacity>
      ) : null}

      <View style={styles.grid}>
        <Tile icon={<Receipt size={18} color={COLORS.primary} />} label="Total bills" value={metrics?.groups_total ?? '—'} sub={`${metrics?.groups_active ?? 0} active`} />
        <Tile icon={<Activity size={18} color={'#F59E0B'} />} color="#F59E0B" label="Awaiting settlement" value={metrics?.groups_paid ?? 0} sub="Paid by lead, members may still owe" />
        <Tile icon={<Users size={18} color={COLORS.success} />} color={COLORS.success} label="Users" value={metrics?.users_total ?? '—'} sub={`${metrics?.admins_total ?? 0} admins`} />
        <Tile icon={<Wallet size={18} color={'#8B5CF6'} />} color="#8B5CF6" label="Total billed" value={`$${(metrics?.total_billed || 0).toFixed(2)}`} sub={`$${(metrics?.total_contributed || 0).toFixed(2)} contributed`} />
      </View>

      <TouchableOpacity
        style={styles.quickLink}
        activeOpacity={0.85}
        onPress={() => router.push('/admin/platform-fees')}
        testID="admin-link-platform-fees"
      >
        <View style={[styles.tileIcon, { backgroundColor: COLORS.primary + '22' }]}>
          <Wallet size={18} color={COLORS.primary} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.tileLabel}>Platform Fees</Text>
          <Text style={styles.tileSub}>Configure up to 2 extra fees applied to every new bill</Text>
        </View>
        <ChevronRight size={16} color={COLORS.subtext} />
      </TouchableOpacity>

      <View style={styles.section}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: SPACING.sm }}>
          <ScrollText size={16} color={COLORS.text} />
          <Text style={styles.sectionTitle}>Recent admin activity</Text>
        </View>
        {recent.length === 0 ? (
          <Text style={styles.empty}>No activity yet.</Text>
        ) : (
          recent.map((r) => (
            <View key={r.id} style={styles.auditRow}>
              <View style={[styles.dot, { backgroundColor: r.destructive ? COLORS.danger : COLORS.primary }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.auditAction}>{r.action}</Text>
                <Text style={styles.auditMeta}>by {r.admin_email} • {new Date(r.at).toLocaleString()}</Text>
              </View>
            </View>
          ))
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text, marginBottom: 4 },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.lg },
  // P2 — default-password nudge banner
  nudgeBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    padding: SPACING.md,
    backgroundColor: COLORS.warningLight,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.warning,
    marginBottom: SPACING.md,
  },
  nudgeIcon: {
    width: 36,
    height: 36,
    borderRadius: 12,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
  },
  nudgeTitle: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold, color: COLORS.text },
  nudgeSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  nudgeCta: { color: COLORS.warning, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.bold },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.md },
  tile: { flexBasis: 230, flexGrow: 1, flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, padding: SPACING.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, minWidth: 220 },
  quickLink: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, padding: SPACING.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, marginTop: SPACING.md },
  tileIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  tileLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.medium },
  tileValue: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 2 },
  tileSub: { fontSize: 11, color: COLORS.subtext, marginTop: 2 },
  section: { marginTop: SPACING.xl, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md },
  sectionTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  empty: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic' },
  auditRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  dot: { width: 8, height: 8, borderRadius: 4 },
  auditAction: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  auditMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
});
