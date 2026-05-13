/**
 * Admin · Notification Config (June 2025).
 *
 * Per-event channel matrix: admin checks which channels each notification
 * event uses (SMS, Push, Both, or Off). Also exposes:
 *  • Settlement delay slider (Lead Paid → Bill Settled, default 20 min)
 *  • Push status banner (push delivery currently no-op until
 *    expo-notifications integration ships in a follow-up build)
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
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
import {
  BellRing,
  MessageSquare,
  Smartphone,
  CheckCircle2,
  AlertCircle,
  Clock,
} from 'lucide-react-native';
import {
  notificationConfigApi,
  settlementDelayApi,
  type NotifChannel,
  type NotificationConfig,
} from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

const CHANNELS: { key: NotifChannel; label: string }[] = [
  { key: 'off', label: 'Off' },
  { key: 'sms', label: 'SMS' },
  { key: 'push', label: 'Push' },
  { key: 'both', label: 'Both' },
];

export default function AdminNotificationConfigScreen() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const [config, setConfig] = useState<NotificationConfig | null>(null);
  const [delayMin, setDelayMin] = useState<string>('20');
  const [delayDirty, setDelayDirty] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, delay] = await Promise.all([
        notificationConfigApi.get(),
        settlementDelayApi.get(),
      ]);
      setConfig(cfg);
      setDelayMin(String(delay.minutes));
      setDelayDirty(false);
    } catch (e: any) {
      setError(e?.message || 'Failed to load notification config');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const setChannel = (event: string, ch: NotifChannel) => {
    if (!config) return;
    setConfig({
      ...config,
      events: { ...config.events, [event]: { ...config.events[event], channel: ch } },
    });
  };

  const eventEntries = useMemo(() => {
    if (!config) return [];
    return Object.entries(config.events);
  }, [config]);

  const save = async () => {
    if (!config) return;
    setSaving(true);
    setError(null);
    setSavedAt(null);
    try {
      const flatEvents: Record<string, NotifChannel> = {};
      for (const [k, v] of Object.entries(config.events)) flatEvents[k] = v.channel;
      const next = await notificationConfigApi.set(flatEvents, config.push_enabled);
      setConfig(next);
      // Save settlement delay if dirty
      if (delayDirty) {
        const m = Math.max(0, Math.min(240, parseInt(delayMin || '20', 10) || 20));
        await settlementDelayApi.set(m);
        setDelayMin(String(m));
        setDelayDirty(false);
      }
      setSavedAt(new Date().toLocaleTimeString());
    } catch (e: any) {
      setError(e?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={s.safe}>
        <View style={s.center}>
          <ActivityIndicator color={COLORS.primary} />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView contentContainerStyle={s.scroll}>
        <View style={s.header}>
          <BellRing size={24} color={COLORS.primary} />
          <Text style={s.h1}>Notification Config</Text>
        </View>
        <Text style={s.sub}>
          Choose how each in-app notification is delivered. SMS is live now; Push will
          dispatch once the next mobile build ships with expo-notifications.
        </Text>

        {error ? (
          <View style={s.error}>
            <AlertCircle size={16} color={COLORS.danger} />
            <Text style={s.errorText}>{error}</Text>
          </View>
        ) : null}
        {savedAt ? (
          <View style={s.success}>
            <CheckCircle2 size={16} color={COLORS.success} />
            <Text style={s.successText}>Saved at {savedAt}</Text>
          </View>
        ) : null}

        {/* Push status banner */}
        <View style={s.pushBanner}>
          <Smartphone size={18} color={COLORS.warning} />
          <Text style={s.pushBannerText}>
            Push delivery is wire-ready but no-ops in this build (
            <Text style={{ fontWeight: '700' }}>expo-notifications</Text> integration
            pending). Your choices will activate automatically in the next mobile build.
          </Text>
        </View>

        {/* Push master toggle */}
        <View style={s.row}>
          <Text style={s.rowLabel}>Push notifications globally enabled</Text>
          <TouchableOpacity
            style={[s.toggle, config?.push_enabled && s.toggleOn]}
            onPress={() => config && setConfig({ ...config, push_enabled: !config.push_enabled })}
          >
            <View style={[s.knob, config?.push_enabled && s.knobOn]} />
          </TouchableOpacity>
        </View>

        {/* Event channel matrix */}
        <View style={s.card}>
          <Text style={s.cardTitle}>Per-event channels</Text>
          {eventEntries.map(([key, cfg]) => (
            <View key={key} style={s.eventRow}>
              <View style={{ flex: 1 }}>
                <Text style={s.eventName}>{key}</Text>
                <Text style={s.eventDesc}>{cfg.description}</Text>
              </View>
              <View style={s.pillRow}>
                {CHANNELS.map((c) => (
                  <TouchableOpacity
                    key={c.key}
                    onPress={() => setChannel(key, c.key)}
                    style={[s.pill, cfg.channel === c.key && s.pillActive]}
                  >
                    <Text
                      style={[s.pillText, cfg.channel === c.key && s.pillTextActive]}
                    >
                      {c.label}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>
          ))}
        </View>

        {/* Settlement delay */}
        <View style={s.card}>
          <View style={s.rowHeader}>
            <Clock size={18} color={COLORS.primary} />
            <Text style={s.cardTitle}>Settlement delay</Text>
          </View>
          <Text style={s.sub}>
            Minutes between Lead Paid (Stripe Connect webhook) and Bill Settled.
            Bounded 0–240.
          </Text>
          <View style={s.delayRow}>
            <TextInput
              style={s.delayInput}
              keyboardType="number-pad"
              value={delayMin}
              onChangeText={(v) => {
                setDelayMin(v.replace(/[^0-9]/g, ''));
                setDelayDirty(true);
              }}
              maxLength={3}
            />
            <Text style={s.delayUnit}>min</Text>
          </View>
        </View>

        <TouchableOpacity
          style={[s.saveBtn, (saving || !config) && { opacity: 0.5 }]}
          disabled={saving || !config}
          onPress={save}
        >
          {saving ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={s.saveText}>Save Notification Config</Text>
          )}
        </TouchableOpacity>

        <View style={{ height: 60 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: SPACING.lg, gap: SPACING.md },
  header: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  h1: { fontSize: FONT.sizes.xl, fontWeight: '700', color: COLORS.text },
  sub: { fontSize: FONT.sizes.sm, color: COLORS.muted, lineHeight: 18 },
  error: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.xs,
    padding: SPACING.sm,
    backgroundColor: COLORS.dangerLight,
    borderRadius: RADIUS.md,
  },
  errorText: { color: COLORS.danger, fontSize: FONT.sizes.sm },
  success: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.xs,
    padding: SPACING.sm,
    backgroundColor: COLORS.successLight,
    borderRadius: RADIUS.md,
  },
  successText: { color: COLORS.success, fontSize: FONT.sizes.sm },
  pushBanner: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: SPACING.sm,
    padding: SPACING.md,
    backgroundColor: COLORS.warningLight,
    borderRadius: RADIUS.md,
  },
  pushBannerText: { flex: 1, color: COLORS.text, fontSize: FONT.sizes.sm, lineHeight: 18 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
  },
  rowLabel: { flex: 1, color: COLORS.text, fontSize: FONT.sizes.md, fontWeight: '600' },
  toggle: {
    width: 44,
    height: 24,
    borderRadius: 12,
    backgroundColor: COLORS.border,
    padding: 2,
    justifyContent: 'center',
  },
  toggleOn: { backgroundColor: COLORS.primary },
  knob: { width: 20, height: 20, borderRadius: 10, backgroundColor: '#fff' },
  knobOn: { alignSelf: 'flex-end' },
  card: {
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    gap: SPACING.sm,
  },
  cardTitle: { fontSize: FONT.sizes.md, fontWeight: '700', color: COLORS.text },
  rowHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACING.xs },
  eventRow: {
    paddingVertical: SPACING.sm,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    flexDirection: Platform.OS === 'web' ? 'row' : 'column',
    alignItems: Platform.OS === 'web' ? 'center' : 'stretch',
    gap: SPACING.sm,
  },
  eventName: { fontSize: FONT.sizes.sm, fontWeight: '700', color: COLORS.text },
  eventDesc: { fontSize: FONT.sizes.xs, color: COLORS.muted, marginTop: 2 },
  pillRow: { flexDirection: 'row', gap: SPACING.xs, flexWrap: 'wrap' },
  pill: {
    paddingHorizontal: SPACING.sm,
    paddingVertical: 6,
    borderRadius: RADIUS.sm,
    backgroundColor: COLORS.bg,
    borderWidth: 1,
    borderColor: COLORS.border,
    minWidth: 56,
    alignItems: 'center',
  },
  pillActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  pillText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: '600' },
  pillTextActive: { color: '#fff' },
  delayRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  delayInput: {
    width: 80,
    paddingHorizontal: SPACING.sm,
    paddingVertical: SPACING.sm,
    backgroundColor: COLORS.bg,
    borderRadius: RADIUS.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
    fontSize: FONT.sizes.lg,
    color: COLORS.text,
    fontWeight: '700',
    textAlign: 'center',
  },
  delayUnit: { fontSize: FONT.sizes.sm, color: COLORS.muted },
  saveBtn: {
    backgroundColor: COLORS.primary,
    paddingVertical: SPACING.md,
    borderRadius: RADIUS.md,
    alignItems: 'center',
    marginTop: SPACING.sm,
  },
  saveText: { color: '#fff', fontSize: FONT.sizes.md, fontWeight: '700' },
});
