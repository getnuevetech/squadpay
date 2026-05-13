import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator, Alert } from 'react-native';
import { Lock, ShieldAlert, ShieldCheck, RefreshCw, RotateCcw, AlertCircle, KeyRound } from 'lucide-react-native';
import { adminApi, KmsStatus, KmsRotateResult } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';

export default function AdminSecurity() {
  const [status, setStatus] = useState<KmsStatus | null>(null);
  const [busy, setBusy] = useState(true);
  const [acting, setActing] = useState<'reload' | 'rotate' | null>(null);
  const [lastRotate, setLastRotate] = useState<KmsRotateResult | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const s = await adminApi.getKmsStatus();
      setStatus(s);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed to load'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const reload = async () => {
    setActing('reload');
    try {
      const s = await adminApi.reloadKms();
      setStatus(s);
      Alert.alert('Reloaded', `Now using key source: ${s.key_source}`);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setActing(null); }
  };

  const rotate = async () => {
    if (!confirm('Re-encrypt all stored secrets with the current primary key?\n\nThis is safe to run — old ciphertexts remain decryptable through legacy fallback.')) return;
    setActing('rotate');
    try {
      const r = await adminApi.rotateKms();
      setLastRotate(r);
      await load();
      // June 2025 — extended walker reports per-collection counts. Surface
      // them so the admin can see exactly where secrets moved (gateway_config,
      // app_settings, users, etc.) — useful for compliance / SOC-2 audit.
      const lines: string[] = [
        `Re-encrypted ${r.rotated} field${r.rotated === 1 ? '' : 's'} in ${r.elapsed_ms}ms.`,
        `Skipped: ${r.skipped}   Failed: ${r.failed}`,
        `New primary key fingerprint: ${r.primary_fingerprint}`,
      ];
      if (r.per_collection) {
        const detail = Object.entries(r.per_collection)
          .filter(([, v]) => v.rotated || v.skipped || v.failed)
          .map(([k, v]) => `  • ${k}: ${v.rotated} rotated${v.failed ? `, ${v.failed} failed` : ''}`)
          .join('\n');
        if (detail) {
          lines.push('', 'Per collection:', detail);
        }
      }
      if (r.failed > 0) {
        lines.push('', `Note: "failed" usually means plaintext values stored inside an *_enc parent (e.g. publishable Stripe key, environment flag). These are not actually encrypted and remain as-is.`);
      }
      Alert.alert('Rotation complete', lines.join('\n'));
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed'); }
    finally { setActing(null); }
  };

  if (busy && !status) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  const secure = !!status?.secure;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <Text style={styles.heading} testID="admin-security-heading">Security & Encryption</Text>
      <Text style={styles.subheading}>
        At-rest encryption keys (KMS) used to protect Stripe, Twilio, SignalWire and other
        integration secrets stored in the database.
      </Text>

      {/* Status banner */}
      <View style={[styles.banner, secure ? styles.bannerOk : styles.bannerWarn]}>
        {secure ? <ShieldCheck size={22} color="#fff" /> : <ShieldAlert size={22} color="#fff" />}
        <View style={{ flex: 1 }}>
          <Text style={styles.bannerTitle}>{secure ? 'Secure' : 'Insecure (development only)'}</Text>
          <Text style={styles.bannerText}>
            {secure
              ? `Running with a dedicated KMS key (source: ${status?.key_source}).`
              : status?.warning || 'Running with JWT-derived key — set KMS_MASTER_KEY in /app/backend/.env for production.'}
          </Text>
        </View>
      </View>

      {/* Key info */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={styles.cardIcon}><KeyRound size={18} color={COLORS.primary} /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle}>Current key</Text>
            <Text style={styles.cardSub}>The fingerprint is a non-reversible 8-char hash of the key bytes (safe to display).</Text>
          </View>
        </View>
        <View style={styles.kvRow}><Text style={styles.k}>Source:</Text><Text style={styles.v}>{status?.key_source || '—'}</Text></View>
        <View style={styles.kvRow}><Text style={styles.k}>Primary fingerprint:</Text><Text style={[styles.v, styles.mono]}>{status?.primary_fingerprint || '—'}</Text></View>
        <View style={styles.kvRow}>
          <Text style={styles.k}>Legacy keys (decrypt fallback):</Text>
          <Text style={[styles.v, styles.mono]}>
            {status?.legacy_fingerprints && status.legacy_fingerprints.length > 0
              ? status.legacy_fingerprints.join(', ')
              : '— none —'}
          </Text>
        </View>
        <View style={styles.kvRow}><Text style={styles.k}>Encrypted fields stored:</Text><Text style={styles.v}>{status?.encrypted_field_count ?? '—'}</Text></View>
      </View>

      {/* Setup instructions for production */}
      {!secure ? (
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardIcon}><Lock size={18} color={COLORS.warning} /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardTitle}>Switch to a production KMS key</Text>
              <Text style={styles.cardSub}>One-time setup. Existing data stays readable through automatic legacy fallback.</Text>
            </View>
          </View>
          <Text style={styles.step}>1. Generate a new Fernet key:</Text>
          <View style={styles.codeBlock}>
            <Text style={styles.code} selectable>
              python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
            </Text>
          </View>
          <Text style={styles.step}>2. Add it to /app/backend/.env:</Text>
          <View style={styles.codeBlock}>
            <Text style={styles.code} selectable>KMS_MASTER_KEY=&lt;paste-key-here&gt;</Text>
          </View>
          <Text style={styles.step}>3. Restart the backend (sudo supervisorctl restart backend) — or click Reload below if you've already updated .env.</Text>
          <Text style={styles.step}>4. Click "Rotate now" to re-encrypt all stored secrets with the new key.</Text>
        </View>
      ) : null}

      {/* Actions */}
      <View style={styles.actions}>
        <TouchableOpacity onPress={reload} disabled={!!acting} style={[styles.btn, styles.btnSecondary, acting === 'reload' && styles.btnDisabled]} activeOpacity={0.85} testID="security-reload">
          <RefreshCw size={14} color={COLORS.text} />
          <Text style={styles.btnTextSecondary}>{acting === 'reload' ? 'Reloading…' : 'Reload from .env'}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={rotate} disabled={!!acting} style={[styles.btn, styles.btnPrimary, acting === 'rotate' && styles.btnDisabled]} activeOpacity={0.85} testID="security-rotate">
          <RotateCcw size={14} color="#fff" />
          <Text style={styles.btnText}>{acting === 'rotate' ? 'Rotating…' : 'Rotate now (re-encrypt)'}</Text>
        </TouchableOpacity>
      </View>

      {lastRotate ? (
        <View style={[styles.card, { backgroundColor: COLORS.successLight, borderColor: COLORS.success }]}>
          <View style={styles.cardHeader}>
            <View style={styles.cardIcon}><AlertCircle size={18} color={COLORS.success} /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardTitle}>Last rotation result</Text>
            </View>
          </View>
          <View style={styles.kvRow}><Text style={styles.k}>Re-encrypted:</Text><Text style={styles.v}>{lastRotate.rotated} fields</Text></View>
          <View style={styles.kvRow}><Text style={styles.k}>Skipped:</Text><Text style={styles.v}>{lastRotate.skipped}</Text></View>
          <View style={styles.kvRow}><Text style={styles.k}>Failed:</Text><Text style={[styles.v, lastRotate.failed > 0 && { color: COLORS.danger }]}>{lastRotate.failed}</Text></View>
          <View style={styles.kvRow}><Text style={styles.k}>Elapsed:</Text><Text style={styles.v}>{lastRotate.elapsed_ms}ms</Text></View>
          <View style={styles.kvRow}><Text style={styles.k}>Active key:</Text><Text style={[styles.v, styles.mono]}>{lastRotate.primary_fingerprint}</Text></View>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginBottom: SPACING.lg },
  banner: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md, padding: SPACING.md, marginBottom: SPACING.md, borderRadius: RADIUS.md },
  bannerOk: { backgroundColor: '#10B981' },
  bannerWarn: { backgroundColor: '#D97706' },
  bannerTitle: { color: '#fff', fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold },
  bannerText: { color: 'rgba(255,255,255,0.95)', fontSize: FONT.sizes.sm, marginTop: 2 },
  card: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md, padding: SPACING.md, marginBottom: SPACING.md },
  cardHeader: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACING.sm, marginBottom: SPACING.sm },
  cardIcon: { width: 32, height: 32, borderRadius: RADIUS.md, backgroundColor: COLORS.primaryLight, alignItems: 'center', justifyContent: 'center' },
  cardTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  cardSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  kvRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', paddingVertical: 6, gap: SPACING.md, flexWrap: 'wrap' },
  k: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, flex: 1 },
  v: { color: COLORS.text, fontSize: FONT.sizes.sm, textAlign: 'right' },
  mono: { fontFamily: 'Menlo, Consolas, monospace', fontSize: FONT.sizes.xs },
  step: { fontSize: FONT.sizes.sm, color: COLORS.text, marginTop: SPACING.sm, fontWeight: FONT.weights.semibold },
  codeBlock: { backgroundColor: '#0F172A', borderRadius: RADIUS.md, padding: SPACING.md, marginTop: 6 },
  code: { fontFamily: 'Menlo, Consolas, monospace', color: '#A5B4FC', fontSize: FONT.sizes.xs },
  actions: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.md, flexWrap: 'wrap' },
  btn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: SPACING.md, paddingVertical: 12, borderRadius: RADIUS.md },
  btnPrimary: { backgroundColor: COLORS.primary },
  btnSecondary: { backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: '#fff', fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold },
  btnTextSecondary: { color: COLORS.text, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold },
});
