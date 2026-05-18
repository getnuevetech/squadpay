import { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  ScrollView,
  TextInput,
  StyleSheet,
  ActivityIndicator,
  TouchableOpacity,
  Alert,
  Platform,
} from 'react-native';
import { adminApi, AuditEntry } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { formatUid, formatSid } from '../../src/ids';
import { Download, Filter as FilterIcon, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react-native';
import { toast } from '../../src/components/Toast';

const PAGE_SIZE = 50;

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
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0); // 0-indexed
  const [busy, setBusy] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Filters
  const [filterAction, setFilterAction] = useState('');
  const [filterAdmin, setFilterAdmin] = useState('');
  const [filterTargetType, setFilterTargetType] = useState('');
  const [filterDateFrom, setFilterDateFrom] = useState(''); // YYYY-MM-DD
  const [filterDateTo, setFilterDateTo] = useState('');
  const [filterDestructive, setFilterDestructive] = useState<'all' | 'true' | 'false'>('all');

  const params = useCallback(() => {
    return {
      action: filterAction || undefined,
      admin_email: filterAdmin || undefined,
      target_type: filterTargetType || undefined,
      // Pad date to ISO start/end of day so the server-side $gte/$lte hit the
      // full calendar day rather than just midnight.
      date_from: filterDateFrom ? `${filterDateFrom}T00:00:00.000Z` : undefined,
      date_to: filterDateTo ? `${filterDateTo}T23:59:59.999Z` : undefined,
      destructive: filterDestructive === 'all' ? undefined : filterDestructive === 'true',
    };
  }, [filterAction, filterAdmin, filterTargetType, filterDateFrom, filterDateTo, filterDestructive]);

  const load = useCallback(async (nextPage = page) => {
    setBusy(true);
    try {
      const r = await adminApi.auditLog({
        limit: PAGE_SIZE,
        skip: nextPage * PAGE_SIZE,
        ...params(),
      });
      setItems(r.items);
      setTotal(r.total);
      setPage(nextPage);
    } catch (e: any) {
      Alert.alert('Error', e?.message || 'Failed to load audit log');
    } finally {
      setBusy(false);
    }
  }, [page, params]);

  useEffect(() => { load(0); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const onApplyFilters = () => load(0);
  const onClearFilters = () => {
    setFilterAction('');
    setFilterAdmin('');
    setFilterTargetType('');
    setFilterDateFrom('');
    setFilterDateTo('');
    setFilterDestructive('all');
    setTimeout(() => load(0), 0);
  };

  const onDownloadCsv = async () => {
    setDownloading(true);
    try {
      const r = await adminApi.downloadAuditCsv(params());
      if (Platform.OS === 'web') {
        toast.success(`Downloaded ${r.filename}`);
      } else {
        Alert.alert('CSV ready', `${r.filename} (${r.size} bytes). On mobile, please download from the admin web console.`);
      }
    } catch (e: any) {
      Alert.alert('Download failed', e?.message || 'Could not export audit log');
    } finally {
      setDownloading(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.heading} testID="admin-audit-heading">Audit log</Text>
          <Text style={styles.subheading}>Every administrative action is recorded immutably.</Text>
        </View>
        <TouchableOpacity
          onPress={onDownloadCsv}
          disabled={downloading}
          style={[styles.iconBtn, { backgroundColor: COLORS.success }]}
          testID="admin-audit-download"
        >
          {downloading ? <ActivityIndicator color="#fff" size="small" /> : <Download size={14} color="#fff" />}
          <Text style={styles.iconBtnText}>{downloading ? 'Exporting…' : 'CSV'}</Text>
        </TouchableOpacity>
      </View>

      {/* Filter toggle + summary */}
      <View style={styles.filterHeader}>
        <TouchableOpacity
          onPress={() => setFiltersOpen((v) => !v)}
          style={styles.filterToggle}
          testID="admin-audit-filter-toggle"
        >
          <FilterIcon size={14} color={COLORS.primary} />
          <Text style={styles.filterToggleText}>{filtersOpen ? 'Hide filters' : 'Show filters'}</Text>
        </TouchableOpacity>
        <Text style={styles.totalChip}>{total} entries</Text>
        <TouchableOpacity onPress={() => load(0)} style={styles.refreshChip} testID="admin-audit-refresh">
          <RefreshCw size={12} color={COLORS.subtext} />
          <Text style={styles.refreshChipText}>Refresh</Text>
        </TouchableOpacity>
      </View>

      {filtersOpen && (
        <View style={styles.filterCard}>
          <View style={styles.filterField}>
            <Text style={styles.filterLabel}>Action contains</Text>
            <TextInput
              style={styles.filterInput}
              placeholder="e.g. block, login, grant"
              placeholderTextColor={COLORS.disabledText}
              value={filterAction}
              onChangeText={setFilterAction}
              testID="admin-audit-filter-action"
            />
          </View>
          <View style={styles.filterField}>
            <Text style={styles.filterLabel}>Admin email</Text>
            <TextInput
              style={styles.filterInput}
              placeholder="admin@getsquadpay.com"
              placeholderTextColor={COLORS.disabledText}
              value={filterAdmin}
              onChangeText={setFilterAdmin}
              autoCapitalize="none"
              testID="admin-audit-filter-email"
            />
          </View>
          <View style={styles.filterField}>
            <Text style={styles.filterLabel}>Target type</Text>
            <View style={styles.chipsRow}>
              {['', 'user', 'group', 'admin', 'settings'].map((t) => (
                <TouchableOpacity
                  key={t || 'any'}
                  onPress={() => setFilterTargetType(t)}
                  style={[styles.chip, filterTargetType === t && styles.chipActive]}
                  testID={`admin-audit-target-${t || 'any'}`}
                >
                  <Text style={[styles.chipText, filterTargetType === t && styles.chipTextActive]}>
                    {t || 'Any'}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
          <View style={styles.filterRowSplit}>
            <View style={[styles.filterField, { flex: 1 }]}>
              <Text style={styles.filterLabel}>From (YYYY-MM-DD)</Text>
              <TextInput
                style={styles.filterInput}
                placeholder="2025-01-01"
                placeholderTextColor={COLORS.disabledText}
                value={filterDateFrom}
                onChangeText={setFilterDateFrom}
                testID="admin-audit-date-from"
              />
            </View>
            <View style={[styles.filterField, { flex: 1 }]}>
              <Text style={styles.filterLabel}>To (YYYY-MM-DD)</Text>
              <TextInput
                style={styles.filterInput}
                placeholder="2025-12-31"
                placeholderTextColor={COLORS.disabledText}
                value={filterDateTo}
                onChangeText={setFilterDateTo}
                testID="admin-audit-date-to"
              />
            </View>
          </View>
          <View style={styles.filterField}>
            <Text style={styles.filterLabel}>Destructive only</Text>
            <View style={styles.chipsRow}>
              {(['all', 'true', 'false'] as const).map((v) => (
                <TouchableOpacity
                  key={v}
                  onPress={() => setFilterDestructive(v)}
                  style={[styles.chip, filterDestructive === v && styles.chipActive]}
                  testID={`admin-audit-destructive-${v}`}
                >
                  <Text style={[styles.chipText, filterDestructive === v && styles.chipTextActive]}>
                    {v === 'all' ? 'All' : v === 'true' ? 'Destructive' : 'Non-destructive'}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
          <View style={styles.filterButtonsRow}>
            <TouchableOpacity onPress={onApplyFilters} style={[styles.applyBtn]} testID="admin-audit-apply">
              <Text style={styles.applyBtnText}>Apply filters</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={onClearFilters} style={[styles.clearBtn]} testID="admin-audit-clear">
              <Text style={styles.clearBtnText}>Clear</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

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

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <View style={styles.pageBar}>
          <TouchableOpacity
            disabled={page === 0 || busy}
            onPress={() => load(Math.max(0, page - 1))}
            style={[styles.pageBtn, (page === 0 || busy) && { opacity: 0.4 }]}
            testID="admin-audit-prev"
          >
            <ChevronLeft size={14} color={COLORS.text} />
            <Text style={styles.pageBtnText}>Prev</Text>
          </TouchableOpacity>
          <Text style={styles.pageMeta}>
            Page {page + 1} of {totalPages} · showing {items.length} of {total}
          </Text>
          <TouchableOpacity
            disabled={page + 1 >= totalPages || busy}
            onPress={() => load(page + 1)}
            style={[styles.pageBtn, (page + 1 >= totalPages || busy) && { opacity: 0.4 }]}
            testID="admin-audit-next"
          >
            <Text style={styles.pageBtnText}>Next</Text>
            <ChevronRight size={14} color={COLORS.text} />
          </TouchableOpacity>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: SPACING.sm, gap: SPACING.sm },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.md, marginTop: 2 },
  iconBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, height: 36, borderRadius: RADIUS.md },
  iconBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs },
  filterHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginBottom: SPACING.sm, flexWrap: 'wrap' },
  filterToggle: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, height: 32, borderRadius: RADIUS.pill, backgroundColor: COLORS.primaryLight, borderWidth: 1, borderColor: COLORS.primary },
  filterToggleText: { color: COLORS.primary, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.xs },
  totalChip: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.medium },
  refreshChip: { flexDirection: 'row', alignItems: 'center', gap: 4, marginLeft: 'auto', paddingHorizontal: 10, height: 28, borderRadius: RADIUS.pill, backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border },
  refreshChipText: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold },
  filterCard: { padding: SPACING.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, marginBottom: SPACING.md, gap: SPACING.sm },
  filterField: { gap: 6 },
  filterLabel: { fontSize: 10, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.semibold, letterSpacing: 0.5 },
  filterInput: { height: 38, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.bg, fontSize: FONT.sizes.sm },
  filterRowSplit: { flexDirection: 'row', gap: SPACING.sm },
  chipsRow: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  chip: { paddingHorizontal: 10, height: 28, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.bg, alignItems: 'center', justifyContent: 'center' },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.medium },
  chipTextActive: { color: '#fff' },
  filterButtonsRow: { flexDirection: 'row', gap: SPACING.sm, marginTop: 6 },
  applyBtn: { flex: 1, height: 38, borderRadius: RADIUS.md, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  applyBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  clearBtn: { height: 38, paddingHorizontal: SPACING.md, borderRadius: RADIUS.md, backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border, alignItems: 'center', justifyContent: 'center' },
  clearBtnText: { color: COLORS.subtext, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  empty: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic', marginTop: 24 },
  row: { flexDirection: 'row', gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  action: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  meta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  target: { fontSize: 11, color: COLORS.subtext, marginTop: 2, fontFamily: 'monospace', letterSpacing: 0.5 },
  payload: { fontSize: 11, color: COLORS.subtext, marginTop: 4, fontFamily: 'monospace' },
  pageBar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: SPACING.md, padding: SPACING.sm, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md },
  pageBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 12, height: 34, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.bg },
  pageBtnText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.semibold },
  pageMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext },
});
