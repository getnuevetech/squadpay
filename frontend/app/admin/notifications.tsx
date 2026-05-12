/**
 * Admin Notification Center (June 2025).
 *
 * Admins compose a short message + optional image URL + optional link URL
 * and choose:
 *   • audience: All users / Leads only / Members only / Specific Squads
 *   • channels: In-app inbox and/or SMS
 *
 * Submitting posts to /api/admin/notifications/broadcast. Below the form
 * we show the most recent broadcasts (last 100) so admins can audit what
 * went out and to whom.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Send, Mail, MessageSquare, CheckCircle2, AlertCircle, Image as ImgIcon, Link as LinkIcon } from 'lucide-react-native';
import { adminApi } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

type Audience = 'all' | 'leads' | 'members' | 'groups';

export default function AdminNotificationsScreen() {
  const [message, setMessage] = useState('');
  const [imageUrl, setImageUrl] = useState('');
  const [linkUrl, setLinkUrl] = useState('');
  const [audience, setAudience] = useState<Audience>('all');
  const [groupIdsRaw, setGroupIdsRaw] = useState('');
  const [chInApp, setChInApp] = useState(true);
  const [chSms, setChSms] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const r = await adminApi.listBroadcasts();
      setHistory(r.items || []);
    } catch (e: any) {
      // best-effort, ignore
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const submit = async () => {
    setError(null);
    setSuccess(null);
    if (!message.trim()) {
      setError('Please enter a message before sending.');
      return;
    }
    if (!chInApp && !chSms) {
      setError('Choose at least one delivery channel (in-app or SMS).');
      return;
    }
    if (audience === 'groups') {
      const ids = groupIdsRaw.split(/[\s,]+/).filter(Boolean);
      if (ids.length === 0) {
        setError('Add at least one Squad ID when sending to specific Squads.');
        return;
      }
    }
    setSending(true);
    try {
      const group_ids = audience === 'groups'
        ? groupIdsRaw.split(/[\s,]+/).filter(Boolean)
        : undefined;
      const res = await adminApi.broadcastNotification({
        message: message.trim(),
        image_url: imageUrl.trim() || null,
        link_url: linkUrl.trim() || null,
        audience: { type: audience, group_ids },
        channels: { in_app: chInApp, sms: chSms },
      });
      setSuccess(
        `Sent to ${res.recipient_count} user${res.recipient_count === 1 ? '' : 's'} ` +
        `· In-app: ${res.in_app_delivered} · SMS sent: ${res.sms_sent}` +
        (res.sms_failed ? ` · SMS failed: ${res.sms_failed}` : ''),
      );
      setMessage('');
      setImageUrl('');
      setLinkUrl('');
      setGroupIdsRaw('');
      await loadHistory();
    } catch (e: any) {
      setError(e?.message || 'Could not send the broadcast.');
    } finally {
      setSending(false);
    }
  };

  const audienceLabel = (t: string) => ({
    all: 'All users',
    leads: 'Leads only',
    members: 'Members only',
    groups: 'Specific Squads',
  } as Record<string, string>)[t] || t;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: COLORS.bg }} edges={['bottom']}>
      <ScrollView contentContainerStyle={{ padding: SPACING.lg, gap: SPACING.md }}>
        <Text style={styles.h1}>Notification Center</Text>
        <Text style={styles.subtle}>
          Send a short broadcast to your users via in-app inbox and/or SMS. Add
          a link or an image URL to enrich the message.
        </Text>

        <View style={styles.card}>
          <Text style={styles.label}>Message</Text>
          <TextInput
            testID="admin-notif-message"
            value={message}
            onChangeText={setMessage}
            multiline
            placeholder="What do you want to say?"
            placeholderTextColor={COLORS.disabledText}
            style={[styles.input, { minHeight: 88, textAlignVertical: 'top' }]}
          />
          <Text style={styles.helper}>{message.length}/1000</Text>

          <View style={styles.row2}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}><ImgIcon size={12} color={COLORS.subtext} /> Image URL (optional)</Text>
              <TextInput
                testID="admin-notif-image-url"
                value={imageUrl}
                onChangeText={setImageUrl}
                placeholder="https://…"
                placeholderTextColor={COLORS.disabledText}
                style={styles.input}
                autoCapitalize="none"
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}><LinkIcon size={12} color={COLORS.subtext} /> Link URL (optional)</Text>
              <TextInput
                testID="admin-notif-link-url"
                value={linkUrl}
                onChangeText={setLinkUrl}
                placeholder="https://…"
                placeholderTextColor={COLORS.disabledText}
                style={styles.input}
                autoCapitalize="none"
              />
            </View>
          </View>

          <Text style={[styles.label, { marginTop: SPACING.md }]}>Audience</Text>
          <View style={styles.audRow}>
            {(['all', 'leads', 'members', 'groups'] as Audience[]).map((a) => (
              <TouchableOpacity
                key={a}
                testID={`admin-notif-audience-${a}`}
                style={[styles.chip, audience === a && styles.chipActive]}
                onPress={() => setAudience(a)}
                activeOpacity={0.85}
              >
                <Text style={[styles.chipText, audience === a && styles.chipTextActive]}>
                  {audienceLabel(a)}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          {audience === 'groups' && (
            <>
              <Text style={[styles.label, { marginTop: SPACING.sm }]}>Squad IDs</Text>
              <TextInput
                testID="admin-notif-group-ids"
                value={groupIdsRaw}
                onChangeText={setGroupIdsRaw}
                placeholder="g_abc123, g_def456, … (comma or space separated)"
                placeholderTextColor={COLORS.disabledText}
                style={styles.input}
                autoCapitalize="none"
              />
            </>
          )}

          <Text style={[styles.label, { marginTop: SPACING.md }]}>Channels</Text>
          <View style={styles.audRow}>
            <TouchableOpacity
              testID="admin-notif-channel-inapp"
              style={[styles.chip, chInApp && styles.chipActive]}
              onPress={() => setChInApp(!chInApp)}
              activeOpacity={0.85}
            >
              <Mail size={14} color={chInApp ? '#fff' : COLORS.primary} />
              <Text style={[styles.chipText, chInApp && styles.chipTextActive]}>In-app</Text>
            </TouchableOpacity>
            <TouchableOpacity
              testID="admin-notif-channel-sms"
              style={[styles.chip, chSms && styles.chipActive]}
              onPress={() => setChSms(!chSms)}
              activeOpacity={0.85}
            >
              <MessageSquare size={14} color={chSms ? '#fff' : COLORS.primary} />
              <Text style={[styles.chipText, chSms && styles.chipTextActive]}>SMS</Text>
            </TouchableOpacity>
          </View>

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
            testID="admin-notif-send-btn"
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
                <Text style={styles.sendBtnText}>Send broadcast</Text>
              </>
            )}
          </TouchableOpacity>
        </View>

        <Text style={[styles.h2, { marginTop: SPACING.md }]}>Recent broadcasts</Text>
        {loadingHistory ? (
          <ActivityIndicator color={COLORS.primary} />
        ) : history.length === 0 ? (
          <Text style={styles.subtle}>Nothing sent yet.</Text>
        ) : (
          history.map((b) => (
            <View key={b.id} style={styles.historyCard} testID={`admin-notif-history-${b.id}`}>
              <View style={styles.histTop}>
                <Text style={styles.histAudience}>
                  {audienceLabel(b.audience?.type || 'all')}
                </Text>
                <Text style={styles.histDate}>
                  {new Date(b.sent_at).toLocaleString()}
                </Text>
              </View>
              <Text style={styles.histMsg} numberOfLines={3}>{b.message}</Text>
              {b.link_url ? <Text style={styles.histLink}>{b.link_url}</Text> : null}
              <View style={styles.histStats}>
                <Text style={styles.histStat}>👥 {b.recipient_count}</Text>
                {b.channels?.in_app ? <Text style={styles.histStat}>✉️ in-app</Text> : null}
                {b.channels?.sms ? (
                  <Text style={styles.histStat}>
                    📱 SMS {b.sms_sent}/{b.sms_sent + b.sms_failed}
                  </Text>
                ) : null}
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  h1: { fontSize: 24, fontWeight: FONT.weights.heavy, color: COLORS.text, letterSpacing: -0.4 },
  h2: { fontSize: 16, fontWeight: FONT.weights.bold, color: COLORS.text },
  subtle: { color: COLORS.subtext, fontSize: FONT.sizes.sm, lineHeight: 20 },
  card: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.md,
    gap: 8,
  },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', letterSpacing: 1, marginTop: 4 },
  helper: { fontSize: FONT.sizes.xs, color: COLORS.subtext, alignSelf: 'flex-end' },
  input: {
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    backgroundColor: COLORS.bg,
    paddingHorizontal: SPACING.md,
    paddingVertical: Platform.OS === 'ios' ? 10 : 8,
    fontSize: FONT.sizes.md,
    color: COLORS.text,
    marginBottom: 4,
  },
  row2: { flexDirection: 'row', gap: SPACING.sm, marginTop: 4 },
  audRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: RADIUS.pill,
    backgroundColor: COLORS.primaryLight,
    borderWidth: 1,
    borderColor: COLORS.primaryLight,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { color: COLORS.primary, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  chipTextActive: { color: '#fff' },
  sendBtn: {
    marginTop: SPACING.md,
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.md,
    height: 48,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 8,
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
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.md,
    gap: 4,
  },
  histTop: { flexDirection: 'row', justifyContent: 'space-between' },
  histAudience: { color: COLORS.primary, fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs, textTransform: 'uppercase', letterSpacing: 0.5 },
  histDate: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
  histMsg: { color: COLORS.text, fontSize: FONT.sizes.sm, lineHeight: 20 },
  histLink: { color: COLORS.primary, fontSize: FONT.sizes.xs, textDecorationLine: 'underline' },
  histStats: { flexDirection: 'row', gap: 12, marginTop: 4 },
  histStat: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
});
