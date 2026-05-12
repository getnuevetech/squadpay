/**
 * Bulk SMS Broadcaster (Admin — June 2025).
 *
 * SMS-only sibling of the Notification Center. Lets admins send marketing
 * blasts to:
 *   - all app users with a phone on file
 *   - leads / members / specific squads
 *   - an arbitrary uploaded list OR a typed list of phone numbers
 *
 * Numbers entered via paste / upload are accepted in any reasonable
 * format; the backend normalises and dedupes them.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
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
import * as DocumentPicker from 'expo-document-picker';
import {
  Send,
  AlertCircle,
  CheckCircle2,
  Upload,
  Users,
  Hash,
} from 'lucide-react-native';
import { adminApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

type Audience = 'all_users' | 'leads' | 'members' | 'groups' | 'numbers';

const HISTORY_PAGE_SIZE = 10;

export default function AdminBulkSmsScreen() {
  const [message, setMessage] = useState('');
  const [audience, setAudience] = useState<Audience>('all_users');
  const [groupIdsRaw, setGroupIdsRaw] = useState('');
  const [numbersRaw, setNumbersRaw] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [loadingHistory, setLoadingHistory] = useState(true);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const r = await adminApi.listBulkSms(historyPage, HISTORY_PAGE_SIZE);
      setHistory(r.items || []);
      setHistoryTotal(r.total || 0);
    } catch {} finally {
      setLoadingHistory(false);
    }
  }, [historyPage]);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const numbersParsed = useMemo(() => {
    if (audience !== 'numbers') return 0;
    return numbersRaw
      .split(/[,\s;\n]+/)
      .map((s) => s.trim())
      .filter(Boolean).length;
  }, [audience, numbersRaw]);

  const pickFile = async () => {
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ['text/csv', 'text/plain', 'application/csv', '*/*'],
        copyToCacheDirectory: true,
      });
      if (res.canceled || !res.assets?.[0]?.uri) return;
      // Fetch the file's text body — works for both native & web.
      const txt = await fetch(res.assets[0].uri).then((r) => r.text());
      // Split on common delimiters & strip header column ("phone").
      const lines = txt
        .split(/[\n\r,]+/)
        .map((s) => s.trim())
        .filter((s) => s && !/^phone$/i.test(s));
      setNumbersRaw((prev) => {
        const merged = (prev ? prev + '\n' : '') + lines.join('\n');
        return merged;
      });
    } catch (e: any) {
      setError(e?.message || "We couldn't read that file.");
    }
  };

  const submit = async () => {
    setError(null);
    setSuccess(null);
    if (!message.trim()) {
      setError('Please enter a message before sending.');
      return;
    }
    if (audience === 'groups') {
      const ids = groupIdsRaw.split(/[\s,]+/).filter(Boolean);
      if (ids.length === 0) {
        setError('Add at least one Squad ID when sending to specific Squads.');
        return;
      }
    }
    if (audience === 'numbers' && numbersParsed === 0) {
      setError('Add at least one phone number.');
      return;
    }
    setSending(true);
    try {
      const body: any = {
        message: message.trim(),
        audience,
      };
      if (audience === 'groups') {
        body.group_ids = groupIdsRaw.split(/[\s,]+/).filter(Boolean);
      }
      if (audience === 'numbers') {
        body.phone_numbers = numbersRaw
          .split(/[,\s;\n]+/)
          .map((s) => s.trim())
          .filter(Boolean);
      }
      const r = await adminApi.sendBulkSms(body);
      setSuccess(
        `Sent to ${r.recipient_count} number${r.recipient_count === 1 ? '' : 's'} ` +
        `· SMS sent: ${r.sms_sent}` +
        (r.sms_failed ? ` · failed: ${r.sms_failed}` : ''),
      );
      setMessage('');
      setNumbersRaw('');
      setGroupIdsRaw('');
      await loadHistory();
    } catch (e: any) {
      setError(e?.message || 'Could not send the SMS blast.');
    } finally {
      setSending(false);
    }
  };

  const audienceLabel = (t: string) => ({
    all_users: 'All app users',
    leads: 'Leads only',
    members: 'Members only',
    groups: 'Specific Squads',
    numbers: 'Custom numbers',
  } as Record<string, string>)[t] || t;

  const totalPages = Math.max(1, Math.ceil(historyTotal / HISTORY_PAGE_SIZE));
  const charCount = message.length;
  const segments = Math.max(1, Math.ceil(charCount / 160));

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: COLORS.bg }} edges={['bottom']}>
      <ScrollView contentContainerStyle={{ padding: SPACING.lg, gap: SPACING.md }}>
        <Text style={styles.h1}>Bulk SMS</Text>
        <Text style={styles.subtle}>
          Broadcast plain SMS to app users or any external phone numbers
          (uploaded list, pasted list, or single number). Use this for
          marketing, referral nudges, or growth campaigns.
        </Text>

        <View style={styles.card}>
          <Text style={styles.label}>Message</Text>
          <TextInput
            testID="admin-bulksms-message"
            value={message}
            onChangeText={setMessage}
            multiline
            placeholder="What do you want to text?"
            placeholderTextColor={COLORS.disabledText}
            style={[styles.input, { minHeight: 96, textAlignVertical: 'top' }]}
          />
          <Text style={styles.helper}>
            {charCount}/1000 · {segments} SMS segment{segments === 1 ? '' : 's'} (per recipient)
          </Text>

          <Text style={[styles.label, { marginTop: SPACING.md }]}>Audience</Text>
          <View style={styles.audRow}>
            {(['all_users', 'leads', 'members', 'groups', 'numbers'] as Audience[]).map((a) => (
              <TouchableOpacity
                key={a}
                testID={`admin-bulksms-audience-${a}`}
                style={[styles.chip, audience === a && styles.chipActive]}
                onPress={() => setAudience(a)}
                activeOpacity={0.85}
              >
                {a === 'numbers' ? (
                  <Hash size={14} color={audience === a ? '#fff' : COLORS.primary} />
                ) : (
                  <Users size={14} color={audience === a ? '#fff' : COLORS.primary} />
                )}
                <Text style={[styles.chipText, audience === a && styles.chipTextActive]}>
                  {audienceLabel(a)}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {audience === 'groups' ? (
            <>
              <Text style={[styles.label, { marginTop: SPACING.sm }]}>Squad IDs</Text>
              <TextInput
                testID="admin-bulksms-group-ids"
                value={groupIdsRaw}
                onChangeText={setGroupIdsRaw}
                placeholder="g_abc123, g_def456, …"
                placeholderTextColor={COLORS.disabledText}
                style={styles.input}
                autoCapitalize="none"
              />
            </>
          ) : null}

          {audience === 'numbers' ? (
            <>
              <Text style={[styles.label, { marginTop: SPACING.sm }]}>
                Phone numbers ({numbersParsed} parsed)
              </Text>
              <TextInput
                testID="admin-bulksms-numbers"
                value={numbersRaw}
                onChangeText={setNumbersRaw}
                multiline
                placeholder={'+12025550123\n2025550123\n(202) 555-0123'}
                placeholderTextColor={COLORS.disabledText}
                style={[styles.input, { minHeight: 110, textAlignVertical: 'top' }]}
                autoCapitalize="none"
              />
              <View style={{ flexDirection: 'row', gap: 8, marginTop: 6 }}>
                <TouchableOpacity
                  onPress={pickFile}
                  activeOpacity={0.85}
                  style={styles.uploadBtn}
                  testID="admin-bulksms-upload-btn"
                >
                  <Upload size={14} color={COLORS.primary} />
                  <Text style={styles.uploadBtnText}>Upload CSV / TXT</Text>
                </TouchableOpacity>
                {numbersRaw ? (
                  <TouchableOpacity
                    onPress={() => setNumbersRaw('')}
                    activeOpacity={0.85}
                    style={styles.clearBtn}
                    testID="admin-bulksms-clear-numbers"
                  >
                    <Text style={styles.clearBtnText}>Clear</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
              <Text style={[styles.helper, { marginTop: 4 }]}>
                Tip: paste numbers comma- or newline-separated. Country codes
                are recommended (+1, +44…) but not required.
              </Text>
            </>
          ) : null}

          {error ? (
            <View style={styles.errBanner}>
              <AlertCircle size={14} color={COLORS.danger} />
              <Text style={styles.errText}>{error}</Text>
            </View>
          ) : null}
          {success ? (
            <View style={styles.okBanner}>
              <CheckCircle2 size={14} color={COLORS.success} />
              <Text style={styles.okText}>{success}</Text>
            </View>
          ) : null}

          <TouchableOpacity
            testID="admin-bulksms-send-btn"
            onPress={submit}
            disabled={sending}
            activeOpacity={0.85}
            style={[styles.sendBtn, sending && { opacity: 0.7 }]}
          >
            {sending ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Send size={16} color="#fff" />
                <Text style={styles.sendBtnText}>Send SMS blast</Text>
              </>
            )}
          </TouchableOpacity>
        </View>

        <Text style={[styles.h2, { marginTop: SPACING.md }]}>Recent SMS blasts</Text>
        {loadingHistory ? (
          <ActivityIndicator color={COLORS.primary} />
        ) : history.length === 0 ? (
          <Text style={styles.subtle}>Nothing sent yet.</Text>
        ) : (
          history.map((b) => (
            <View key={b.id} style={styles.historyCard} testID={`admin-bulksms-history-${b.id}`}>
              <View style={styles.histTop}>
                <Text style={styles.histAudience}>{audienceLabel(b.audience)}</Text>
                <Text style={styles.histDate}>{new Date(b.sent_at).toLocaleString()}</Text>
              </View>
              <Text style={styles.histMsg} numberOfLines={3}>{b.message}</Text>
              <View style={styles.histStats}>
                <Text style={styles.histStat}>👥 {b.recipient_count}</Text>
                <Text style={styles.histStat}>📱 SMS {b.sms_sent}/{b.sms_sent + b.sms_failed}</Text>
              </View>
            </View>
          ))
        )}

        {historyTotal > HISTORY_PAGE_SIZE ? (
          <View style={styles.pager}>
            <TouchableOpacity
              onPress={() => setHistoryPage((p) => Math.max(1, p - 1))}
              disabled={historyPage <= 1 || loadingHistory}
              style={[styles.pagerBtn, (historyPage <= 1 || loadingHistory) && { opacity: 0.4 }]}
              activeOpacity={0.85}
              testID="admin-bulksms-page-prev"
            >
              <Text style={styles.pagerBtnText}>Prev</Text>
            </TouchableOpacity>
            <Text style={styles.pagerInfo}>Page {historyPage} of {totalPages}</Text>
            <TouchableOpacity
              onPress={() => setHistoryPage((p) => Math.min(totalPages, p + 1))}
              disabled={historyPage >= totalPages || loadingHistory}
              style={[styles.pagerBtn, (historyPage >= totalPages || loadingHistory) && { opacity: 0.4 }]}
              activeOpacity={0.85}
              testID="admin-bulksms-page-next"
            >
              <Text style={styles.pagerBtnText}>Next</Text>
            </TouchableOpacity>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  h1: { fontSize: 24, fontWeight: FONT.weights.heavy, color: COLORS.text, letterSpacing: -0.4 },
  h2: { fontSize: 16, fontWeight: FONT.weights.bold, color: COLORS.text },
  subtle: { color: COLORS.subtext, fontSize: FONT.sizes.sm, lineHeight: 20 },
  card: {
    backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, borderWidth: 1,
    borderColor: COLORS.border, padding: SPACING.md, gap: 8,
  },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', letterSpacing: 1 },
  helper: { fontSize: FONT.sizes.xs, color: COLORS.subtext, alignSelf: 'flex-end' },
  input: {
    borderRadius: RADIUS.md, borderWidth: 1.5, borderColor: COLORS.border,
    backgroundColor: COLORS.bg, paddingHorizontal: SPACING.md,
    paddingVertical: Platform.OS === 'ios' ? 10 : 8,
    fontSize: FONT.sizes.md, color: COLORS.text, marginBottom: 4,
  },
  audRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: RADIUS.pill,
    backgroundColor: COLORS.primaryLight, borderWidth: 1, borderColor: COLORS.primaryLight,
    flexDirection: 'row', alignItems: 'center', gap: 6,
  },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { color: COLORS.primary, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  chipTextActive: { color: '#fff' },
  uploadBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: RADIUS.md,
    backgroundColor: COLORS.primaryLight, borderWidth: 1, borderColor: COLORS.primaryLight,
  },
  uploadBtnText: { color: COLORS.primary, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  clearBtn: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: RADIUS.md,
    borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface,
  },
  clearBtnText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
  sendBtn: {
    marginTop: SPACING.md, backgroundColor: COLORS.primary, borderRadius: RADIUS.md,
    height: 48, alignItems: 'center', justifyContent: 'center',
    flexDirection: 'row', gap: 8,
  },
  sendBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
  errBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    backgroundColor: COLORS.dangerLight, borderRadius: RADIUS.md,
    padding: 10, marginTop: SPACING.sm,
  },
  errText: { color: COLORS.danger, fontSize: FONT.sizes.sm, flex: 1 },
  okBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    backgroundColor: COLORS.successLight, borderRadius: RADIUS.md,
    padding: 10, marginTop: SPACING.sm,
  },
  okText: { color: COLORS.success, fontSize: FONT.sizes.sm, flex: 1 },
  historyCard: {
    backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1,
    borderColor: COLORS.border, padding: SPACING.md, gap: 4,
  },
  histTop: { flexDirection: 'row', justifyContent: 'space-between' },
  histAudience: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs, textTransform: 'uppercase', letterSpacing: 0.5 },
  histDate: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
  histMsg: { color: COLORS.text, fontSize: FONT.sizes.sm, lineHeight: 20 },
  histStats: { flexDirection: 'row', gap: 12, marginTop: 4 },
  histStat: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
  pager: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACING.md, paddingVertical: SPACING.md,
  },
  pagerBtn: {
    paddingHorizontal: SPACING.md, paddingVertical: 8, borderRadius: RADIUS.md,
    borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface,
    minWidth: 70, alignItems: 'center',
  },
  pagerBtnText: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  pagerInfo: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
});
