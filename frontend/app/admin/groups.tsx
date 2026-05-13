import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { Search, Ban, ChevronRight, Filter, Receipt } from 'lucide-react-native';
import { adminApi, AdminGroupRow } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { formatSid } from '../../src/ids';

type StatusFilter = 'all' | 'open' | 'paid' | 'closed' | 'blocked';

const PAGE_SIZE = 25;

function statusBadgeColor(status: string, blocked: boolean) {
  if (blocked) return { bg: COLORS.dangerLight, fg: COLORS.danger };
  if (status === 'open') return { bg: COLORS.warningLight, fg: COLORS.warning };
  if (status === 'paid') return { bg: COLORS.primaryLight, fg: COLORS.primary };
  if (status === 'closed') return { bg: COLORS.successLight, fg: COLORS.success };
  return { bg: COLORS.disabledBg, fg: COLORS.subtext };
}

export default function AdminGroupsList() {
  const router = useRouter();
  const [items, setItems] = useState<AdminGroupRow[]>([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(true);
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<StatusFilter>('all');
  // June 2025 deploy prep — paginate the squads table.
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const params: any = {
        limit: PAGE_SIZE,
        skip: (page - 1) * PAGE_SIZE,
        q: q || undefined,
      };
      if (filter === 'open' || filter === 'paid' || filter === 'closed') params.status = filter;
      if (filter === 'blocked') params.blocked = true;
      const r = await adminApi.listGroups(params);
      setItems(r.items);
      setTotal(r.total);
    } finally { setBusy(false); }
  }, [q, filter, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [q, filter]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="admin-groups-heading">Groups</Text>
      <Text style={styles.subheading}>{total} total • search by title or invite code.</Text>

      <View style={styles.searchRow}>
        <View style={styles.searchBox}>
          <Search size={16} color={COLORS.subtext} />
          <TextInput
            style={styles.searchInput}
            placeholder="Search title or code…"
            placeholderTextColor={COLORS.disabledText}
            value={q}
            onChangeText={setQ}
            onSubmitEditing={load}
            returnKeyType="search"
            testID="admin-groups-search"
          />
        </View>
        <TouchableOpacity onPress={load} style={styles.searchBtn} activeOpacity={0.85} testID="admin-groups-refresh">
          <Text style={{ color: '#fff', fontWeight: FONT.weights.semibold }}>Apply</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.filterRow}>
        <Filter size={14} color={COLORS.subtext} />
        {(['all','open','paid','closed','blocked'] as StatusFilter[]).map((f) => (
          <TouchableOpacity
            key={f}
            onPress={() => setFilter(f)}
            style={[styles.chip, filter === f && styles.chipActive]}
            activeOpacity={0.85}
            testID={`admin-groups-filter-${f}`}
          >
            <Text style={[styles.chipText, filter === f && { color: '#fff' }]}>{f}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {busy ? <ActivityIndicator color={COLORS.primary} style={{ marginTop: 24 }} /> : null}
      {!busy && items.length === 0 ? <Text style={styles.empty}>No squads match.</Text> : null}

      {items.map((g) => {
        const c = statusBadgeColor(g.status, g.is_blocked);
        return (
          <TouchableOpacity
            key={g.id}
            onPress={() => router.push(`/admin/groups/${g.id}` as any)}
            activeOpacity={0.85}
            style={styles.row}
            testID={`admin-groups-row-${g.id}`}
          >
            <View style={[styles.iconBox, g.is_blocked && { backgroundColor: COLORS.dangerLight }]}>
              <Receipt size={18} color={g.is_blocked ? COLORS.danger : COLORS.primary} />
            </View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <Text style={styles.title} numberOfLines={1}>{g.title || 'Untitled'}</Text>
                <View style={[styles.badge, { backgroundColor: c.bg }]}>
                  <Text style={[styles.badgeText, { color: c.fg }]}>{g.is_blocked ? 'BLOCKED' : g.status?.toUpperCase()}</Text>
                </View>
              </View>
              <Text style={styles.meta}>{g.code} • lead {g.lead_name || '—'} • {g.members_count} Squad members</Text>
              <Text style={styles.sidLine} testID={`admin-groups-sid-${g.id}`} selectable>
                {formatSid(g.id)}
              </Text>
              <Text style={styles.metaSmall}>${(g.total_amount || 0).toFixed(2)} total • ${(g.contributions_total || 0).toFixed(2)} collected • {new Date(g.created_at).toLocaleDateString()}</Text>
            </View>
            <ChevronRight size={16} color={COLORS.subtext} />
          </TouchableOpacity>
        );
      })}

      {/* Pagination footer */}
      {total > PAGE_SIZE ? (
        <View style={styles.pagination} testID="admin-groups-pagination">
          <TouchableOpacity
            onPress={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || busy}
            style={[styles.pageBtn, (page <= 1 || busy) && styles.pageBtnDisabled]}
            activeOpacity={0.85}
            testID="admin-groups-page-prev"
          >
            <Text style={styles.pageBtnText}>Prev</Text>
          </TouchableOpacity>
          <Text style={styles.pageInfo}>
            Page {page} of {totalPages}
          </Text>
          <TouchableOpacity
            onPress={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || busy}
            style={[styles.pageBtn, (page >= totalPages || busy) && styles.pageBtnDisabled]}
            activeOpacity={0.85}
            testID="admin-groups-page-next"
          >
            <Text style={styles.pageBtnText}>Next</Text>
          </TouchableOpacity>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.md },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginBottom: SPACING.sm },
  searchBox: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: SPACING.md, height: 40, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  searchInput: { flex: 1, color: COLORS.text, height: 40, outlineStyle: 'none' as any },
  searchBtn: { paddingHorizontal: SPACING.md, height: 40, borderRadius: RADIUS.md, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  filterRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: SPACING.md, flexWrap: 'wrap' },
  chip: { paddingHorizontal: SPACING.md, paddingVertical: 6, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { color: COLORS.subtext, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold, textTransform: 'capitalize' },
  empty: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic', marginTop: 24 },
  row: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, paddingVertical: 12, paddingHorizontal: SPACING.md, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, marginBottom: 8 },
  iconBox: { width: 36, height: 36, borderRadius: 18, backgroundColor: COLORS.primaryLight, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  badge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  badgeText: { fontSize: 10, fontWeight: FONT.weights.bold, letterSpacing: 0.4 },
  meta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  metaSmall: { fontSize: 11, color: COLORS.subtext, marginTop: 2 },
  sidLine: {
    fontSize: 11,
    color: COLORS.subtext,
    marginTop: 2,
    fontFamily: 'monospace',
    letterSpacing: 0.6,
  },
  pagination: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACING.md,
    paddingVertical: SPACING.md,
  },
  pageBtn: {
    paddingHorizontal: SPACING.md,
    paddingVertical: 8,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
    minWidth: 70,
    alignItems: 'center',
  },
  pageBtnDisabled: { opacity: 0.4 },
  pageBtnText: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  pageInfo: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
});
