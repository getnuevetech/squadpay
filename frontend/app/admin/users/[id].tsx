import { useEffect, useState, useCallback } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, Platform, TextInput } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { ArrowLeft, Ban, ShieldCheck, Crown, Users as UsersIcon, Wallet, Plus, X as XIcon, Percent, DollarSign, Trash2, KeyRound, FileCheck2, FileWarning, Inbox, Mail } from 'lucide-react-native';
import { adminApi, AdminUserDetail, AdminGroupRow, UserCreditWallet, LeadAutoDiscount, ticketsApi } from '../../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { formatUid } from '../../../src/ids';

function confirm(title: string, message: string, onYes: () => void) {
  if (Platform.OS === 'web') {
    if (typeof window !== 'undefined' && window.confirm(`${title}\n\n${message}`)) onYes();
  } else {
    Alert.alert(title, message, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Yes', style: 'destructive', onPress: onYes },
    ]);
  }
}

export default function AdminUserDetailPage() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [user, setUser] = useState<AdminUserDetail | null>(null);
  const [tickets, setTickets] = useState<any[]>([]);
  const [busy, setBusy] = useState(true);
  const [reason, setReason] = useState('');
  // C2 — credits + lead discount
  const [wallet, setWallet] = useState<UserCreditWallet | null>(null);
  const [grantAmt, setGrantAmt] = useState('');
  const [grantNote, setGrantNote] = useState('');
  const [granting, setGranting] = useState(false);
  const [ldType, setLdType] = useState<'flat' | 'percent'>('flat');
  const [ldValue, setLdValue] = useState('');
  const [ldNote, setLdNote] = useState('');

  const load = useCallback(async () => {
    if (!id) return;
    setBusy(true);
    try {
      const [u, w, t] = await Promise.all([
        adminApi.getUser(id),
        adminApi.getUserCredits(id).catch(() => null),
        ticketsApi.forUser(id).catch(() => ({ items: [], total: 0 })),
      ]);
      setUser(u);
      setWallet(w);
      setTickets(t.items || []);
      const ld = w?.lead_auto_discount;
      if (ld) {
        setLdType(ld.type);
        setLdValue(String(ld.value));
        setLdNote(ld.note || '');
      } else {
        setLdValue('');
        setLdNote('');
      }
    }
    catch (e: any) { Alert.alert('Error', e?.message || 'Failed to load user'); }
    finally { setBusy(false); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const onGrantCredit = async () => {
    const amt = parseFloat(grantAmt);
    if (!amt || amt <= 0) { Alert.alert('Invalid', 'Amount must be > 0'); return; }
    setGranting(true);
    try {
      await adminApi.grantUserCredit(id!, amt, grantNote || undefined);
      setGrantAmt('');
      setGrantNote('');
      await load();
    } catch (e: any) { Alert.alert('Error', e?.message || 'Grant failed'); }
    finally { setGranting(false); }
  };

  const onRevokeCredit = async (creditId: string) => {
    confirm('Revoke credit?', 'This credit will no longer be spendable. Already-consumed amount stays consumed.', async () => {
      try { await adminApi.revokeUserCredit(id!, creditId); await load(); }
      catch (e: any) { Alert.alert('Error', e?.message || 'Revoke failed'); }
    });
  };

  const onSaveLeadDiscount = async () => {
    const v = parseFloat(ldValue);
    if (!v || v <= 0) { Alert.alert('Invalid', 'Discount value must be > 0'); return; }
    if (ldType === 'percent' && v > 100) { Alert.alert('Invalid', 'Percent must be ≤ 100'); return; }
    try {
      await adminApi.setLeadDiscount(id!, { type: ldType, value: v, note: ldNote || undefined, enabled: true });
      await load();
    } catch (e: any) { Alert.alert('Error', e?.message || 'Save failed'); }
  };

  const onClearLeadDiscount = async () => {
    confirm('Clear lead auto-discount?', 'New squads by this lead will not get an automatic discount.', async () => {
      try {
        await adminApi.setLeadDiscount(id!, { enabled: false });
        await load();
      } catch (e: any) { Alert.alert('Error', e?.message || 'Clear failed'); }
    });
  };

  const onBlock = () => {
    if (!user) return;
    confirm(
      'Block user?',
      `This will prevent ${user.name} from logging in or contributing to bills. They can be unblocked later.`,
      async () => {
        try { await adminApi.blockUser(user.id, true, reason || undefined); setReason(''); await load(); }
        catch (e: any) { Alert.alert('Error', e?.message || 'Failed to block'); }
      }
    );
  };

  const onUnblock = () => {
    if (!user) return;
    confirm(
      'Unblock user?',
      `${user.name} will be able to log in and contribute again.`,
      async () => {
        try { await adminApi.blockUser(user.id, false); await load(); }
        catch (e: any) { Alert.alert('Error', e?.message || 'Failed to unblock'); }
      }
    );
  };

  const onPushOtp = async () => {
    if (!user) return;
    if (!user.phone) {
      Alert.alert('No phone on file', 'This user has no phone number registered, so we can\'t send a verification code.');
      return;
    }
    confirm(
      'Send verification code?',
      `A 6-digit OTP will be sent via SMS to ${user.phone}. ${user.name} can use it to verify on their next sign-in.`,
      async () => {
        try {
          const r = await adminApi.pushUserOtp(user.id);
          Alert.alert('OTP sent', r.message || 'Code sent via SMS.');
        } catch (e: any) {
          Alert.alert('Could not send OTP', e?.message || '');
        }
      }
    );
  };

  if (busy || !user) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  const renderGroup = (g: AdminGroupRow, i: number) => (
    <TouchableOpacity
      key={g.id || i}
      style={styles.groupRow}
      onPress={() => router.push(`/admin/groups/${g.id}` as any)}
      activeOpacity={0.85}
      testID={`admin-user-group-${g.id}`}
    >
      <View style={{ flex: 1 }}>
        <Text style={styles.groupTitle} numberOfLines={1}>{g.title || 'Untitled bill'}</Text>
        <Text style={styles.groupMeta}>{g.code} • {g.status} • {g.members_count} members</Text>
      </View>
      <Text style={styles.groupAmount}>${(g.total_amount || 0).toFixed(2)}</Text>
    </TouchableOpacity>
  );

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} activeOpacity={0.7} testID="admin-user-back">
        <ArrowLeft size={16} color={COLORS.subtext} />
        <Text style={styles.backText}>All users</Text>
      </TouchableOpacity>

      <View style={styles.headerCard}>
        <View style={[styles.avatar, user.is_blocked && { backgroundColor: COLORS.dangerLight }]}>
          <Text style={[styles.avatarText, user.is_blocked && { color: COLORS.danger }]}>{(user.name || '?').slice(0, 1).toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Text style={styles.name}>{user.name}</Text>
            {user.verified ? <ShieldCheck size={14} color={COLORS.success} /> : null}
            {user.is_blocked ? (
              <View style={styles.blockedPill}><Ban size={11} color={COLORS.danger} /><Text style={styles.blockedPillText}>Blocked</Text></View>
            ) : null}
          </View>

          {/* Labeled info table — each field gets its own line + label so the
              admin can scan quickly. Replaces the previous clogged single-line
              meta block. */}
          <View style={styles.infoTable} testID="admin-user-info-table">
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Phone</Text>
              <Text style={styles.infoValue} selectable>{user.phone || '—'}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>User ID</Text>
              <Text style={[styles.infoValue, styles.mono]} selectable testID="admin-user-uid">{formatUid(user.id)}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Raw ID</Text>
              <Text style={[styles.infoValueSm, styles.mono]} selectable>{user.id}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Joined</Text>
              <Text style={styles.infoValue}>{new Date(user.created_at).toLocaleString()}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Verified</Text>
              <Text style={[styles.infoValue, { color: user.verified ? COLORS.success : COLORS.warning }]}>
                {user.verified ? 'Yes' : 'No'}
              </Text>
            </View>
            {user.is_blocked && user.blocked_reason ? (
              <View style={styles.infoRow}>
                <Text style={styles.infoLabel}>Block reason</Text>
                <Text style={[styles.infoValue, { color: COLORS.danger, fontStyle: 'italic' }]}>{user.blocked_reason}</Text>
              </View>
            ) : null}
          </View>

          {/* T&C agreement status — surfaces user agreement check stored on the
              user account so support staff can confirm acceptance. */}
          <View
            testID="admin-user-terms-row"
            style={[
              styles.termsRow,
              user.terms_accepted_at ? styles.termsRowOk : styles.termsRowMissing,
            ]}
          >
            {user.terms_accepted_at ? (
              <>
                <FileCheck2 size={12} color={COLORS.success} />
                <Text style={styles.termsTextOk} testID="admin-user-terms-accepted">
                  Terms agreed · {new Date(user.terms_accepted_at).toLocaleDateString()}
                </Text>
              </>
            ) : (
              <>
                <FileWarning size={12} color={COLORS.warning} />
                <Text style={styles.termsTextMissing} testID="admin-user-terms-missing">
                  Terms not yet agreed
                </Text>
              </>
            )}
          </View>
        </View>
      </View>

      <View style={styles.statsRow}>
        <View style={styles.statCard}><Text style={styles.statLabel}>As lead</Text><Text style={styles.statValue}>{(user.led_groups || []).length}</Text></View>
        <View style={styles.statCard}><Text style={styles.statLabel}>As member</Text><Text style={styles.statValue}>{(user.joined_groups || []).length}</Text></View>
        <View style={styles.statCard}><Text style={styles.statLabel}>Lead billed</Text><Text style={styles.statValue}>${Number(user.total_billed_as_lead || (user.led_groups || []).reduce((s, g) => s + Number(g?.total_amount || 0), 0) || 0).toFixed(2)}</Text></View>
        <View style={styles.statCard} testID="admin-user-total-contributed">
          <Text style={styles.statLabel}>Total contributed</Text>
          <Text style={[styles.statValue, { color: COLORS.success }]}>
            ${Number(user.total_contributed || 0).toFixed(2)}
          </Text>
        </View>
      </View>

      <View style={styles.actionsCard}>
        {user.is_blocked ? (
          <TouchableOpacity onPress={onUnblock} style={[styles.actionBtn, { backgroundColor: COLORS.success }]} activeOpacity={0.85} testID="admin-user-unblock">
            <ShieldCheck size={16} color="#fff" /><Text style={styles.actionBtnText}>Unblock user</Text>
          </TouchableOpacity>
        ) : (
          <View style={{ gap: 8 }}>
            <Text style={styles.label}>Reason (optional)</Text>
            <TextInput
              style={styles.input}
              placeholder="e.g. fraud, abuse, requested by user…"
              placeholderTextColor={COLORS.disabledText}
              value={reason}
              onChangeText={setReason}
              testID="admin-user-block-reason"
            />
            <TouchableOpacity onPress={onBlock} style={[styles.actionBtn, { backgroundColor: COLORS.danger }]} activeOpacity={0.85} testID="admin-user-block">
              <Ban size={16} color="#fff" /><Text style={styles.actionBtnText}>Block user</Text>
            </TouchableOpacity>
          </View>
        )}
        {!user.is_blocked && user.phone ? (
          <TouchableOpacity
            onPress={onPushOtp}
            style={[styles.actionBtn, { backgroundColor: COLORS.primary, marginTop: 8 }]}
            activeOpacity={0.85}
            testID="admin-user-push-otp"
          >
            <KeyRound size={16} color="#fff" />
            <Text style={styles.actionBtnText}>Send verification code</Text>
          </TouchableOpacity>
        ) : null}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}><Wallet size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Credits — balance ${(wallet?.balance ?? 0).toFixed(2)}</Text></View>
        <View style={styles.formRow}>
          <TextInput
            style={[styles.input, { flex: 1 }]}
            placeholder="Amount"
            placeholderTextColor={COLORS.disabledText}
            keyboardType="decimal-pad"
            value={grantAmt}
            onChangeText={setGrantAmt}
            testID="admin-credit-amount"
          />
          <TextInput
            style={[styles.input, { flex: 2 }]}
            placeholder="Note (optional)"
            placeholderTextColor={COLORS.disabledText}
            value={grantNote}
            onChangeText={setGrantNote}
            testID="admin-credit-note"
          />
          <TouchableOpacity
            onPress={onGrantCredit}
            disabled={granting}
            style={[styles.smallBtn, { backgroundColor: COLORS.success, opacity: granting ? 0.6 : 1 }]}
            activeOpacity={0.85}
            testID="admin-credit-grant"
          >
            <Plus size={14} color="#fff" /><Text style={styles.smallBtnText}>Grant</Text>
          </TouchableOpacity>
        </View>
        {(wallet?.items || []).length === 0 ? (
          <Text style={styles.empty}>No credits yet.</Text>
        ) : (
          (wallet!.items).slice(0, 12).map((c) => (
            <View key={c.id} style={styles.creditRow} testID={`admin-credit-row-${c.id}`}>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <Text style={styles.creditAmt}>${Number(c.amount || 0).toFixed(2)}</Text>
                  <View style={[styles.kindPill,
                    c.status === 'active' && { backgroundColor: COLORS.successLight },
                    c.status === 'consumed' && { backgroundColor: COLORS.disabledBg },
                    c.status === 'revoked' && { backgroundColor: COLORS.dangerLight },
                  ]}>
                    <Text style={[styles.kindPillText,
                      c.status === 'active' && { color: COLORS.success },
                      c.status === 'consumed' && { color: COLORS.subtext },
                      c.status === 'revoked' && { color: COLORS.danger },
                    ]}>{c.status?.toUpperCase()}</Text>
                  </View>
                  <Text style={styles.creditKind}>{c.kind?.replace('_', ' ')}</Text>
                </View>
                {Number(c.consumed_amount || 0) > 0 ? (
                  <Text style={styles.metaSmall}>Used ${Number(c.consumed_amount || 0).toFixed(2)} • Remaining ${Math.max(0, Number(c.amount || 0) - Number(c.consumed_amount || 0)).toFixed(2)}</Text>
                ) : null}
                {c.note ? <Text style={styles.metaSmall}>{c.note}</Text> : null}
              </View>
              {c.status === 'active' ? (
                <TouchableOpacity onPress={() => onRevokeCredit(c.id)} style={styles.iconBtn} activeOpacity={0.7} testID={`admin-credit-revoke-${c.id}`}>
                  <Trash2 size={14} color={COLORS.danger} />
                </TouchableOpacity>
              ) : null}
            </View>
          ))
        )}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}><Crown size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Lead auto-discount</Text></View>
        <Text style={styles.metaSmall}>Auto-applied to every NEW squad this user creates as lead. Leave empty to disable.</Text>
        <View style={[styles.formRow, { marginTop: SPACING.sm }]}>
          <TouchableOpacity
            onPress={() => setLdType('flat')}
            style={[styles.toggle, ldType === 'flat' && styles.toggleActive]}
            activeOpacity={0.85}
          >
            <DollarSign size={12} color={ldType === 'flat' ? '#fff' : COLORS.text} />
            <Text style={[styles.toggleText, ldType === 'flat' && { color: '#fff' }]}>Flat</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => setLdType('percent')}
            style={[styles.toggle, ldType === 'percent' && styles.toggleActive]}
            activeOpacity={0.85}
          >
            <Percent size={12} color={ldType === 'percent' ? '#fff' : COLORS.text} />
            <Text style={[styles.toggleText, ldType === 'percent' && { color: '#fff' }]}>Percent</Text>
          </TouchableOpacity>
          <TextInput
            style={[styles.input, { flex: 1 }]}
            placeholder={ldType === 'percent' ? '10' : '5'}
            placeholderTextColor={COLORS.disabledText}
            keyboardType="decimal-pad"
            value={ldValue}
            onChangeText={setLdValue}
            testID="admin-lead-discount-value"
          />
          <TextInput
            style={[styles.input, { flex: 2 }]}
            placeholder="Note (e.g. VIP)"
            placeholderTextColor={COLORS.disabledText}
            value={ldNote}
            onChangeText={setLdNote}
            testID="admin-lead-discount-note"
          />
          <TouchableOpacity onPress={onSaveLeadDiscount} style={[styles.smallBtn, { backgroundColor: COLORS.primary }]} activeOpacity={0.85} testID="admin-lead-discount-save">
            <Text style={styles.smallBtnText}>Save</Text>
          </TouchableOpacity>
          {wallet?.lead_auto_discount ? (
            <TouchableOpacity onPress={onClearLeadDiscount} style={[styles.smallBtn, { backgroundColor: COLORS.danger }]} activeOpacity={0.85} testID="admin-lead-discount-clear">
              <XIcon size={14} color="#fff" />
            </TouchableOpacity>
          ) : null}
        </View>
        {wallet?.lead_auto_discount ? (
          <Text style={styles.activeNote}>
            Active: {wallet.lead_auto_discount.type === 'percent' ? `${wallet.lead_auto_discount.value}%` : `$${Number(wallet.lead_auto_discount.value || 0).toFixed(2)}`} off — {wallet.lead_auto_discount.note || 'no note'} (set by {wallet.lead_auto_discount.set_by})
          </Text>
        ) : null}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}><Crown size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Squads led ({user.led_groups.length})</Text></View>
        {user.led_groups.length === 0 ? <Text style={styles.empty}>None.</Text> : user.led_groups.map(renderGroup)}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}><UsersIcon size={14} color={COLORS.text} /><Text style={styles.sectionTitle}>Squads joined ({user.joined_groups.length})</Text></View>
        {user.joined_groups.length === 0 ? <Text style={styles.empty}>None.</Text> : user.joined_groups.map(renderGroup)}
      </View>

      {/* Customer Service tickets — auto-linked to user via UID.
          Surfaces all contact-us messages the user has sent. Tap to jump to
          the Customer Service screen with the ticket pre-opened. */}
      <View style={styles.section} testID="admin-user-tickets-section">
        <View style={styles.sectionHeader}>
          <Inbox size={14} color={COLORS.text} />
          <Text style={styles.sectionTitle}>Support tickets ({tickets.length})</Text>
        </View>
        {tickets.length === 0 ? (
          <Text style={styles.empty}>No tickets from this user.</Text>
        ) : tickets.map((t: any) => (
          <TouchableOpacity
            key={t.id}
            style={styles.ticketRow}
            activeOpacity={0.7}
            onPress={() => router.push(`/admin/customer-service?ticket=${t.id}` as any)}
            testID={`admin-user-ticket-${t.id}`}
          >
            <Mail size={14} color={t.status === 'new' ? COLORS.danger : t.status === 'resolved' || t.status === 'closed' ? COLORS.success : COLORS.warning} />
            <View style={{ flex: 1 }}>
              <Text style={styles.ticketTitle}>{t.subject_label || t.subject || 'Message'}</Text>
              <Text style={styles.ticketBody} numberOfLines={2}>{t.message}</Text>
              <Text style={styles.ticketMeta}>
                {new Date(t.created_at).toLocaleString()} · status {t.status}
                {t.replies?.length ? ` · ${t.replies.length} repl${t.replies.length === 1 ? 'y' : 'ies'}` : ''}
              </Text>
            </View>
          </TouchableOpacity>
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  backBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: SPACING.md },
  backText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.medium },
  headerCard: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACING.md, padding: SPACING.lg, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginBottom: SPACING.md },
  avatar: { width: 56, height: 56, borderRadius: 28, backgroundColor: COLORS.primaryLight, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: COLORS.primary, fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold },
  name: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  meta: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 2 },
  metaSmall: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  // Labeled info table — left-aligned narrow label column, value column flexes.
  infoTable: { marginTop: SPACING.md, gap: 10 },
  infoRow: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACING.sm },
  infoLabel: { width: 100, fontSize: 11, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.bold, letterSpacing: 0.4, paddingTop: 1 },
  infoValue: { flex: 1, fontSize: FONT.sizes.sm, color: COLORS.text, lineHeight: 18 },
  infoValueSm: { flex: 1, fontSize: 11, color: COLORS.subtext, lineHeight: 16 },
  mono: { fontFamily: 'monospace', letterSpacing: 0.4 },
  uidLine: {
    fontSize: 12,
    color: COLORS.subtext,
    marginTop: 4,
    fontFamily: 'monospace',
    letterSpacing: 0.6,
    fontWeight: FONT.weights.semibold,
  },
  blockedPill: { flexDirection: 'row', alignItems: 'center', gap: 3, backgroundColor: COLORS.dangerLight, paddingHorizontal: 6, paddingVertical: 2, borderRadius: RADIUS.pill },
  blockedPillText: { fontSize: 10, color: COLORS.danger, fontWeight: FONT.weights.bold },
  blockedReason: { fontSize: FONT.sizes.xs, color: COLORS.danger, marginTop: 6, fontStyle: 'italic' },
  // T&C agreement pill — green when signed, amber if pre-T&C / not yet agreed.
  termsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    alignSelf: 'flex-start',
    marginTop: 8,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: RADIUS.pill,
    borderWidth: 1,
  },
  termsRowOk: { backgroundColor: COLORS.successLight, borderColor: COLORS.success },
  termsRowMissing: { backgroundColor: COLORS.warningLight, borderColor: COLORS.warning },
  termsTextOk: { fontSize: 11, color: COLORS.success, fontWeight: FONT.weights.semibold },
  termsTextMissing: { fontSize: 11, color: COLORS.warning, fontWeight: FONT.weights.semibold },
  statsRow: { flexDirection: 'row', gap: SPACING.sm, marginBottom: SPACING.md, flexWrap: 'wrap' },
  statCard: { flex: 1, minWidth: 120, padding: SPACING.md, backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md },
  statLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.medium },
  statValue: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text, marginTop: 4 },
  actionsCard: { padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, marginBottom: SPACING.md },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.medium },
  input: { height: 40, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, color: COLORS.text, backgroundColor: COLORS.bg },
  actionBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, height: 42, borderRadius: RADIUS.md },
  actionBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  section: { marginBottom: SPACING.md, padding: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: SPACING.sm },
  sectionTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  empty: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic' },
  ticketRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, padding: SPACING.sm, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  ticketTitle: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  ticketBody: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  ticketMeta: { fontSize: 10, color: COLORS.subtext, marginTop: 4, fontStyle: 'italic' },
  groupRow: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  groupTitle: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.semibold, color: COLORS.text },
  groupMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  groupAmount: { fontSize: FONT.sizes.sm, fontWeight: FONT.weights.bold, color: COLORS.text },
  // C2 styles
  formRow: { flexDirection: 'row', gap: 8, alignItems: 'center', flexWrap: 'wrap' },
  smallBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 12, height: 38, borderRadius: RADIUS.md, justifyContent: 'center' },
  smallBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  creditRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COLORS.border, gap: 8 },
  creditAmt: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.bold, color: COLORS.text },
  kindPill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  kindPillText: { fontSize: 10, fontWeight: FONT.weights.bold },
  creditKind: { fontSize: FONT.sizes.xs, color: COLORS.subtext, textTransform: 'capitalize' },
  iconBtn: { padding: 8 },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, height: 38, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface },
  toggleActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  toggleText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.semibold, color: COLORS.text },
  activeNote: { fontSize: FONT.sizes.xs, color: COLORS.success, fontWeight: FONT.weights.semibold, marginTop: SPACING.sm },
});
