import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { Search, Ban, ShieldCheck, ChevronRight, Filter, FileCheck2 } from 'lucide-react-native';
import { adminApi, AdminUserRow } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

type FilterMode = 'all' | 'verified' | 'unverified' | 'blocked';

const PAGE_SIZE = 25;

export default function AdminUsersList() {
  const router = useRouter();
  const [items, setItems] = useState<AdminUserRow[]>([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(true);
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<FilterMode>('all');
  // June 2025 deploy prep — paginate the users table. Backend already
  // supports `skip`/`limit`; we just expose Prev/Next controls.
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const params: any = {
        limit: PAGE_SIZE,
        skip: (page - 1) * PAGE_SIZE,
        q: q || undefined,
      };
      if (filter === 'verified') params.verified = true;
      if (filter === 'unverified') params.verified = false;
      if (filter === 'blocked') params.blocked = true;
      const r = await adminApi.listUsers(params);
      setItems(r.items);
      setTotal(r.total);
    } catch (e) { /* swallow; banner could be added */ }
    finally { setBusy(false); }
  }, [q, filter, page]);

  useEffect(() => { load(); }, [load]);
  // Reset to page 1 whenever the search/filter changes.
  useEffect(() => { setPage(1); }, [q, filter]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="admin-users-heading">Users</Text>
      <Text style={styles.subheading}>{total} total • search by name or phone. Persistent identities are matched by phone number.</Text>

      <View style={styles.searchRow}>
        <View style={styles.searchBox}>
          <Search size={16} color={COLORS.subtext} />
          <TextInput
            style={styles.searchInput}
            placeholder="Search name or phone…"
            placeholderTextColor={COLORS.disabledText}
            value={q}
            onChangeText={setQ}
            onSubmitEditing={load}
            returnKeyType="search"
            testID="admin-users-search"
          />
        </View>
        <TouchableOpacity onPress={load} style={styles.searchBtn} activeOpacity={0.85} testID="admin-users-refresh">
          <Text style={{ color: '#fff', fontWeight: FONT.weights.semibold }}>Apply</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.filterRow}>
        <Filter size={14} color={COLORS.subtext} />
        {(['all','verified','unverified','blocked'] as FilterMode[]).map((f) => (
          <TouchableOpacity
            key={f}
            onPress={() => setFilter(f)}
            style={[styles.chip, filter === f && styles.chipActive]}
            activeOpacity={0.85}
            testID={`admin-users-filter-${f}`}
          >
            <Text style={[styles.chipText, filter === f && { color: '#fff' }]}>{f}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {busy ? <ActivityIndicator color={COLORS.primary} style={{ marginTop: 24 }} /> : null}
      {!busy && items.length === 0 ? <Text style={styles.empty}>No users match.</Text> : null}

      {items.map((u) => (
        <TouchableOpacity
          key={u.id}
          onPress={() => router.push(`/admin/users/${u.id}` as any)}
          activeOpacity={0.85}
          style={styles.row}
          testID={`admin-users-row-${u.id}`}
        >
          <View style={[styles.avatar, u.is_blocked && { backgroundColor: COLORS.dangerLight }]}>
            <Text style={[styles.avatarText, u.is_blocked && { color: COLORS.danger }]}>{(u.name || '?').slice(0, 1).toUpperCase()}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <Text style={styles.name} numberOfLines={1}>{u.name || '—'}</Text>
              {u.verified ? <ShieldCheck size={12} color={COLORS.success} /> : null}
              {u.terms_accepted_at ? (
                <FileCheck2
                  size={12}
                  color={COLORS.success}
                  testID={`admin-users-terms-${u.id}`}
                />
              ) : null}
              {u.is_blocked ? (
                <View style={styles.blockedBadge}><Ban size={10} color={COLORS.danger} /><Text style={styles.blockedBadgeText}>Blocked</Text></View>
              ) : null}
            </View>
            <Text style={styles.meta}>{u.phone || 'no phone'}</Text>
            <Text style={styles.metaSmall}>led {u.groups_led} • joined {u.groups_joined} • ${u.total_billed_as_lead.toFixed(2)} billed</Text>
          </View>
          <ChevronRight size={16} color={COLORS.subtext} />
        </TouchableOpacity>
      ))}

      {/* Pagination footer */}
      {total > PAGE_SIZE ? (
        <View style={styles.pagination} testID="admin-users-pagination">
          <TouchableOpacity
            onPress={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || busy}
            style={[styles.pageBtn, (page <= 1 || busy) && styles.pageBtnDisabled]}
            activeOpacity={0.85}
            testID="admin-users-page-prev"
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
            testID="admin-users-page-next"
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
  row: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, paddingVertical: 12, paddingHorizontal: SPACING.md, borderBottomWidth: 1, borderBottomColor: COLORS.border, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, marginBottom: 8, borderWidth: 1 },
  avatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: COLORS.primaryLight, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: COLORS.primary, fontWeight: FONT.weights.bold },
  name: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  meta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  metaSmall: { fontSize: 11, color: COLORS.subtext, marginTop: 2 },
  blockedBadge: { flexDirection: 'row', alignItems: 'center', gap: 3, backgroundColor: COLORS.dangerLight, paddingHorizontal: 6, paddingVertical: 2, borderRadius: RADIUS.pill },
  blockedBadgeText: { fontSize: 10, color: COLORS.danger, fontWeight: FONT.weights.bold },
  // Pagination footer — used on /admin/users, /admin/groups, /admin/notifications.
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
