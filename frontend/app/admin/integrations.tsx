import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, Switch } from 'react-native';
import { CreditCard, MessageSquare, Bell, Save, Send, Play, CheckCircle2, XCircle, AlertCircle } from 'lucide-react-native';
import { adminApi, IntegrationsView } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <View style={[styles.pill, { backgroundColor: ok ? COLORS.successLight : COLORS.disabledBg }]}>
      {ok ? <CheckCircle2 size={11} color={COLORS.success} /> : <XCircle size={11} color={COLORS.subtext} />}
      <Text style={[styles.pillText, { color: ok ? COLORS.success : COLORS.subtext }]}>{label}</Text>
    </View>
  );
}

export default function AdminIntegrations() {
  const [view, setView] = useState<IntegrationsView | null>(null);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);

  // Stripe form
  const [stEnabled, setStEnabled] = useState(false);
  const [stMode, setStMode] = useState<'test' | 'live'>('test');
  const [stPub, setStPub] = useState('');
  const [stSec, setStSec] = useState('');
  const [stWh, setStWh] = useState('');

  // Twilio form
  const [twEnabled, setTwEnabled] = useState(false);
  const [twSid, setTwSid] = useState('');
  const [twTok, setTwTok] = useState('');
  const [twFrom, setTwFrom] = useState('');
  const [testTo, setTestTo] = useState('');
  const [testInfo, setTestInfo] = useState<string | null>(null);

  // Reminders form
  const [rmEnabled, setRmEnabled] = useState(false);
  const [rmHours, setRmHours] = useState('24,72,168');
  const [rmMax, setRmMax] = useState('3');
  const [rmSms, setRmSms] = useState(true);
  const [runResult, setRunResult] = useState<string | null>(null);

  // Issuing form (Phase F1)
  const [issEnabled, setIssEnabled] = useState(true);
  const [issName, setIssName] = useState('KWIKPAY');
  const [issDisableMode, setIssDisableMode] = useState<'auto' | 'manual'>('auto');
  const [issCardholderId, setIssCardholderId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const v = await adminApi.getIntegrations();
      setView(v);
      setStEnabled(v.stripe.enabled);
      setStMode(v.stripe.mode);
      setStPub(v.stripe.publishable_key || '');
      setStSec('');
      setStWh('');
      setTwEnabled(v.twilio.enabled);
      setTwSid('');
      setTwTok('');
      setTwFrom(v.twilio.from_number || '');
      setRmEnabled(v.reminders.enabled);
      setRmHours((v.reminders.schedule_hours || []).join(','));
      setRmMax(String(v.reminders.max_reminders_per_user || 3));
      setRmSms(v.reminders.send_via_sms);
      // Phase F1: Issuing
      try {
        const iss = await adminApi.getIssuingSettings();
        setIssEnabled(!!iss.enabled);
        setIssName(iss.cardholder_name || 'KWIKPAY');
        setIssDisableMode(iss.card_disable_mode || 'auto');
        setIssCardholderId(iss.cardholder_id || null);
      } catch {}
    } catch (e: any) {
      Alert.alert('Error', e?.message || 'Failed to load');
    } finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const saveStripe = async () => {
    setSaving('stripe');
    try {
      await adminApi.setStripe({
        enabled: stEnabled,
        mode: stMode,
        publishable_key: stPub,
        secret_key: stSec || undefined,
        webhook_secret: stWh || undefined,
      });
      await load();
      Alert.alert('Saved', `Stripe ${stEnabled ? 'enabled' : 'disabled'} (${stMode})`);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setSaving(null); }  };

  const saveTwilio = async () => {
    setSaving('twilio');
    try {
      await adminApi.setTwilio({
        enabled: twEnabled,
        account_sid: twSid || undefined,
        auth_token: twTok || undefined,
        from_number: twFrom || undefined,
      });
      await load();
      Alert.alert('Saved', `Twilio ${twEnabled ? 'enabled' : 'disabled'}`);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setSaving(null); }
  };

  const sendTest = async () => {
    if (!testTo) { Alert.alert('Phone required', 'Enter a destination phone number to send the test SMS.'); return; }
    setSaving('test');
    try {
      const r = await adminApi.testTwilio(testTo);
      setTestInfo(r.sent_real ? `✓ Sent — ${r.info}` : `(mocked) ${r.info}`);
    } catch (e: any) { setTestInfo(`✗ ${e?.message || 'Failed'}`); }
    finally { setSaving(null); }
  };

  const saveReminders = async () => {
    setSaving('rem');
    try {
      const hours = rmHours.split(',').map((s) => parseInt(s.trim(), 10)).filter((n) => Number.isFinite(n) && n > 0);
      if (hours.length === 0) { Alert.alert('Invalid', 'Add at least one positive hour value (e.g. 24,72,168)'); setSaving(null); return; }
      const max = parseInt(rmMax, 10);
      if (!Number.isFinite(max) || max < 1) { Alert.alert('Invalid', 'Max reminders ≥ 1'); setSaving(null); return; }
      await adminApi.setReminders({
        enabled: rmEnabled,
        schedule_hours: hours,
        max_reminders_per_user: max,
        send_via_sms: rmSms,
      });
      await load();
      Alert.alert('Saved', 'Reminder schedule updated');
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setSaving(null); }
  };

  const runNow = async () => {
    setSaving('run');
    try {
      const r = await adminApi.runRemindersNow();
      setRunResult(`Scanned ${r.scanned} groups • sent_real=${r.sent_real} • logged=${r.logged} • skipped=${r.skipped}`);
    } catch (e: any) { setRunResult(`Error: ${e?.message || 'Failed'}`); }
    finally { setSaving(null); }
  };

  const saveIssuing = async () => {
    setSaving('iss');
    try {
      await adminApi.setIssuingSettings({
        enabled: issEnabled,
        cardholder_name: issName.trim() || 'KWIKPAY',
        card_disable_mode: issDisableMode,
      });
      await load();
      Alert.alert('Saved', `Issuing ${issEnabled ? 'enabled' : 'disabled'} · disable mode: ${issDisableMode}`);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setSaving(null); }
  };
    finally { setSaving(null); }
  };

  if (busy || !view) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="admin-integrations-heading">Integrations</Text>
      <Text style={styles.subheading}>Configure Stripe, Twilio (SMS/OTP), and reminder schedules. Secrets are encrypted at rest and only the last 4 chars are shown after save.</Text>

      {/* Stripe */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={styles.cardIcon}><CreditCard size={18} color="#635BFF" /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle}>Stripe</Text>
            <Text style={styles.cardSub}>Payment processing — virtual card & charge integration (deferred to next phase, keys stored now).</Text>
          </View>
          <View style={{ flexDirection: 'row', gap: 6 }}>
            <StatusPill ok={view.stripe.enabled} label={view.stripe.enabled ? 'Enabled' : 'Disabled'} />
            <StatusPill ok={view.stripe.secret_key_set} label={view.stripe.secret_key_set ? 'Keys set' : 'Not configured'} />
          </View>
        </View>

        <View style={styles.toggleRow}>
          <Text style={styles.label}>Enable Stripe</Text>
          <Switch value={stEnabled} onValueChange={setStEnabled} trackColor={{ false: COLORS.disabledBg, true: '#635BFF' }} thumbColor="#fff" testID="admin-stripe-enable" />
        </View>

        <View style={styles.formRow}>
          <TouchableOpacity onPress={() => setStMode('test')} style={[styles.toggle, stMode === 'test' && styles.toggleActive]} activeOpacity={0.85}>
            <Text style={[styles.toggleText, stMode === 'test' && { color: '#fff' }]}>Test mode</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setStMode('live')} style={[styles.toggle, stMode === 'live' && styles.toggleActive]} activeOpacity={0.85}>
            <Text style={[styles.toggleText, stMode === 'live' && { color: '#fff' }]}>Live mode</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.label}>Publishable key</Text>
        <TextInput style={styles.input} value={stPub} onChangeText={setStPub} placeholder="pk_test_…" placeholderTextColor={COLORS.disabledText} testID="admin-stripe-pub" />
        <Text style={styles.label}>Secret key {view.stripe.secret_key_set ? <Text style={styles.maskedHint}>(saved: {view.stripe.secret_key_masked} — leave blank to keep)</Text> : null}</Text>
        <TextInput style={styles.input} value={stSec} onChangeText={setStSec} placeholder="sk_test_…" placeholderTextColor={COLORS.disabledText} secureTextEntry testID="admin-stripe-sec" />
        <Text style={styles.label}>Webhook secret {view.stripe.webhook_secret_set ? <Text style={styles.maskedHint}>(saved: {view.stripe.webhook_secret_masked} — leave blank to keep)</Text> : null}</Text>
        <TextInput style={styles.input} value={stWh} onChangeText={setStWh} placeholder="whsec_…" placeholderTextColor={COLORS.disabledText} secureTextEntry testID="admin-stripe-wh" />

        <TouchableOpacity onPress={saveStripe} disabled={saving === 'stripe'} style={[styles.saveBtn, { backgroundColor: '#635BFF', opacity: saving === 'stripe' ? 0.6 : 1 }]} activeOpacity={0.85} testID="admin-stripe-save">
          <Save size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'stripe' ? 'Saving…' : 'Save Stripe settings'}</Text>
        </TouchableOpacity>
        {view.stripe.updated_at ? <Text style={styles.metaSmall}>Last updated {new Date(view.stripe.updated_at).toLocaleString()} by {view.stripe.updated_by}</Text> : null}
      </View>

      {/* Issuing — Phase F1 */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={styles.cardIcon}><CreditCard size={18} color="#0EA5E9" /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle}>Stripe Issuing (Virtual cards)</Text>
            <Text style={styles.cardSub}>Auto-issue a real Stripe-issued virtual card per fully-funded group. Cardholder = your business (KWIKPAY). Cards are auto-cancelled after group settles or admin can disable manually.</Text>
          </View>
          <View style={{ flexDirection: 'row', gap: 6 }}>
            <StatusPill ok={issEnabled} label={issEnabled ? 'Enabled' : 'Disabled'} />
            <StatusPill ok={!!issCardholderId} label={issCardholderId ? 'Cardholder linked' : 'Cardholder missing'} />
          </View>
        </View>

        <View style={styles.toggleRow}>
          <Text style={styles.label}>Enable Issuing</Text>
          <Switch value={issEnabled} onValueChange={setIssEnabled} trackColor={{ false: COLORS.disabledBg, true: '#0EA5E9' }} thumbColor="#fff" testID="admin-issuing-enable" />
        </View>

        <Text style={styles.label}>Business name (used as card nickname prefix)</Text>
        <TextInput style={styles.input} value={issName} onChangeText={setIssName} placeholder="KWIKPAY" placeholderTextColor={COLORS.disabledText} testID="admin-issuing-name" />
        <Text style={styles.helper}>Each group's card will be named "{issName.trim() || 'KWIKPAY'} - {'{Group title}'}".</Text>

        <Text style={styles.label}>Card disable mode</Text>
        <View style={styles.formRow}>
          <TouchableOpacity onPress={() => setIssDisableMode('auto')} style={[styles.toggle, issDisableMode === 'auto' && styles.toggleActive]} activeOpacity={0.85} testID="admin-issuing-mode-auto">
            <Text style={[styles.toggleText, issDisableMode === 'auto' && { color: '#fff' }]}>Auto · disable after merchant settlement</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setIssDisableMode('manual')} style={[styles.toggle, issDisableMode === 'manual' && styles.toggleActive]} activeOpacity={0.85} testID="admin-issuing-mode-manual">
            <Text style={[styles.toggleText, issDisableMode === 'manual' && { color: '#fff' }]}>Manual · admin disables only</Text>
          </TouchableOpacity>
        </View>

        {issCardholderId ? (
          <Text style={styles.metaSmall}>Cardholder: {issCardholderId}</Text>
        ) : (
          <Text style={[styles.metaSmall, { color: COLORS.warning }]}>
            No active cardholder linked. Create one in Stripe Dashboard → Issuing → Cardholders.
          </Text>
        )}

        <TouchableOpacity onPress={saveIssuing} disabled={saving === 'iss'} style={[styles.saveBtn, { backgroundColor: '#0EA5E9', opacity: saving === 'iss' ? 0.6 : 1 }]} activeOpacity={0.85} testID="admin-issuing-save">
          <Save size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'iss' ? 'Saving…' : 'Save Issuing settings'}</Text>
        </TouchableOpacity>
      </View>

      {/* Twilio */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={styles.cardIcon}><MessageSquare size={18} color="#F22F46" /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle}>Twilio (SMS / OTP)</Text>
            <Text style={styles.cardSub}>When enabled, OTP codes & reminders are sent as real SMS via Twilio. Mock OTP code 123456 still works for testing.</Text>
          </View>
          <View style={{ flexDirection: 'row', gap: 6 }}>
            <StatusPill ok={view.twilio.enabled} label={view.twilio.enabled ? 'Enabled' : 'Disabled'} />
            <StatusPill ok={view.twilio.account_sid_set} label={view.twilio.account_sid_set ? 'Configured' : 'Not configured'} />
          </View>
        </View>

        <View style={styles.toggleRow}>
          <Text style={styles.label}>Enable Twilio</Text>
          <Switch value={twEnabled} onValueChange={setTwEnabled} trackColor={{ false: COLORS.disabledBg, true: '#F22F46' }} thumbColor="#fff" testID="admin-twilio-enable" />
        </View>

        <Text style={styles.label}>Account SID {view.twilio.account_sid_set ? <Text style={styles.maskedHint}>(saved: {view.twilio.account_sid_masked} — leave blank to keep)</Text> : null}</Text>
        <TextInput style={styles.input} value={twSid} onChangeText={setTwSid} placeholder="ACxxxxxxxxxxxxxxxx" placeholderTextColor={COLORS.disabledText} testID="admin-twilio-sid" />
        <Text style={styles.label}>Auth token {view.twilio.auth_token_set ? <Text style={styles.maskedHint}>(saved: {view.twilio.auth_token_masked} — leave blank to keep)</Text> : null}</Text>
        <TextInput style={styles.input} value={twTok} onChangeText={setTwTok} placeholder="…" placeholderTextColor={COLORS.disabledText} secureTextEntry testID="admin-twilio-tok" />
        <Text style={styles.label}>From number (E.164)</Text>
        <TextInput style={styles.input} value={twFrom} onChangeText={setTwFrom} placeholder="+15555550000" placeholderTextColor={COLORS.disabledText} testID="admin-twilio-from" />

        <View style={styles.btnRow}>
          <TouchableOpacity onPress={saveTwilio} disabled={saving === 'twilio'} style={[styles.saveBtn, { flex: 2, backgroundColor: '#F22F46', opacity: saving === 'twilio' ? 0.6 : 1 }]} activeOpacity={0.85} testID="admin-twilio-save">
            <Save size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'twilio' ? 'Saving…' : 'Save Twilio'}</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.divider} />
        <Text style={styles.label}>Send test SMS</Text>
        <View style={styles.formRow}>
          <TextInput style={[styles.input, { flex: 1, marginTop: 0 }]} value={testTo} onChangeText={setTestTo} placeholder="+15551234567" placeholderTextColor={COLORS.disabledText} testID="admin-twilio-test-to" />
          <TouchableOpacity onPress={sendTest} disabled={saving === 'test'} style={[styles.saveBtn, { backgroundColor: COLORS.primary, opacity: saving === 'test' ? 0.6 : 1, paddingHorizontal: 18 }]} activeOpacity={0.85} testID="admin-twilio-test-send">
            <Send size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'test' ? '…' : 'Send'}</Text>
          </TouchableOpacity>
        </View>
        {testInfo ? (
          <View style={[styles.infoBox, testInfo.startsWith('✓') ? { backgroundColor: COLORS.successLight } : { backgroundColor: COLORS.warningLight }]}>
            <AlertCircle size={12} color={COLORS.text} />
            <Text style={styles.infoText}>{testInfo}</Text>
          </View>
        ) : null}
        {view.twilio.updated_at ? <Text style={styles.metaSmall}>Last updated {new Date(view.twilio.updated_at).toLocaleString()} by {view.twilio.updated_by}</Text> : null}
      </View>

      {/* Reminders */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={styles.cardIcon}><Bell size={18} color={COLORS.warning} /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle}>Reminders</Text>
            <Text style={styles.cardSub}>Auto-nudge group members who haven't paid yet. Runs every 15 minutes in the background.</Text>
          </View>
          <StatusPill ok={view.reminders.enabled} label={view.reminders.enabled ? 'On' : 'Off'} />
        </View>

        <View style={styles.toggleRow}>
          <Text style={styles.label}>Enable reminders</Text>
          <Switch value={rmEnabled} onValueChange={setRmEnabled} trackColor={{ false: COLORS.disabledBg, true: COLORS.warning }} thumbColor="#fff" testID="admin-reminders-enable" />
        </View>

        <Text style={styles.label}>Schedule (hours after group creation, comma-separated)</Text>
        <TextInput style={styles.input} value={rmHours} onChangeText={setRmHours} placeholder="24,72,168" placeholderTextColor={COLORS.disabledText} testID="admin-reminders-hours" />
        <Text style={styles.helper}>Default: 24h, 72h (3d), 168h (7d). Each member gets at most one reminder per offset.</Text>

        <View style={styles.formRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Max reminders / user / group</Text>
            <TextInput style={styles.input} value={rmMax} onChangeText={setRmMax} keyboardType="number-pad" testID="admin-reminders-max" />
          </View>
          <View style={[styles.toggleRow, { flex: 1, marginTop: 0 }]}>
            <Text style={styles.label}>Send via SMS</Text>
            <Switch value={rmSms} onValueChange={setRmSms} trackColor={{ false: COLORS.disabledBg, true: COLORS.primary }} thumbColor="#fff" testID="admin-reminders-sms" />
          </View>
        </View>

        <View style={styles.btnRow}>
          <TouchableOpacity onPress={saveReminders} disabled={saving === 'rem'} style={[styles.saveBtn, { flex: 1, backgroundColor: COLORS.warning, opacity: saving === 'rem' ? 0.6 : 1 }]} activeOpacity={0.85} testID="admin-reminders-save">
            <Save size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'rem' ? 'Saving…' : 'Save reminders'}</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={runNow} disabled={saving === 'run'} style={[styles.saveBtn, { flex: 1, backgroundColor: COLORS.primary, opacity: saving === 'run' ? 0.6 : 1 }]} activeOpacity={0.85} testID="admin-reminders-run">
            <Play size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'run' ? 'Running…' : 'Run now'}</Text>
          </TouchableOpacity>
        </View>
        {runResult ? (
          <View style={[styles.infoBox, { backgroundColor: COLORS.primaryLight }]}>
            <AlertCircle size={12} color={COLORS.primary} />
            <Text style={[styles.infoText, { color: COLORS.primary }]}>{runResult}</Text>
          </View>
        ) : null}
        {view.reminders.updated_at ? <Text style={styles.metaSmall}>Last updated {new Date(view.reminders.updated_at).toLocaleString()} by {view.reminders.updated_by}</Text> : null}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.lg },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.md },
  cardHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginBottom: SPACING.sm, flexWrap: 'wrap' },
  cardIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: COLORS.bg, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: COLORS.border },
  cardTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  cardSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: RADIUS.pill },
  pillText: { fontSize: 10, fontWeight: FONT.weights.bold },
  toggleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: SPACING.sm, marginTop: 4 },
  label: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.semibold, marginTop: SPACING.sm },
  helper: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 4, fontStyle: 'italic' },
  maskedHint: { color: COLORS.subtext, fontWeight: FONT.weights.regular, fontSize: 11 },
  input: { height: 40, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.bg, marginTop: 6, outlineStyle: 'none' as any },
  formRow: { flexDirection: 'row', gap: SPACING.sm, alignItems: 'flex-end', flexWrap: 'wrap' },
  toggle: { paddingHorizontal: SPACING.md, paddingVertical: 8, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  toggleActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  toggleText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold, color: COLORS.text },
  divider: { height: 1, backgroundColor: COLORS.border, marginVertical: SPACING.md },
  saveBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, height: 42, borderRadius: RADIUS.md, marginTop: SPACING.sm, paddingHorizontal: SPACING.md },
  saveBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  btnRow: { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.sm },
  metaSmall: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: SPACING.sm, fontStyle: 'italic' },
  infoBox: { flexDirection: 'row', alignItems: 'center', gap: 6, padding: SPACING.sm, marginTop: SPACING.sm, borderRadius: RADIUS.sm },
  infoText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.semibold, flex: 1 },
});
