/**
 * Settings stub screen — hub for profile, credits, legal, sign out, and (when
 * applicable) admin entry. Designed for the bottom tab bar destination.
 */
import { useEffect, useState } from 'react';
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
  Alert,
  Platform,
  Modal,
  TextInput,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import {
  ArrowLeft,
  Wallet,
  Gift,
  ShieldCheck,
  FileText,
  HelpCircle,
  Mail,
  LogOut,
  ChevronRight,
  Lock,
  ShieldAlert,
  Trash2,
  AlertTriangle,
  Users,
} from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';
import { refreshUser, clearUser, loadSessionId } from '../src/session';
import { api } from '../src/api';
import { formatUid } from '../src/ids';
import { AvatarRing } from '../src/components/AvatarRing';
import { BottomTabBar } from '../src/components/redesign/BottomTabBar';
import { SquadPayMark } from '../src/components/redesign/SquadPayMark';
import { useBrand } from '../src/hooks/useBrand';

type Row = {
  key: string;
  label: string;
  sub?: string;
  icon: React.ComponentType<{ size: number; color: string }>;
  onPress: () => void;
  destructive?: boolean;
  hidden?: boolean;
};

export default function SettingsScreen() {
  const router = useRouter();
  const brand = useBrand();
  const [user, setUser] = useState<Awaited<ReturnType<typeof refreshUser>>>(null);
  const [features, setFeatures] = useState<{ credits_enabled: boolean; invite_friends_enabled: boolean }>({ credits_enabled: true, invite_friends_enabled: true });
  // Delete-account modal state
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteStep, setDeleteStep] = useState<'confirm' | 'typing' | 'submitting' | 'done'>('confirm');
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [deleteReason, setDeleteReason] = useState('');
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteResult, setDeleteResult] = useState<{ scheduled_purge_at: string; grace_days: number } | null>(null);

  useEffect(() => {
    (async () => {
      const u = await refreshUser();
      if (!u) {
        router.replace('/');
        return;
      }
      setUser(u);
      api.getAppFeatures().then(setFeatures).catch(() => {});
    })();
  }, [router]);

  const onLogout = async () => {
    const doLogout = async () => {
      try { await api.logout(user?.id || ''); } catch {}
      await clearUser();
      router.replace('/');
    };
    if (Platform.OS === 'web') {
      doLogout();
    } else {
      Alert.alert('Sign out?', 'You will be signed out of SquadPay on this device.', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Sign out', style: 'destructive', onPress: doLogout },
      ]);
    }
  };

  const onOpenDelete = () => {
    setDeleteOpen(true);
    setDeleteStep('confirm');
    setDeleteConfirmText('');
    setDeleteReason('');
    setDeleteError(null);
    setDeleteResult(null);
  };

  const onConfirmDelete = async () => {
    if (!user?.id) return;
    if (deleteConfirmText.trim().toUpperCase() !== 'DELETE') {
      setDeleteError('Please type DELETE in capital letters to confirm.');
      return;
    }
    setDeleteError(null);
    setDeleteStep('submitting');
    try {
      const sid = (await loadSessionId()) || '';
      const res = await api.deleteMyAccount(user.id, sid, deleteReason);
      setDeleteResult({
        scheduled_purge_at: res.scheduled_purge_at,
        grace_days: res.grace_days,
      });
      setDeleteStep('done');
    } catch (e: any) {
      setDeleteError(e?.message || 'Could not delete account. Please try again.');
      setDeleteStep('typing');
    }
  };

  const onDeleteDone = async () => {
    setDeleteOpen(false);
    await clearUser();
    router.replace('/');
  };

  const rows: Row[] = [
    {
      key: 'credits',
      label: 'Credits & rewards',
      sub: 'See your pending and available credits.',
      icon: Wallet,
      onPress: () => router.push('/credits' as any),
      // June 2025 — always visible now that the credit-rules engine ships
      // pending/available balances per user.
    },
    {
      key: 'invite',
      label: 'Invite friends',
      sub: 'Share your code, both earn credits.',
      icon: Gift,
      onPress: () => router.push('/invite'),
      hidden: !features.invite_friends_enabled,
    },
    {
      // June 2026 — Squad was demoted from the bottom tab bar (replaced by
      // Support). It still has its own screen but is now reached as a
      // Settings row since it's a contacts directory rather than a
      // primary navigation destination.
      key: 'squad',
      label: 'Friends & Squad',
      sub: 'See the people you split with most.',
      icon: Users,
      onPress: () => router.push('/squad'),
    },
    {
      key: 'verify',
      label: 'Verify phone',
      sub: 'Required to pay or repay.',
      icon: ShieldAlert,
      onPress: () => router.push(`/auth?mode=verify&user_id=${user?.id || ''}`),
      hidden: !!user?.verified,
    },
    {
      key: 'support',
      label: 'Support',
      sub: 'FAQ and contact options.',
      icon: HelpCircle,
      onPress: () => router.push('/legal/support'),
    },
    {
      key: 'contact',
      label: 'Contact Us',
      sub: 'Send our team a message — we get back fast.',
      icon: Mail,
      onPress: () => router.push('/contact' as any),
    },
    {
      key: 'privacy',
      label: 'Privacy Policy',
      icon: ShieldCheck,
      onPress: () => router.push('/legal/privacy'),
    },
    {
      key: 'terms',
      label: 'Terms & Conditions',
      icon: FileText,
      onPress: () => router.push('/legal/terms'),
    },
    {
      key: 'delete',
      label: 'Delete account',
      sub: `30‑day grace period. Contact ${brand.support_email} to restore.`,
      icon: Trash2,
      onPress: onOpenDelete,
      destructive: true,
    },
    {
      key: 'logout',
      label: 'Sign out',
      icon: LogOut,
      onPress: onLogout,
      destructive: true,
    },
  ];

  return (
    <SafeAreaView style={styles.container} edges={['top']} testID="settings-screen">
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.replace('/')} style={styles.iconBtn} activeOpacity={0.7} testID="settings-home-btn">
          <ArrowLeft size={20} color={COLORS.text} />
        </TouchableOpacity>
        <SquadPayMark size={28} />
        <View style={{ width: 40 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: SPACING.md, paddingBottom: 120 }}>
        <Text style={styles.heading}>Settings</Text>
        <Text style={styles.subheading}>Manage your account and preferences.</Text>

        {/* Profile card */}
        <View style={styles.profile}>
          <AvatarRing name={user?.name || '?'} seed={user?.id || 'me'} size={56} />
          <View style={{ flex: 1, marginLeft: 12 }}>
            <Text style={styles.profileName}>{user?.name || '—'}</Text>
            <Text style={styles.profileMeta}>{user?.phone || 'no phone on file'}</Text>
            {user?.id ? (
              <Text style={styles.profileUid} testID="settings-uid" selectable>
                {formatUid(user.id)}
              </Text>
            ) : null}
            <Text style={[styles.profileBadge, user?.verified ? styles.verifiedOk : styles.verifiedNo]}>
              {user?.verified ? '● Verified' : '● Unverified'}
            </Text>
          </View>
        </View>

        {rows.filter(r => !r.hidden).map((r) => {
          const Icon = r.icon;
          return (
            <TouchableOpacity
              key={r.key}
              onPress={r.onPress}
              activeOpacity={0.85}
              style={[styles.row, r.destructive && styles.rowDestructive]}
              testID={`settings-row-${r.key}`}
            >
              <View style={[styles.rowIcon, r.destructive ? styles.rowIconDanger : styles.rowIconNormal]}>
                <Icon size={18} color={r.destructive ? COLORS.danger : COLORS.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[styles.rowLabel, r.destructive && styles.rowLabelDanger]}>{r.label}</Text>
                {r.sub ? <Text style={styles.rowSub}>{r.sub}</Text> : null}
              </View>
              {!r.destructive ? <ChevronRight size={16} color={COLORS.subtext} /> : null}
            </TouchableOpacity>
          );
        })}

        <Text style={styles.copyright}>© 2026 — SquadPay by NueveTech</Text>
      </ScrollView>

      {/* Delete Account confirmation modal */}
      <Modal
        visible={deleteOpen}
        transparent
        animationType="fade"
        onRequestClose={() => deleteStep !== 'submitting' && setDeleteOpen(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <View style={styles.modalHeader}>
              <View style={styles.modalIconWrap}>
                <AlertTriangle size={22} color={COLORS.danger} />
              </View>
              <Text style={styles.modalTitle}>Delete your SquadPay account?</Text>
            </View>

            {deleteStep !== 'done' ? (
              <>
                <Text style={styles.modalBody}>
                  • Your account will be scheduled for deletion immediately.{"\n"}
                  • You will have a 30-day grace period to restore it by emailing{' '}
                  <Text style={styles.modalEmail}>{brand.support_email}</Text>.{"\n"}
                  • After 30 days, your personal information (name, phone, email) will be
                  permanently removed.{"\n"}
                  • Past squad activity required for compliance & open balances will be
                  retained in anonymised form.
                </Text>

                <Text style={styles.modalLabel}>Reason (optional)</Text>
                <TextInput
                  value={deleteReason}
                  onChangeText={setDeleteReason}
                  placeholder="Tell us why you're leaving — it helps us improve."
                  placeholderTextColor={COLORS.subtext}
                  multiline
                  maxLength={500}
                  style={styles.modalInputMulti}
                  editable={deleteStep !== 'submitting'}
                />

                <Text style={styles.modalLabel}>Type DELETE to confirm</Text>
                <TextInput
                  value={deleteConfirmText}
                  onChangeText={(t) => { setDeleteConfirmText(t); setDeleteError(null); }}
                  autoCapitalize="characters"
                  autoCorrect={false}
                  placeholder="DELETE"
                  placeholderTextColor={COLORS.subtext}
                  style={styles.modalInput}
                  editable={deleteStep !== 'submitting'}
                />

                {deleteError ? <Text style={styles.modalError}>{deleteError}</Text> : null}

                <View style={styles.modalActions}>
                  <TouchableOpacity
                    style={[styles.modalBtn, styles.modalBtnSecondary]}
                    onPress={() => setDeleteOpen(false)}
                    disabled={deleteStep === 'submitting'}
                  >
                    <Text style={styles.modalBtnSecondaryText}>Cancel</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[
                      styles.modalBtn,
                      styles.modalBtnDanger,
                      deleteConfirmText.trim().toUpperCase() !== 'DELETE' && { opacity: 0.5 },
                    ]}
                    onPress={onConfirmDelete}
                    disabled={
                      deleteStep === 'submitting' ||
                      deleteConfirmText.trim().toUpperCase() !== 'DELETE'
                    }
                  >
                    {deleteStep === 'submitting' ? (
                      <ActivityIndicator color="#fff" />
                    ) : (
                      <Text style={styles.modalBtnDangerText}>Delete my account</Text>
                    )}
                  </TouchableOpacity>
                </View>
              </>
            ) : (
              <>
                <Text style={styles.modalBody}>
                  Your account has been scheduled for deletion. You can still restore it
                  within {deleteResult?.grace_days ?? 30} days by emailing{' '}
                  <Text style={styles.modalEmail}>{brand.support_email}</Text>.{"\n\n"}
                  Permanent purge scheduled:{' '}
                  <Text style={{ fontWeight: '700' }}>
                    {deleteResult?.scheduled_purge_at
                      ? new Date(deleteResult.scheduled_purge_at).toDateString()
                      : '—'}
                  </Text>
                </Text>
                <TouchableOpacity
                  style={[styles.modalBtn, styles.modalBtnDanger]}
                  onPress={onDeleteDone}
                >
                  <Text style={styles.modalBtnDangerText}>Sign me out</Text>
                </TouchableOpacity>
              </>
            )}
          </View>
        </View>
      </Modal>

      <BottomTabBar active="settings" />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: SPACING.md, paddingTop: SPACING.sm },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: 28, fontWeight: FONT.weights.bold, color: COLORS.text, letterSpacing: -0.5 },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 4, marginBottom: SPACING.md },
  profile: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.md,
  },
  profileName: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  profileMeta: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  profileUid: {
    fontSize: 11,
    color: COLORS.subtext,
    marginTop: 2,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    letterSpacing: 0.6,
  },
  profileBadge: { fontSize: 11, fontWeight: FONT.weights.bold, marginTop: 4 },
  verifiedOk: { color: COLORS.success },
  verifiedNo: { color: COLORS.warning },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: SPACING.md,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: 8,
  },
  rowDestructive: { borderColor: COLORS.dangerLight, backgroundColor: COLORS.dangerLight },
  rowIcon: { width: 38, height: 38, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  rowIconNormal: { backgroundColor: COLORS.primaryLight },
  rowIconDanger: { backgroundColor: '#fff' },
  rowLabel: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text },
  rowLabelDanger: { color: COLORS.danger },
  rowSub: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  copyright: { textAlign: 'center', fontSize: 11, color: COLORS.subtext, marginTop: SPACING.lg },
  // Delete-account modal
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.55)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: SPACING.md,
  },
  modalCard: {
    width: '100%',
    maxWidth: 480,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  modalHeader: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 12 },
  modalIconWrap: {
    width: 40, height: 40, borderRadius: 20,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: COLORS.dangerLight,
  },
  modalTitle: { flex: 1, fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  modalBody: { fontSize: FONT.sizes.sm, color: COLORS.text, lineHeight: 20, marginBottom: 12 },
  modalEmail: { color: COLORS.primary, fontWeight: FONT.weights.semibold },
  modalLabel: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 8, marginBottom: 4, fontWeight: FONT.weights.semibold },
  modalInput: {
    borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md,
    paddingHorizontal: 12, paddingVertical: 10, color: COLORS.text,
    fontSize: FONT.sizes.md, backgroundColor: COLORS.bg,
  },
  modalInputMulti: {
    borderWidth: 1, borderColor: COLORS.border, borderRadius: RADIUS.md,
    paddingHorizontal: 12, paddingVertical: 10, color: COLORS.text,
    fontSize: FONT.sizes.sm, backgroundColor: COLORS.bg,
    minHeight: 64, textAlignVertical: 'top',
  },
  modalError: { color: COLORS.danger, fontSize: FONT.sizes.xs, marginTop: 6 },
  modalActions: { flexDirection: 'row', gap: 8, marginTop: 16 },
  modalBtn: {
    flex: 1, paddingVertical: 12, borderRadius: RADIUS.md,
    alignItems: 'center', justifyContent: 'center', minHeight: 44,
  },
  modalBtnSecondary: { backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border },
  modalBtnSecondaryText: { fontWeight: FONT.weights.semibold, color: COLORS.text },
  modalBtnDanger: { backgroundColor: COLORS.danger },
  modalBtnDangerText: { fontWeight: FONT.weights.bold, color: '#fff' },
});
