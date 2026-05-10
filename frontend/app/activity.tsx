/**
 * Activity stub screen — placeholder for the new IA Activity tab.
 * Pulls the user's groups and shows them as a single chronological feed.
 * If the user has no activity, gracefully invites them to start one.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Receipt, ArrowLeft, ChevronRight, Sparkles } from 'lucide-react-native';
import { api } from '../src/api';
import { refreshUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';
import { StatusBadge } from '../src/StatusBadge';
import { BottomTabBar } from '../src/components/redesign/BottomTabBar';
import { SquadPayMark } from '../src/components/redesign/SquadPayMark';
import { EmptyState } from '../src/components/EmptyState';

export default function ActivityScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [groups, setGroups] = useState<any[]>([]);

  const load = useCallback(async () => {
    const u = await refreshUser();
    if (!u) {
      router.replace('/');
      return;
    }
    try {
      const gs = await api.getUserGroups(u.id);
      setGroups(gs);
    } catch {}
    setLoading(false);
  }, [router]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']} testID="activity-screen">
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.replace('/')} style={styles.iconBtn} activeOpacity={0.7} testID="activity-home-btn">
          <ArrowLeft size={20} color={COLORS.text} />
        </TouchableOpacity>
        <SquadPayMark size={28} />
        <View style={{ width: 40 }} />
      </View>
      <Text style={styles.heading}>Activity</Text>
      <Text style={styles.subheading}>All your splits, in one place.</Text>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>
      ) : groups.length === 0 ? (
        <View style={{ padding: SPACING.lg }}>
          <EmptyState
            icon={<Sparkles color={COLORS.primary} size={36} />}
            title="Nothing here yet"
            subtitle="Splits you create or join will show up here."
            cta={{ label: 'Split a bill', onPress: () => router.push('/create') }}
          />
        </View>
      ) : (
        <FlatList
          data={groups}
          keyExtractor={(g) => g.id}
          contentContainerStyle={{ padding: SPACING.md, paddingBottom: 110 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
          renderItem={({ item }) => (
            <TouchableOpacity
              style={styles.row}
              activeOpacity={0.85}
              onPress={() => router.push(`/group/${item.id}/dashboard`)}
              testID={`activity-row-${item.id}`}
            >
              <View style={styles.rowIcon}>
                <Receipt color={COLORS.primary} size={18} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle} numberOfLines={1}>{item.title}</Text>
                <Text style={styles.rowMeta}>
                  {item.member_count} members · ${Number(item.total || 0).toFixed(2)} · {new Date(item.created_at).toLocaleDateString()}
                </Text>
              </View>
              <StatusBadge
                status={(item as any).derived_status || (item.status === 'closed' ? 'settled' : item.status === 'paid' ? 'repaying' : 'contributing')}
              />
              <ChevronRight color={COLORS.subtext} size={16} />
            </TouchableOpacity>
          )}
        />
      )}
      <BottomTabBar active="activity" />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: SPACING.md, paddingTop: SPACING.sm },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: 28, fontWeight: FONT.weights.bold, color: COLORS.text, paddingHorizontal: SPACING.md, marginTop: SPACING.md, letterSpacing: -0.5 },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, paddingHorizontal: SPACING.md, marginTop: 4, marginBottom: SPACING.md },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.sm,
  },
  rowIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: COLORS.primaryLight, alignItems: 'center', justifyContent: 'center' },
  rowTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  rowMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
});
