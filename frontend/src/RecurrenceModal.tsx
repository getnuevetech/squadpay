/**
 * RecurrenceModal — lead-only sheet to configure auto-recurring squads.
 *
 * Lets the lead pick Weekly (with day-of-week) or Monthly (with day-of-month),
 * shows the next scheduled clone date, and offers a "skip when last one is
 * still open" toggle. Saves via api.setRecurrence / api.disableRecurrence.
 *
 * Why a separate sheet? Recurrence touches a different mental model than the
 * one-time bill: it sets a SCHEDULE, not the current bill. Keeping it in its
 * own modal avoids confusing the lead into thinking they're editing this
 * bill's amount/items when they tap Weekly.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { X, Repeat, Calendar } from 'lucide-react-native';
import { api } from './api';
import { COLORS, FONT, RADIUS, SPACING } from './theme';
import { toast } from './components/Toast';

type Cadence = 'weekly' | 'monthly';

interface Props {
  visible: boolean;
  groupId: string;
  userId: string;
  onClose: () => void;
  onChanged?: () => void;
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function formatDate(iso?: string | null): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export function RecurrenceModal({ visible, groupId, userId, onClose, onChanged }: Props) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [cadence, setCadence] = useState<Cadence>('weekly');
  const [anchor, setAnchor] = useState<number>(0); // weekly Mon, or monthly day-1
  const [skipIfOpen, setSkipIfOpen] = useState(false);
  const [nextRunAt, setNextRunAt] = useState<string | null>(null);
  const [lastRunAt, setLastRunAt] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) return;
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const rec = await api.getRecurrence(groupId, userId);
        if (!alive) return;
        setEnabled(!!rec.enabled);
        setCadence((rec.cadence as Cadence) || 'weekly');
        setAnchor(rec.anchor ?? 0);
        setSkipIfOpen(!!rec.skip_if_open);
        setNextRunAt(rec.next_run_at || null);
        setLastRunAt(rec.last_run_at || null);
      } catch (e: any) {
        toast.error(e?.message || 'Could not load recurrence');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [visible, groupId, userId]);

  // Sensible default anchor when cadence flips.
  useEffect(() => {
    if (cadence === 'weekly' && anchor > 6) setAnchor(0);
    if (cadence === 'monthly' && anchor < 1) setAnchor(1);
  }, [cadence, anchor]);

  const save = async () => {
    setSaving(true);
    try {
      if (!enabled) {
        await api.disableRecurrence(groupId, userId);
        toast.success('Recurrence turned off');
      } else {
        const res = await api.setRecurrence(groupId, {
          user_id: userId,
          enabled: true,
          cadence,
          anchor,
          skip_if_open: skipIfOpen,
        });
        setNextRunAt(res.next_run_at || null);
        toast.success(`Next bill: ${formatDate(res.next_run_at)}`);
      }
      onChanged?.();
      onClose();
    } catch (e: any) {
      toast.error(e?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const anchorLabel = useMemo(() => {
    if (cadence === 'weekly') return `Every ${WEEKDAYS[anchor] || 'Mon'}`;
    const day = Math.max(1, Math.min(31, anchor || 1));
    const suffix = day === 1 || day === 21 || day === 31 ? 'st'
      : day === 2 || day === 22 ? 'nd'
        : day === 3 || day === 23 ? 'rd' : 'th';
    return `On the ${day}${suffix} of every month`;
  }, [cadence, anchor]);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={onClose} testID="recurrence-backdrop">
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
          <View style={styles.header}>
            <View style={styles.headerIcon}>
              <Repeat size={18} color={COLORS.primary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>Recurring bill</Text>
              <Text style={styles.sub}>Auto-create a fresh copy on a schedule.</Text>
            </View>
            <TouchableOpacity onPress={onClose} hitSlop={10} testID="recurrence-close">
              <X size={20} color={COLORS.text} />
            </TouchableOpacity>
          </View>

          {loading ? (
            <View style={styles.center}>
              <ActivityIndicator color={COLORS.primary} />
            </View>
          ) : (
            <ScrollView style={{ maxHeight: 480 }}>
              <View style={styles.toggleRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.toggleLabel}>Enable recurrence</Text>
                  <Text style={styles.toggleHint}>
                    {enabled
                      ? 'A new bill will be created automatically.'
                      : 'No new bills will be created.'}
                  </Text>
                </View>
                <Switch
                  testID="recurrence-toggle"
                  value={enabled}
                  onValueChange={setEnabled}
                  trackColor={{ false: COLORS.border, true: COLORS.primary }}
                  thumbColor={Platform.OS === 'android' ? '#fff' : undefined}
                />
              </View>

              {enabled && (
                <>
                  <Text style={styles.section}>Cadence</Text>
                  <View style={styles.tabsRow}>
                    {(['weekly', 'monthly'] as Cadence[]).map((c) => (
                      <TouchableOpacity
                        key={c}
                        testID={`recurrence-cadence-${c}`}
                        onPress={() => setCadence(c)}
                        style={[styles.tab, cadence === c && styles.tabActive]}
                      >
                        <Text style={[styles.tabText, cadence === c && styles.tabTextActive]}>
                          {c === 'weekly' ? 'Weekly' : 'Monthly'}
                        </Text>
                      </TouchableOpacity>
                    ))}
                  </View>

                  {cadence === 'weekly' ? (
                    <View style={styles.gridRow}>
                      {WEEKDAYS.map((d, i) => {
                        const active = anchor === i;
                        return (
                          <TouchableOpacity
                            key={d}
                            onPress={() => setAnchor(i)}
                            style={[styles.dayChip, active && styles.dayChipActive]}
                            testID={`recurrence-weekday-${i}`}
                          >
                            <Text style={[styles.dayChipText, active && styles.dayChipTextActive]}>
                              {d}
                            </Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                  ) : (
                    <View style={styles.gridRow}>
                      {Array.from({ length: 31 }, (_, k) => k + 1).map((day) => {
                        const active = anchor === day;
                        return (
                          <TouchableOpacity
                            key={day}
                            onPress={() => setAnchor(day)}
                            style={[styles.dayChipSm, active && styles.dayChipActive]}
                            testID={`recurrence-monthday-${day}`}
                          >
                            <Text style={[styles.dayChipText, active && styles.dayChipTextActive]}>
                              {day}
                            </Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                  )}

                  <View style={styles.previewCard}>
                    <Calendar size={14} color={COLORS.subtext} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.previewTitle}>{anchorLabel}</Text>
                      {nextRunAt ? (
                        <Text style={styles.previewSub}>
                          Next: {formatDate(nextRunAt)}
                        </Text>
                      ) : null}
                      {lastRunAt ? (
                        <Text style={styles.previewSub}>
                          Last: {formatDate(lastRunAt)}
                        </Text>
                      ) : null}
                    </View>
                  </View>

                  <View style={styles.toggleRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.toggleLabel}>Skip if last one is still open</Text>
                      <Text style={styles.toggleHint}>
                        Avoid stacking bills when members are behind on payment.
                      </Text>
                    </View>
                    <Switch
                      testID="recurrence-skip-open"
                      value={skipIfOpen}
                      onValueChange={setSkipIfOpen}
                      trackColor={{ false: COLORS.border, true: COLORS.primary }}
                      thumbColor={Platform.OS === 'android' ? '#fff' : undefined}
                    />
                  </View>
                </>
              )}

              <TouchableOpacity
                testID="recurrence-save"
                style={styles.saveBtn}
                onPress={save}
                disabled={saving}
              >
                {saving ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.saveBtnText}>Save schedule</Text>
                )}
              </TouchableOpacity>
            </ScrollView>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(15,23,42,0.55)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: COLORS.surface,
    borderTopLeftRadius: RADIUS.xl,
    borderTopRightRadius: RADIUS.xl,
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.lg,
    paddingBottom: SPACING.xl,
    maxHeight: '92%',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    marginBottom: SPACING.md,
  },
  headerIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: COLORS.primaryLight,
    alignItems: 'center', justifyContent: 'center',
  },
  title: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.heavy, color: COLORS.text },
  sub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 2 },
  center: { alignItems: 'center', justifyContent: 'center', paddingVertical: SPACING.xl },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: SPACING.sm,
    gap: SPACING.md,
  },
  toggleLabel: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  toggleHint: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  section: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    fontWeight: FONT.weights.bold,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: SPACING.md,
    marginBottom: SPACING.sm,
  },
  tabsRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.md },
  tab: {
    flex: 1,
    paddingVertical: SPACING.sm,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.bg,
    borderWidth: 1,
    borderColor: COLORS.border,
    alignItems: 'center',
  },
  tabActive: { backgroundColor: COLORS.primaryLight, borderColor: COLORS.primary },
  tabText: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  tabTextActive: { color: COLORS.primary },
  gridRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: SPACING.md,
  },
  dayChip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.bg,
    borderWidth: 1,
    borderColor: COLORS.border,
    minWidth: 56,
    alignItems: 'center',
  },
  dayChipSm: {
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: RADIUS.sm,
    backgroundColor: COLORS.bg,
    borderWidth: 1,
    borderColor: COLORS.border,
    minWidth: 38,
    alignItems: 'center',
  },
  dayChipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  dayChipText: { fontSize: FONT.sizes.sm, color: COLORS.text, fontWeight: FONT.weights.semibold },
  dayChipTextActive: { color: '#fff' },
  previewCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    padding: SPACING.md,
    backgroundColor: COLORS.bg,
    borderRadius: RADIUS.md,
    marginBottom: SPACING.md,
  },
  previewTitle: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold, color: COLORS.text },
  previewSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  saveBtn: {
    marginTop: SPACING.lg,
    height: 50,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
});
