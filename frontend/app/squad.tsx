/**
 * Squad stub screen — a friendly directory of people the user has split with
 * (collected from their groups), plus an invite-friends CTA. Replaces the
 * Squad bottom tab destination.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  ActivityIndicator,
  FlatList,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { ArrowLeft, UserPlus, Users as UsersIcon, ChevronDown } from 'lucide-react-native';
import { api } from '../src/api';
import { refreshUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';
import { AvatarRing } from '../src/components/AvatarRing';
import { BottomTabBar } from '../src/components/redesign/BottomTabBar';
import { SquadPayMark } from '../src/components/redesign/SquadPayMark';
import { EmptyState } from '../src/components/EmptyState';

type Person = { user_id: string; name: string; groups: { id: string; title: string }[] };

export default function SquadScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [people, setPeople] = useState<Person[]>([]);
  const [me, setMe] = useState<{ id: string; name: string } | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    const u = await refreshUser();
    if (!u) {
      router.replace('/');
      return;
    }
    setMe(u);
    try {
      const groups = await api.getUserGroups(u.id);
      const map = new Map<string, Person>();
      for (const g of groups) {
        const preview = (g as any).members_preview || [];
        for (const m of preview) {
          if (!m.user_id || m.user_id === u.id) continue;
          const existing = map.get(m.user_id);
          const groupRef = { id: g.id, title: g.title || 'Bill' };
          if (existing) existing.groups.push(groupRef);
          else map.set(m.user_id, { user_id: m.user_id, name: m.name || 'Member', groups: [groupRef] });
        }
      }
      const list = Array.from(map.values()).sort((a, b) => b.groups.length - a.groups.length);
      setPeople(list);
    } catch {}
    setLoading(false);
  }, [router]);

  useEffect(() => { load(); }, [load]);

  return (
    <SafeAreaView style={styles.container} edges={['top']} testID="squad-screen">
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.replace('/')} style={styles.iconBtn} activeOpacity={0.7} testID="squad-home-btn">
          <ArrowLeft size={20} color={COLORS.text} />
        </TouchableOpacity>
        <SquadPayMark size={28} />
        <View style={{ width: 40 }} />
      </View>
      <Text style={styles.heading}>Your squad</Text>
      <Text style={styles.subheading}>People you've split with most.</Text>

      <TouchableOpacity
        onPress={() => router.push('/invite')}
        style={styles.inviteBanner}
        activeOpacity={0.85}
        testID="squad-invite-cta"
      >
        <View style={styles.inviteIcon}>
          <UserPlus color={COLORS.primary} size={18} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.inviteTitle}>Invite friends to SquadPay</Text>
          <Text style={styles.inviteSub}>They get bonus credits when they sign up.</Text>
        </View>
      </TouchableOpacity>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>
      ) : people.length === 0 ? (
        <View style={{ paddingHorizontal: SPACING.md }}>
          <EmptyState
            icon={<UsersIcon color={COLORS.primary} size={36} />}
            title="No squad members yet"
            subtitle="Start a split to add people you frequently pay with."
            cta={{ label: 'Split a bill', onPress: () => router.push('/create') }}
          />
        </View>
      ) : (
        <FlatList
          data={people}
          keyExtractor={(p) => p.user_id}
          contentContainerStyle={{ padding: SPACING.md, paddingBottom: 110 }}
          renderItem={({ item }) => {
            const isOpen = !!expanded[item.user_id];
            return (
              <View style={styles.row}>
                <TouchableOpacity
                  style={styles.rowHeader}
                  activeOpacity={0.7}
                  onPress={() => setExpanded((m) => ({ ...m, [item.user_id]: !isOpen }))}
                  testID={`squad-row-${item.user_id}`}
                >
                  <AvatarRing name={item.name} seed={item.user_id} size={42} />
                  <View style={{ flex: 1, marginLeft: 12 }}>
                    <Text style={styles.rowName}>{item.name}</Text>
                    <Text style={styles.rowMeta}>
                      {item.groups.length} shared {item.groups.length === 1 ? 'split' : 'splits'}
                      {item.groups.length > 0 ? ` · ${item.groups[0].title}${item.groups.length > 1 ? ` +${item.groups.length - 1}` : ''}` : ''}
                    </Text>
                  </View>
                  <View style={[isOpen && { transform: [{ rotate: '180deg' }] }]}>
                    <ChevronDown size={18} color={COLORS.subtext} />
                  </View>
                </TouchableOpacity>
                {isOpen && (
                  <View style={styles.rowGroups}>
                    {item.groups.map((gr, i) => (
                      <TouchableOpacity
                        key={gr.id + i}
                        style={styles.groupChip}
                        activeOpacity={0.85}
                        onPress={() => router.push(`/group/${gr.id}/summary`)}
                        testID={`squad-group-chip-${gr.id}`}
                      >
                        <Text style={styles.groupChipText} numberOfLines={1}>{gr.title}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                )}
              </View>
            );
          }}
        />
      )}
      <BottomTabBar active="settings" />
      {/* June 2026 — Squad is no longer a primary tab. When reached via the
          "Friends & Squad" row in Settings, highlight the Settings tab as
          the breadcrumb. */}
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
  inviteBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: SPACING.md,
    backgroundColor: COLORS.primaryLight,
    borderRadius: RADIUS.lg,
    marginHorizontal: SPACING.md,
    marginBottom: SPACING.md,
    borderWidth: 1,
    borderColor: '#E0D5FB',
  },
  inviteIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  inviteTitle: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold, color: COLORS.primary },
  inviteSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  row: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.sm,
    overflow: 'hidden',
  },
  rowHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: SPACING.md,
    gap: 4,
  },
  rowGroups: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    paddingHorizontal: SPACING.md,
    paddingBottom: SPACING.md,
    paddingTop: 0,
  },
  groupChip: {
    backgroundColor: COLORS.primaryLight,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
    maxWidth: '100%',
  },
  groupChipText: {
    color: COLORS.primary,
    fontSize: FONT.sizes.xs,
    fontWeight: FONT.weights.semibold,
  },
  rowName: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  rowMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
});
