import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, Switch } from 'react-native';
import { CreditCard, MessageSquare, Bell, Save, Send, Play, CheckCircle2, XCircle, AlertCircle, Radio } from 'lucide-react-native';
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

  // SignalWire form (Phase F2.2 — Twilio alternative)
  const [swEnabled, setSwEnabled] = useState(false);
  const [swProject, setSwProject] = useState('');
  const [swToken, setSwToken] = useState('');
  const [swSpace, setSwSpace] = useState('');
  const [swFrom, setSwFrom] = useState('');
  const [swTestTo, setSwTestTo] = useState('');
  const [swTestInfo, setSwTestInfo] = useState<string | null>(null);

  // SMS Routing (primary + fallback)
  const [smsPrimary, setSmsPrimary] = useState<'twilio' | 'signalwire'>('twilio');
  const [smsFallback, setSmsFallback] = useState<'twilio' | 'signalwire' | 'none'>('none');

  // Phase H6 — global SMS mode (mock | live)
  const [smsMode, setSmsMode] = useState<'mock' | 'live'>('mock');

  // Reminders form
  const [rmEnabled, setRmEnabled] = useState(false);
  const [rmHours, setRmHours] = useState('24,72,168');
  const [rmMax, setRmMax] = useState('3');
  const [rmSms, setRmSms] = useState(true);
  const [runResult, setRunResult] = useState<string | null>(null);

  // Issuing form (Phase F1+F2)
  const [issEnabled, setIssEnabled] = useState(true);
  const [issName, setIssName] = useState('KWIKPAY');
  const [issDisableMode, setIssDisableMode] = useState<'auto' | 'manual'>('auto');
  const [issCardholderId, setIssCardholderId] = useState<string | null>(null);
  const [issRequireOtp, setIssRequireOtp] = useState(true);
  const [issRevealTtl, setIssRevealTtl] = useState('60');
  const [issWebhookSecret, setIssWebhookSecret] = useState('');
  // Phase G3 — per-lead cardholder mode
  const [issRequireLeadKyc, setIssRequireLeadKyc] = useState(false);
  // Phase G4 — push provisioning enrollment toggles
  const [issAppleEnrolled, setIssAppleEnrolled] = useState(false);
  const [issGoogleEnrolled, setIssGoogleEnrolled] = useState(false);

  // Feature toggles
  const [featCredits, setFeatCredits] = useState(true);
  const [featInvite, setFeatInvite] = useState(true);

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
      // Phase F2.2: SignalWire + routing
      setSwEnabled(!!v.signalwire?.enabled);
      setSwProject('');
      setSwToken('');
      setSwSpace(v.signalwire?.space_url || '');
      setSwFrom(v.signalwire?.from_number || '');
      setSmsPrimary((v.sms_routing?.primary as any) || 'twilio');
      setSmsFallback((v.sms_routing?.fallback as any) || 'none');
      setSmsMode((v.sms_routing?.mode as any) || 'mock');
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
        setIssRequireOtp((iss as any).require_otp_for_card_reveal !== false);
        setIssRevealTtl(String((iss as any).reveal_ttl_seconds || 60));
        setIssWebhookSecret(((iss as any).webhook_secret_masked) || '');
        setIssRequireLeadKyc(!!(iss as any).require_lead_kyc);
        setIssAppleEnrolled(!!(iss as any).apple_pay_enrolled);
        setIssGoogleEnrolled(!!(iss as any).google_pay_enrolled);
      } catch {}
      try {
        const f = await adminApi.getFeatures();
        setFeatCredits(f.credits_enabled !== false);
        setFeatInvite(f.invite_friends_enabled !== false);
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

  // --- Phase F2.2: SignalWire ---
  const saveSignalWire = async () => {
    setSaving('sw');
    try {
      await adminApi.setSignalWire({
        enabled: swEnabled,
        project_id: swProject || undefined,
        api_token: swToken || undefined,
        space_url: swSpace || undefined,
        from_number: swFrom || undefined,
      });
      await load();
      Alert.alert('Saved', `SignalWire ${swEnabled ? 'enabled' : 'disabled'}`);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setSaving(null); }
  };

  const sendTestSw = async () => {
    if (!swTestTo) { Alert.alert('Phone required', 'Enter a destination phone number to send the test SMS.'); return; }
    setSaving('sw-test');
    try {
      const r = await adminApi.testSignalWire(swTestTo);
      setSwTestInfo(r.sent_real ? `✓ Sent — ${r.info}` : `✗ ${r.info}`);
    } catch (e: any) { setSwTestInfo(`✗ ${e?.message || 'Failed'}`); }
    finally { setSaving(null); }
  };

  const saveSmsRouting = async () => {
    if (smsFallback !== 'none' && smsFallback === smsPrimary) {
      Alert.alert('Invalid routing', 'Fallback must be different from primary.');
      return;
    }
    setSaving('routing');
    try {
      await adminApi.setSmsRouting({
        primary: smsPrimary,
        fallback: smsFallback === 'none' ? null : smsFallback,
      });
      await load();
      Alert.alert(
        'Saved',
        `Primary: ${smsPrimary}${smsFallback === 'none' ? '' : ` · Fallback: ${smsFallback}`}`,
      );
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setSaving(null); }
  };

  // Phase H6 — SMS Mode (mock | live)
  const saveSmsMode = async (mode: 'mock' | 'live') => {
    if (mode === smsMode) return;
    if (mode === 'live') {
      const proceed = await new Promise<boolean>((resolve) => {
        Alert.alert(
          'Switch to Live SMS?',
          'All OTP and reminder SMS will be sent via the configured provider — real charges may apply. You can switch back to Mock anytime.',
          [
            { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
            { text: 'Go Live', style: 'destructive', onPress: () => resolve(true) },
          ],
          { cancelable: false },
        );
      });
      if (!proceed) return;
    }
    setSaving('smsMode');
    try {
      const v = await adminApi.setSmsMode(mode);
      setView(v);
      setSmsMode(mode);
      Alert.alert('SMS Mode', mode === 'live' ? '📡 Live SMS — provider active' : '🧪 Mock SMS — no real SMS will be sent');
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
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
        require_otp_for_card_reveal: issRequireOtp,
        reveal_ttl_seconds: parseInt(issRevealTtl, 10) || 60,
        webhook_secret: issWebhookSecret.startsWith('whsec_') ? issWebhookSecret : undefined,
        require_lead_kyc: issRequireLeadKyc,
        apple_pay_enrolled: issAppleEnrolled,
        google_pay_enrolled: issGoogleEnrolled,
      });
      await load();
      Alert.alert('Saved', `Issuing ${issEnabled ? 'enabled' : 'disabled'} · disable mode: ${issDisableMode}`);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setSaving(null); }
  };

  const saveFeatures = async () => {
    setSaving('feat');
    try {
      await adminApi.setFeatures({ credits_enabled: featCredits, invite_friends_enabled: featInvite });
      Alert.alert('Saved', `Features updated · Credits: ${featCredits ? 'on' : 'off'} · Invite: ${featInvite ? 'on' : 'off'}`);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
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

        <View style={styles.toggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Require OTP before card reveal</Text>
            <Text style={styles.helper}>Lead must enter a 6-digit SMS code before PAN/CVV is shown.</Text>
          </View>
          <Switch value={issRequireOtp} onValueChange={setIssRequireOtp} trackColor={{ false: COLORS.disabledBg, true: '#0EA5E9' }} thumbColor="#fff" testID="admin-issuing-otp-toggle" />
        </View>

        <Text style={styles.label}>Auto-hide PAN after (seconds)</Text>
        <TextInput
          style={styles.input}
          value={issRevealTtl}
          onChangeText={(t) => setIssRevealTtl(t.replace(/[^0-9]/g, '').slice(0, 4))}
          keyboardType="number-pad"
          placeholder="60"
          placeholderTextColor={COLORS.disabledText}
          testID="admin-issuing-ttl"
        />

        <Text style={styles.label}>Issuing webhook signing secret</Text>
        <TextInput
          style={styles.input}
          value={issWebhookSecret}
          onChangeText={setIssWebhookSecret}
          placeholder="whsec_…  (paste from Stripe Dashboard → Webhooks)"
          placeholderTextColor={COLORS.disabledText}
          autoCapitalize="none"
          testID="admin-issuing-webhook-secret"
        />
        <Text style={styles.helper}>
          Webhook URL to register in Stripe Dashboard → Developers → Webhooks → Add endpoint:
          {`\n${typeof window !== 'undefined' ? (window as any).location?.origin : ''}/api/webhook/stripe/issuing`}
          {`\n\nEvents to subscribe: issuing_authorization.created, issuing_transaction.created`}
        </Text>

        {issCardholderId ? (
          <Text style={styles.metaSmall}>Cardholder: {issCardholderId}</Text>
        ) : (
          <Text style={[styles.metaSmall, { color: COLORS.warning }]}>
            No active cardholder linked. Create one in Stripe Dashboard → Issuing → Cardholders.
          </Text>
        )}

        {/* Phase G3 — per-lead cardholder mode (KYC) */}
        <View style={styles.divider} />
        <View style={styles.toggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Require lead KYC (per-lead cardholders)</Text>
            <Text style={styles.helper}>
              When OFF — all groups share the single business cardholder above.{`\n`}
              When ON — each group's lead gets their own Stripe Issuing cardholder, keyed to
              the lead's verified phone + name. In Test Mode, individual cardholders go straight
              to status="active". In Live Mode, Stripe will require KYC docs (integrate Stripe
              Identity separately) before a card can be issued for that lead.
            </Text>
          </View>
          <Switch
            value={issRequireLeadKyc}
            onValueChange={setIssRequireLeadKyc}
            trackColor={{ false: COLORS.disabledBg, true: '#0EA5E9' }}
            thumbColor="#fff"
            testID="admin-issuing-kyc-toggle"
          />
        </View>

        {/* Phase G4 — Push provisioning enrollment toggles */}
        <View style={styles.divider} />
        <View style={styles.toggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Apple Pay In-App Provisioning enrolled</Text>
            <Text style={styles.helper}>
              Enable only after Apple's PNO (Payment Network Operator) onboarding is approved.
              When ON — leads see the "Add to Apple Wallet" button on the card screen and the
              backend forwards SDK requests to Stripe. When OFF — the endpoint returns 409 with
              a clear "not enrolled" message.
            </Text>
          </View>
          <Switch
            value={issAppleEnrolled}
            onValueChange={setIssAppleEnrolled}
            trackColor={{ false: COLORS.disabledBg, true: '#000' }}
            thumbColor="#fff"
            testID="admin-issuing-apple-toggle"
          />
        </View>
        <View style={styles.toggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Google Pay PSP enrolled</Text>
            <Text style={styles.helper}>
              Enable only after Google Pay PSP (Payment Service Provider) onboarding is approved.
              When ON — leads see the "Add to Google Pay" button on Android and the backend
              forwards SDK requests to Stripe. When OFF — the endpoint returns 409 with a clear
              "not enrolled" message.
            </Text>
          </View>
          <Switch
            value={issGoogleEnrolled}
            onValueChange={setIssGoogleEnrolled}
            trackColor={{ false: COLORS.disabledBg, true: '#4285F4' }}
            thumbColor="#fff"
            testID="admin-issuing-google-toggle"
          />
        </View>

        <TouchableOpacity onPress={saveIssuing} disabled={saving === 'iss'} style={[styles.saveBtn, { backgroundColor: '#0EA5E9', opacity: saving === 'iss' ? 0.6 : 1 }]} activeOpacity={0.85} testID="admin-issuing-save">
          <Save size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'iss' ? 'Saving…' : 'Save Issuing settings'}</Text>
        </TouchableOpacity>
      </View>

      {/* App-wide Feature Toggles */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={styles.cardIcon}><MessageSquare size={18} color="#10B981" /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle}>App Features</Text>
            <Text style={styles.cardSub}>Enable / disable user-facing features. Disabled features are hidden in the user app.</Text>
          </View>
        </View>

        <View style={styles.toggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Credits / Wallet</Text>
            <Text style={styles.helper}>Show credits balance pill, /credits page, and auto-apply credits during contributions.</Text>
          </View>
          <Switch value={featCredits} onValueChange={setFeatCredits} trackColor={{ false: COLORS.disabledBg, true: '#10B981' }} thumbColor="#fff" testID="admin-feat-credits" />
        </View>

        <View style={styles.toggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Invite friends</Text>
            <Text style={styles.helper}>Show "Invite friends" entry on home + the /invite share page.</Text>
          </View>
          <Switch value={featInvite} onValueChange={setFeatInvite} trackColor={{ false: COLORS.disabledBg, true: '#10B981' }} thumbColor="#fff" testID="admin-feat-invite" />
        </View>

        <TouchableOpacity onPress={saveFeatures} disabled={saving === 'feat'} style={[styles.saveBtn, { backgroundColor: '#10B981', opacity: saving === 'feat' ? 0.6 : 1 }]} activeOpacity={0.85} testID="admin-feat-save">
          <Save size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'feat' ? 'Saving…' : 'Save feature toggles'}</Text>
        </TouchableOpacity>
      </View>

      {/* SMS Mode — Phase H6: global mock/live toggle */}
      <View style={[styles.card, { borderLeftWidth: 4, borderLeftColor: smsMode === 'live' ? '#10B981' : '#F59E0B' }]}>
        <View style={styles.cardHeader}>
          <View style={styles.cardIcon}><MessageSquare size={18} color={smsMode === 'live' ? '#10B981' : '#F59E0B'} /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle}>SMS Mode</Text>
            <Text style={styles.cardSub}>
              Master switch for ALL outgoing SMS (auth OTP, sensitive OTP, reminders).
              Switch to <Text style={{ fontWeight: '700' }}>Mock</Text> to skip real provider calls
              while testing — users still receive the OTP code in the app response.
            </Text>
          </View>
          <StatusPill ok={smsMode === 'live'} label={smsMode === 'live' ? 'LIVE' : 'MOCK'} />
        </View>

        <View style={{ flexDirection: 'row', gap: 8, marginTop: 8 }}>
          <TouchableOpacity
            onPress={() => saveSmsMode('mock')}
            disabled={saving === 'smsMode'}
            activeOpacity={0.85}
            testID="admin-sms-mode-mock"
            style={[
              styles.modeBtn,
              smsMode === 'mock' && { backgroundColor: '#F59E0B', borderColor: '#F59E0B' },
              saving === 'smsMode' && { opacity: 0.6 },
            ]}
          >
            <Text style={[styles.modeBtnText, smsMode === 'mock' && { color: '#fff' }]}>🧪 Mock SMS</Text>
            <Text style={[styles.modeBtnSub, smsMode === 'mock' && { color: 'rgba(255,255,255,0.85)' }]}>
              Use OTP 123456
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => saveSmsMode('live')}
            disabled={saving === 'smsMode'}
            activeOpacity={0.85}
            testID="admin-sms-mode-live"
            style={[
              styles.modeBtn,
              smsMode === 'live' && { backgroundColor: '#10B981', borderColor: '#10B981' },
              saving === 'smsMode' && { opacity: 0.6 },
            ]}
          >
            <Text style={[styles.modeBtnText, smsMode === 'live' && { color: '#fff' }]}>📡 Live SMS</Text>
            <Text style={[styles.modeBtnSub, smsMode === 'live' && { color: 'rgba(255,255,255,0.85)' }]}>
              Real provider
            </Text>
          </TouchableOpacity>
        </View>

        {smsMode === 'live' && (
          <Text style={[styles.helper, { marginTop: 8, color: '#10B981' }]}>
            ⚠ Real SMS will be sent and billed via your configured provider. Test on a single number first.
          </Text>
        )}
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

      {/* SignalWire — Phase F2.2 (Twilio alternative) */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={styles.cardIcon}><Radio size={18} color="#044CCC" /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle}>SignalWire (SMS / OTP)</Text>
            <Text style={styles.cardSub}>Twilio-compatible SMS provider. Use as a primary or as a fallback for high availability.</Text>
          </View>
          <View style={{ flexDirection: 'row', gap: 6 }}>
            <StatusPill ok={!!view.signalwire?.enabled} label={view.signalwire?.enabled ? 'Enabled' : 'Disabled'} />
            <StatusPill ok={!!view.signalwire?.project_id_set} label={view.signalwire?.project_id_set ? 'Configured' : 'Not configured'} />
          </View>
        </View>

        <View style={styles.toggleRow}>
          <Text style={styles.label}>Enable SignalWire</Text>
          <Switch value={swEnabled} onValueChange={setSwEnabled} trackColor={{ false: COLORS.disabledBg, true: '#044CCC' }} thumbColor="#fff" testID="admin-sw-enable" />
        </View>

        <Text style={styles.label}>Project ID {view.signalwire?.project_id_set ? <Text style={styles.maskedHint}>(saved: {view.signalwire?.project_id_masked} — leave blank to keep)</Text> : null}</Text>
        <TextInput style={styles.input} value={swProject} onChangeText={setSwProject} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" placeholderTextColor={COLORS.disabledText} autoCapitalize="none" testID="admin-sw-project" />

        <Text style={styles.label}>API Token {view.signalwire?.api_token_set ? <Text style={styles.maskedHint}>(saved: {view.signalwire?.api_token_masked} — leave blank to keep)</Text> : null}</Text>
        <TextInput style={styles.input} value={swToken} onChangeText={setSwToken} placeholder="PT…" placeholderTextColor={COLORS.disabledText} secureTextEntry autoCapitalize="none" testID="admin-sw-token" />

        <Text style={styles.label}>Space URL</Text>
        <TextInput style={styles.input} value={swSpace} onChangeText={setSwSpace} placeholder="your-space.signalwire.com" placeholderTextColor={COLORS.disabledText} autoCapitalize="none" testID="admin-sw-space" />
        <Text style={styles.helper}>Just the host (no protocol). Example: <Text style={{ fontWeight: '700' }}>example.signalwire.com</Text></Text>

        <Text style={styles.label}>From number (E.164)</Text>
        <TextInput style={styles.input} value={swFrom} onChangeText={setSwFrom} placeholder="+15555550000" placeholderTextColor={COLORS.disabledText} testID="admin-sw-from" />

        <View style={styles.btnRow}>
          <TouchableOpacity onPress={saveSignalWire} disabled={saving === 'sw'} style={[styles.saveBtn, { flex: 2, backgroundColor: '#044CCC', opacity: saving === 'sw' ? 0.6 : 1 }]} activeOpacity={0.85} testID="admin-sw-save">
            <Save size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'sw' ? 'Saving…' : 'Save SignalWire'}</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.divider} />
        <Text style={styles.label}>Send test SMS via SignalWire</Text>
        <View style={styles.formRow}>
          <TextInput style={[styles.input, { flex: 1, marginTop: 0 }]} value={swTestTo} onChangeText={setSwTestTo} placeholder="+15551234567" placeholderTextColor={COLORS.disabledText} testID="admin-sw-test-to" />
          <TouchableOpacity onPress={sendTestSw} disabled={saving === 'sw-test'} style={[styles.saveBtn, { backgroundColor: COLORS.primary, opacity: saving === 'sw-test' ? 0.6 : 1, paddingHorizontal: 18 }]} activeOpacity={0.85} testID="admin-sw-test-send">
            <Send size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'sw-test' ? '…' : 'Send'}</Text>
          </TouchableOpacity>
        </View>
        {swTestInfo ? (
          <View style={[styles.infoBox, swTestInfo.startsWith('✓') ? { backgroundColor: COLORS.successLight } : { backgroundColor: COLORS.warningLight }]}>
            <AlertCircle size={12} color={COLORS.text} />
            <Text style={styles.infoText}>{swTestInfo}</Text>
          </View>
        ) : null}
        {view.signalwire?.updated_at ? <Text style={styles.metaSmall}>Last updated {new Date(view.signalwire.updated_at).toLocaleString()} by {view.signalwire.updated_by}</Text> : null}
      </View>

      {/* SMS Routing — Phase F2.2 */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={styles.cardIcon}><Radio size={18} color={COLORS.primary} /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle}>SMS Routing</Text>
            <Text style={styles.cardSub}>Choose the primary SMS provider and an optional fallback. If the primary fails, the fallback is auto-tried.</Text>
          </View>
          <StatusPill ok={true} label={`${(view.sms_routing?.primary || 'twilio').toUpperCase()}${view.sms_routing?.fallback ? ` → ${view.sms_routing.fallback.toUpperCase()}` : ''}`} />
        </View>

        <Text style={styles.label}>Primary provider</Text>
        <View style={styles.formRow}>
          <TouchableOpacity onPress={() => setSmsPrimary('twilio')} style={[styles.toggle, smsPrimary === 'twilio' && styles.toggleActive]} activeOpacity={0.85} testID="admin-routing-primary-twilio">
            <Text style={[styles.toggleText, smsPrimary === 'twilio' && { color: '#fff' }]}>Twilio</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setSmsPrimary('signalwire')} style={[styles.toggle, smsPrimary === 'signalwire' && styles.toggleActive]} activeOpacity={0.85} testID="admin-routing-primary-sw">
            <Text style={[styles.toggleText, smsPrimary === 'signalwire' && { color: '#fff' }]}>SignalWire</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.label}>Fallback provider (optional)</Text>
        <View style={styles.formRow}>
          <TouchableOpacity onPress={() => setSmsFallback('none')} style={[styles.toggle, smsFallback === 'none' && styles.toggleActive]} activeOpacity={0.85} testID="admin-routing-fallback-none">
            <Text style={[styles.toggleText, smsFallback === 'none' && { color: '#fff' }]}>None</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setSmsFallback('twilio')} disabled={smsPrimary === 'twilio'} style={[styles.toggle, smsFallback === 'twilio' && styles.toggleActive, smsPrimary === 'twilio' && { opacity: 0.4 }]} activeOpacity={0.85} testID="admin-routing-fallback-twilio">
            <Text style={[styles.toggleText, smsFallback === 'twilio' && { color: '#fff' }]}>Twilio</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setSmsFallback('signalwire')} disabled={smsPrimary === 'signalwire'} style={[styles.toggle, smsFallback === 'signalwire' && styles.toggleActive, smsPrimary === 'signalwire' && { opacity: 0.4 }]} activeOpacity={0.85} testID="admin-routing-fallback-sw">
            <Text style={[styles.toggleText, smsFallback === 'signalwire' && { color: '#fff' }]}>SignalWire</Text>
          </TouchableOpacity>
        </View>
        <Text style={styles.helper}>Fallback must differ from primary. If a primary attempt fails (timeout / 4xx / 5xx), the fallback provider is automatically retried for the same message.</Text>

        <TouchableOpacity onPress={saveSmsRouting} disabled={saving === 'routing'} style={[styles.saveBtn, { backgroundColor: COLORS.primary, opacity: saving === 'routing' ? 0.6 : 1 }]} activeOpacity={0.85} testID="admin-routing-save">
          <Save size={14} color="#fff" /><Text style={styles.saveBtnText}>{saving === 'routing' ? 'Saving…' : 'Save SMS routing'}</Text>
        </TouchableOpacity>
        {view.sms_routing?.updated_at ? <Text style={styles.metaSmall}>Last updated {new Date(view.sms_routing.updated_at).toLocaleString()} by {view.sms_routing.updated_by}</Text> : null}
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
  // Phase H6 — SMS mode picker buttons
  modeBtn: {
    flex: 1,
    paddingVertical: 14,
    paddingHorizontal: 12,
    borderRadius: RADIUS.md,
    borderWidth: 1.5,
    borderColor: COLORS.border,
    backgroundColor: COLORS.bg,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
  },
  modeBtnText: { fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md, color: COLORS.text },
  modeBtnSub: { fontSize: 11, color: COLORS.subtext, fontWeight: FONT.weights.medium },
  btnRow: { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.sm },
  metaSmall: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: SPACING.sm, fontStyle: 'italic' },
  infoBox: { flexDirection: 'row', alignItems: 'center', gap: 6, padding: SPACING.sm, marginTop: SPACING.sm, borderRadius: RADIUS.sm },
  infoText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.semibold, flex: 1 },
});
