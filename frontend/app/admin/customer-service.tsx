/**
 * Admin → Customer Service (June 2025).
 *
 * Lists Contact Us tickets paginated + filterable + with an inline detail
 * pane that lets the CS rep change status and append internal notes.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Inbox, Filter, Send, CheckCircle2, Clock } from 'lucide-react-native';
import { adminApi, ticketsApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';
import { Alert } from 'react-native';

const STATUS_OPTS = ['', 'new', 'open', 'resolved', 'closed'] as const;
const SUBJECT_OPTS = ['', 'general_enquiry', 'technical_support', 'account_refund', 'others'] as const;

const SUBJECT_LABEL: Record<string, string> = {
  general_enquiry: 'General Enquiry',
  technical_support: 'Technical Support',
  account_refund: 'Account & Refund',
  others: 'Others',
};

export default function AdminCustomerServiceScreen() {
  const [items, setItems] = useState<any[]>([]);
  const [counters, setCounters] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<string>('');
  const [subject, setSubject] = useState<string>('');
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<any | null>(null);
  const [note, setNote] = useState('');
  const [reply, setReply] = useState('');
  const [replying, setReplying] = useState(false);
  const PAGE = 25;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await adminApi.listContactMessages(page, PAGE, { status: status || undefined, subject: subject || undefined, q: q || undefined });
      setItems(r.items || []);
      setCounters(r.counters || {});
      setTotal(r.total || 0);
    } finally {
      setLoading(false);
    }
  }, [page, status, subject, q]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [status, subject, q]);

  const openTicket = async (id: string) => {
    try {
      const r = await adminApi.getContactMessage(id);
      setSelected(r);
      setNote('');
    } catch {}
  };

  const changeStatus = async (newStatus: string) => {
    if (!selected) return;
    try {
      const r = await adminApi.patchContactMessage(selected.id, { status: newStatus });
      setSelected(r);
      await load();
    } catch {}
  };

  const submitNote = async () => {
    if (!selected || !note.trim()) return;
    try {
      const r = await adminApi.addContactNote(selected.id, note.trim());
      setSelected(r);
      setNote('');
    } catch {}
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE));
  const statusPill = (s: string) => {
    const map: Record<string, { bg: string; fg: string }> = {
      new: { bg: COLORS.warningLight, fg: COLORS.warning },
      open: { bg: COLORS.primaryLight, fg: COLORS.primary },
      resolved: { bg: COLORS.successLight, fg: COLORS.success },
      closed: { bg: COLORS.disabledBg, fg: COLORS.subtext },
    };
    return map[s] || { bg: COLORS.disabledBg, fg: COLORS.subtext };
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: COLORS.bg }} edges={['bottom']}>
      <ScrollView contentContainerStyle={{ padding: SPACING.lg, gap: SPACING.md }}>
        <Text style={styles.h1}>Customer Service</Text>
        <Text style={styles.subtle}>Tickets submitted from the in-app Contact Us form. A copy of each ticket is also emailed to help@getsquadpay.com.</Text>

        {/* Counters row */}
        <View style={styles.countersRow}>
          {(['new','open','resolved','closed'] as const).map((s) => {
            const p = statusPill(s);
            return (
              <TouchableOpacity
                key={s}
                onPress={() => setStatus(status === s ? '' : s)}
                style={[styles.counterTile, { backgroundColor: p.bg }, status === s && { borderWidth: 1.5, borderColor: p.fg }]}
                activeOpacity={0.85}
                testID={`cs-counter-${s}`}
              >
                <Text style={[styles.counterLabel, { color: p.fg }]}>{s.toUpperCase()}</Text>
                <Text style={[styles.counterAmt, { color: p.fg }]}>{counters[s] || 0}</Text>
              </TouchableOpacity>
            );
          })}
        </View>

        {/* Filters */}
        <View style={styles.filterRow}>
          <TextInput value={q} onChangeText={setQ} placeholder="Search name / email / message" placeholderTextColor={COLORS.disabledText} style={[styles.input, { flex: 1 }]} />
          <View style={[styles.chipRow, { flex: 1 }]}>
            {SUBJECT_OPTS.map((opt) => (
              <TouchableOpacity
                key={opt}
                onPress={() => setSubject(subject === opt ? '' : opt)}
                style={[styles.chip, subject === opt && styles.chipActive]}
                activeOpacity={0.85}
              >
                <Text style={[styles.chipText, subject === opt && styles.chipTextActive]}>{opt ? SUBJECT_LABEL[opt] : 'All'}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* List */}
        {loading ? (
          <ActivityIndicator color={COLORS.primary} />
        ) : items.length === 0 ? (
          <View style={{ alignItems: 'center', padding: SPACING.lg, gap: SPACING.sm }}>
            <Inbox size={42} color={COLORS.border} />
            <Text style={{ color: COLORS.subtext, fontSize: FONT.sizes.sm }}>No tickets yet.</Text>
          </View>
        ) : (
          items.map((t) => {
            const p = statusPill(t.status);
            return (
              <TouchableOpacity
                key={t.id} onPress={() => openTicket(t.id)} activeOpacity={0.85}
                style={[styles.row, selected?.id === t.id && { borderColor: COLORS.primary, borderWidth: 1.5 }]}
                testID={`cs-row-${t.id}`}
              >
                <View style={{ flex: 1, gap: 4 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <Text style={styles.rowName}>{t.name}</Text>
                    <View style={[styles.statusPill, { backgroundColor: p.bg }]}>
                      <Text style={[styles.statusPillText, { color: p.fg }]}>{t.status}</Text>
                    </View>
                    <Text style={styles.rowSubject}>{t.subject_label || SUBJECT_LABEL[t.subject]}</Text>
                  </View>
                  <Text style={styles.rowEmail}>{t.email}</Text>
                  <Text style={styles.rowMsg} numberOfLines={2}>{t.message}</Text>
                  <Text style={styles.rowDate}>{new Date(t.created_at).toLocaleString()} · {t.id}</Text>
                </View>
              </TouchableOpacity>
            );
          })
        )}

        {/* Pagination */}
        {total > PAGE ? (
          <View style={styles.pager}>
            <TouchableOpacity onPress={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1 || loading} style={[styles.pageBtn, (page <= 1 || loading) && { opacity: 0.4 }]} activeOpacity={0.85}>
              <Text style={styles.pageBtnText}>Prev</Text>
            </TouchableOpacity>
            <Text style={styles.pageInfo}>Page {page} of {totalPages}</Text>
            <TouchableOpacity onPress={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages || loading} style={[styles.pageBtn, (page >= totalPages || loading) && { opacity: 0.4 }]} activeOpacity={0.85}>
              <Text style={styles.pageBtnText}>Next</Text>
            </TouchableOpacity>
          </View>
        ) : null}

        {/* Detail pane */}
        {selected ? (
          <View style={styles.detail} testID="cs-detail">
            <Text style={styles.detailTitle}>Ticket {selected.id}</Text>
            <Text style={styles.detailMeta}>{selected.name} · {selected.email} · {SUBJECT_LABEL[selected.subject]}</Text>
            {selected.user_phone ? <Text style={styles.detailMeta}>User phone: {selected.user_phone}</Text> : null}
            {selected.user_id ? <Text style={styles.detailMeta}>UID: {selected.user_id}</Text> : null}
            <Text style={styles.detailBody}>{selected.message}</Text>
            <View style={styles.statusRow}>
              {(['new','open','resolved','closed'] as const).map((s) => {
                const p = statusPill(s);
                return (
                  <TouchableOpacity
                    key={s} onPress={() => changeStatus(s)}
                    style={[styles.statusBtn, { backgroundColor: p.bg }, selected.status === s && { borderWidth: 1.5, borderColor: p.fg }]}
                    activeOpacity={0.85}
                    testID={`cs-status-${s}`}
                  >
                    <Text style={[styles.statusBtnText, { color: p.fg }]}>Mark {s}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>
            <Text style={[styles.sectionLabel, { marginTop: SPACING.md }]}>Reply to user</Text>
            {/* Outgoing replies (sent to user by admin) */}
            {(selected.replies || []).length === 0 ? (
              <Text style={styles.subtle}>No replies yet.</Text>
            ) : (
              (selected.replies || []).map((rp: any) => (
                <View key={rp.id} style={[styles.noteCard, { backgroundColor: COLORS.primaryLight, borderColor: COLORS.primary }]}>
                  <Text style={[styles.noteMeta, { color: COLORS.primary }]}>
                    {rp.from_email || 'admin'} → {selected.email} · {new Date(rp.created_at).toLocaleString()}
                    {rp.email_dispatch?.sent ? ' · email sent' : rp.email_dispatch?.error ? ` · email FAILED (${rp.email_dispatch.error})` : ''}
                  </Text>
                  <Text style={styles.noteBody}>{rp.message}</Text>
                </View>
              ))
            )}
            <View style={{ flexDirection: 'row', gap: 8, alignItems: 'flex-end' }}>
              <TextInput
                value={reply}
                onChangeText={setReply}
                placeholder={`Send a reply to ${selected.email}…`}
                placeholderTextColor={COLORS.disabledText}
                multiline
                style={[styles.input, { flex: 1, minHeight: 80, textAlignVertical: 'top' }]}
                testID="cs-reply-input"
              />
              <TouchableOpacity
                onPress={async () => {
                  if (!reply.trim()) return;
                  setReplying(true);
                  try {
                    const updated = await ticketsApi.reply(selected.id, reply.trim(), true);
                    setSelected(updated);
                    setReply('');
                    toast.success('Reply sent');
                    load();
                  } catch (e: any) {
                    Alert.alert('Reply failed', e?.message || 'Could not send reply');
                  } finally {
                    setReplying(false);
                  }
                }}
                disabled={replying || !reply.trim()}
                style={[styles.addNoteBtn, { backgroundColor: COLORS.success }, (replying || !reply.trim()) && { opacity: 0.5 }]}
                activeOpacity={0.85}
                testID="cs-reply-send"
              >
                {replying ? <ActivityIndicator color="#fff" size="small" /> : <Send size={14} color="#fff" />}
                <Text style={styles.addNoteBtnText}>{replying ? 'Sending…' : 'Reply'}</Text>
              </TouchableOpacity>
            </View>

            <Text style={[styles.sectionLabel, { marginTop: SPACING.md }]}>Internal notes</Text>
            {(selected.notes || []).length === 0 ? (
              <Text style={styles.subtle}>No notes yet.</Text>
            ) : (
              (selected.notes || []).map((n: any) => (
                <View key={n.id} style={styles.noteCard}>
                  <Text style={styles.noteMeta}>{n.author_email || 'admin'} · {new Date(n.created_at).toLocaleString()}</Text>
                  <Text style={styles.noteBody}>{n.note}</Text>
                </View>
              ))
            )}
            <View style={{ flexDirection: 'row', gap: 8, alignItems: 'flex-end' }}>
              <TextInput value={note} onChangeText={setNote} placeholder="Add an internal note…" placeholderTextColor={COLORS.disabledText} multiline style={[styles.input, { flex: 1, minHeight: 60, textAlignVertical: 'top' }]} />
              <TouchableOpacity onPress={submitNote} style={styles.addNoteBtn} activeOpacity={0.85} testID="cs-add-note">
                <Send size={14} color="#fff" />
                <Text style={styles.addNoteBtnText}>Add</Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  h1: { fontSize: 22, fontWeight: FONT.weights.heavy, color: COLORS.text },
  subtle: { color: COLORS.subtext, fontSize: FONT.sizes.sm },
  countersRow: { flexDirection: 'row', gap: SPACING.sm, flexWrap: 'wrap' },
  counterTile: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: RADIUS.md, minWidth: 90, alignItems: 'flex-start', borderWidth: 1, borderColor: 'transparent' },
  counterLabel: { fontSize: 10, fontWeight: FONT.weights.bold, letterSpacing: 0.8 },
  counterAmt: { fontSize: 22, fontWeight: FONT.weights.heavy, marginTop: 2 },
  filterRow: { flexDirection: Platform.OS === 'web' ? 'row' : 'column', gap: SPACING.sm, alignItems: Platform.OS === 'web' ? 'center' : 'stretch' },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: RADIUS.pill, backgroundColor: COLORS.primaryLight, borderWidth: 1, borderColor: COLORS.primaryLight },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { color: COLORS.primary, fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold },
  chipTextActive: { color: '#fff' },
  input: {
    borderRadius: RADIUS.md, borderWidth: 1.5, borderColor: COLORS.border,
    backgroundColor: COLORS.surface, paddingHorizontal: SPACING.md,
    paddingVertical: Platform.OS === 'ios' ? 10 : 8,
    fontSize: FONT.sizes.md, color: COLORS.text,
  },
  row: { padding: SPACING.md, borderRadius: RADIUS.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, gap: 4 },
  rowName: { fontWeight: FONT.weights.bold, color: COLORS.text },
  rowSubject: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
  rowEmail: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
  rowMsg: { color: COLORS.text, fontSize: FONT.sizes.sm },
  rowDate: { color: COLORS.subtext, fontSize: 11 },
  statusPill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: RADIUS.pill },
  statusPillText: { fontSize: 10, fontWeight: FONT.weights.bold, textTransform: 'uppercase', letterSpacing: 0.5 },
  pager: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACING.md, paddingVertical: SPACING.md },
  pageBtn: { paddingHorizontal: SPACING.md, paddingVertical: 8, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface, minWidth: 70, alignItems: 'center' },
  pageBtnText: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  pageInfo: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  detail: { padding: SPACING.md, borderRadius: RADIUS.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, gap: SPACING.sm, marginTop: SPACING.lg },
  detailTitle: { fontWeight: FONT.weights.heavy, fontSize: FONT.sizes.lg, color: COLORS.text },
  detailMeta: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
  detailBody: { color: COLORS.text, fontSize: FONT.sizes.sm, lineHeight: 20, marginTop: SPACING.sm },
  statusRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: SPACING.sm },
  statusBtn: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: 'transparent' },
  statusBtnText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.bold },
  sectionLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', letterSpacing: 1 },
  noteCard: { padding: 10, backgroundColor: COLORS.bg, borderRadius: RADIUS.md, gap: 2, borderWidth: 1, borderColor: COLORS.border },
  noteMeta: { color: COLORS.subtext, fontSize: 11 },
  noteBody: { color: COLORS.text, fontSize: FONT.sizes.sm },
  addNoteBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 10, borderRadius: RADIUS.md, backgroundColor: COLORS.primary },
  addNoteBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
});
