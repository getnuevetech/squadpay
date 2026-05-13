/**
 * /admin/capabilities — Feature on/off switches.
 *
 * Different from Access Role Management:
 *   • Access Role Management = gates ADMIN PAGES (e.g. can this admin open
 *     /admin/platform-fees).
 *   • Capabilities = gates USER-FACING FEATURES (e.g. is the Virtual Card
 *     issuing feature live for end users).
 *
 * Each capability is a row with a switch. Sensitive ones get a warning badge.
 * Toggling writes to the backend AND refreshes the in-memory cache so a
 * disabled capability immediately stops working for users.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator,
  TouchableOpacity, Alert, Switch,
} from 'react-native';
import { ShieldAlert, Layers } from 'lucide-react-native';
import { adminApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

type Capability = {
  key: string;
  label: string;
  description: string;
  group: string;
  enabled: boolean;
  sensitive: boolean;
  updated_at: string;
};

export default function CapabilitiesPage() {
  const [items, setItems] = useState<Capability[]>([]);
  const [groupOrder, setGroupOrder] = useState<string[]>(['Payments', 'Engagement', 'Communications']);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminApi.listCapabilities();
      setItems(res.items);
      setGroupOrder(res.group_order || groupOrder);
    } catch (e: any) {
      Alert.alert('Failed to load', e?.message || '');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = async (cap: Capability) => {
    const next = !cap.enabled;
    setSavingKey(cap.key);
    try {
      const updated = await adminApi.setCapability(cap.key, next);
      setItems((prev) => prev.map((c) => (c.key === cap.key ? { ...c, ...updated } : c)));
    } catch (e: any) {
      Alert.alert('Toggle failed', e?.message || '');
    } finally {
      setSavingKey(null);
    }
  };

  if (loading) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  const grouped = (g: string) => items.filter((c) => c.group === g);

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.container}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Layers size={20} color={COLORS.primary} />
        <Text style={styles.h1}>Capabilities</Text>
      </View>
      <Text style={styles.sub}>
        Turn user-facing features on or off without a deploy. Changes apply within seconds.
        Disabled features return a friendly 503 ("Coming soon") to mobile clients and the
        relevant UI is hidden on next app launch.
      </Text>

      {groupOrder.map((g) => {
        const rows = grouped(g);
        if (rows.length === 0) return null;
        return (
          <View key={g} style={styles.groupBlock}>
            <Text style={styles.groupTitle}>{g}</Text>
            {rows.map((cap) => (
              <View key={cap.key} style={styles.row} testID={`cap-row-${cap.key}`}>
                <View style={{ flex: 1, paddingRight: SPACING.md }}>
                  <View style={styles.rowHeader}>
                    <Text style={styles.rowLabel}>{cap.label}</Text>
                    {cap.sensitive ? (
                      <ShieldAlert size={12} color={COLORS.warning} />
                    ) : null}
                    <Text style={styles.rowKey}>{cap.key}</Text>
                  </View>
                  <Text style={styles.rowDesc}>{cap.description}</Text>
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  {savingKey === cap.key ? (
                    <ActivityIndicator color={COLORS.primary} />
                  ) : (
                    <Switch
                      value={cap.enabled}
                      onValueChange={() => toggle(cap)}
                      thumbColor="#fff"
                      trackColor={{ false: COLORS.border, true: COLORS.primary }}
                      testID={`cap-switch-${cap.key}`}
                    />
                  )}
                  <Text style={[styles.statusText, { color: cap.enabled ? COLORS.success : COLORS.subtext }]}>
                    {cap.enabled ? 'ENABLED' : 'DISABLED'}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  container: { padding: SPACING.lg, gap: SPACING.lg, maxWidth: 980, alignSelf: 'stretch', width: '100%' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.xl },
  h1: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  sub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, lineHeight: 19 },
  groupBlock: { gap: SPACING.sm },
  groupTitle: {
    fontSize: 11, color: COLORS.subtext, fontWeight: FONT.weights.bold,
    textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 2,
  },
  row: {
    flexDirection: 'row', alignItems: 'center',
    padding: SPACING.md, borderRadius: RADIUS.lg,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
  },
  rowHeader: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 4 },
  rowLabel: { fontSize: FONT.sizes.md, color: COLORS.text, fontWeight: FONT.weights.semibold },
  rowKey: {
    fontSize: 10, color: COLORS.subtext, marginLeft: 4,
    fontFamily: 'monospace', letterSpacing: 0.4,
  },
  rowDesc: { fontSize: FONT.sizes.xs, color: COLORS.subtext, lineHeight: 17 },
  statusText: { fontSize: 9, fontWeight: FONT.weights.bold, marginTop: 4, letterSpacing: 0.5 },
});
