/**
 * Contact Us screen — user-facing form (June 2025).
 *
 * Subject dropdown + name + email + message. We silently attach the
 * authenticated user's ID; the backend looks up the phone from the
 * server-side `users` record (never trusted client-side).
 */
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { ArrowLeft, Send, CheckCircle2, AlertCircle, ChevronDown } from 'lucide-react-native';
import { api } from '../src/api';
import { loadUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';
import { friendlyError } from '../src/errors';

type Subject = 'general_enquiry' | 'technical_support' | 'account_refund' | 'others';

const SUBJECTS: { value: Subject; label: string }[] = [
  { value: 'general_enquiry', label: 'General Enquiry' },
  { value: 'technical_support', label: 'Technical Support' },
  { value: 'account_refund', label: 'Account & Refund' },
  { value: 'others', label: 'Others' },
];

export default function ContactUsScreen() {
  const router = useRouter();
  const [userId, setUserId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [subject, setSubject] = useState<Subject>('general_enquiry');
  const [message, setMessage] = useState('');
  const [showSubjectMenu, setShowSubjectMenu] = useState(false);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const u = await loadUser();
      if (u) {
        setUserId(u.id);
        setName(u.name || '');
      }
    })();
  }, []);

  const submit = async () => {
    setErr(null);
    setSuccess(null);
    if (!name.trim()) { setErr('Please enter your name.'); return; }
    if (!email.trim() || !/.+@.+\..+/.test(email)) { setErr('Please enter a valid email.'); return; }
    if (!message.trim() || message.trim().length < 4) { setErr('Please share a few words about what you need.'); return; }
    setSending(true);
    try {
      const r = await api.submitContact({
        name: name.trim(),
        email: email.trim(),
        subject,
        message: message.trim(),
        user_id: userId,
      });
      setSuccess(
        `Thanks! Ticket ${r.ticket_id} has been logged.` +
        (r.email_dispatched ? " We've also emailed our team." : ' Our team will pick it up shortly.'),
      );
      setMessage('');
    } catch (e: any) {
      setErr(friendlyError(e, "We couldn't send your message. Please try again."));
    } finally {
      setSending(false);
    }
  };

  const subjLabel = SUBJECTS.find((s) => s.value === subject)?.label || '';

  return (
    <SafeAreaView edges={['top', 'bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.canGoBack() ? router.back() : router.replace('/settings')}
          style={styles.backBtn}
          activeOpacity={0.7}
        >
          <ArrowLeft size={20} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Contact Us</Text>
        <View style={{ width: 40 }} />
      </View>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={{ padding: SPACING.lg, gap: SPACING.sm }} keyboardShouldPersistTaps="handled">
          <Text style={styles.subtle}>
            Have a question, found a bug, or need a refund? Send us a note —
            we'll get back to you at the email you provide below.
          </Text>

          <Text style={styles.label}>Your name</Text>
          <TextInput value={name} onChangeText={setName} style={styles.input} placeholder="Your name" placeholderTextColor={COLORS.disabledText} />

          <Text style={styles.label}>Your email</Text>
          <TextInput value={email} onChangeText={setEmail} style={styles.input} placeholder="you@example.com" placeholderTextColor={COLORS.disabledText} keyboardType="email-address" autoCapitalize="none" autoCorrect={false} />

          <Text style={styles.label}>Subject</Text>
          <TouchableOpacity
            onPress={() => setShowSubjectMenu((s) => !s)}
            style={[styles.input, { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }]}
            activeOpacity={0.85}
            testID="contact-subject-toggle"
          >
            <Text style={{ color: COLORS.text, fontSize: FONT.sizes.md }}>{subjLabel}</Text>
            <ChevronDown size={16} color={COLORS.subtext} />
          </TouchableOpacity>
          {showSubjectMenu ? (
            <View style={styles.menu}>
              {SUBJECTS.map((opt) => (
                <TouchableOpacity
                  key={opt.value}
                  onPress={() => { setSubject(opt.value); setShowSubjectMenu(false); }}
                  style={[styles.menuItem, subject === opt.value && { backgroundColor: COLORS.primaryLight }]}
                  activeOpacity={0.85}
                  testID={`contact-subject-${opt.value}`}
                >
                  <Text style={[styles.menuText, subject === opt.value && { color: COLORS.primary, fontWeight: FONT.weights.bold }]}>{opt.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
          ) : null}

          <Text style={styles.label}>Message</Text>
          <TextInput
            value={message} onChangeText={setMessage} multiline
            style={[styles.input, { minHeight: 120, textAlignVertical: 'top' }]}
            placeholder="What can we help you with?" placeholderTextColor={COLORS.disabledText}
          />

          {err ? (
            <View style={styles.errBanner}><AlertCircle size={14} color={COLORS.danger} /><Text style={styles.errText}>{err}</Text></View>
          ) : null}
          {success ? (
            <View style={styles.okBanner}><CheckCircle2 size={14} color={COLORS.success} /><Text style={styles.okText}>{success}</Text></View>
          ) : null}

          <TouchableOpacity
            onPress={submit} disabled={sending}
            style={[styles.sendBtn, sending && { opacity: 0.7 }]} activeOpacity={0.85}
            testID="contact-submit-btn"
          >
            {sending ? <ActivityIndicator color="#fff" /> : (
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <Send size={16} color="#fff" />
                <Text style={styles.sendBtnText}>Send message</Text>
              </View>
            )}
          </TouchableOpacity>
          <View style={{ height: 80 }} />
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm,
    borderBottomWidth: 1, borderBottomColor: COLORS.border, backgroundColor: COLORS.surface,
  },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: COLORS.bg, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: COLORS.border },
  title: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  subtle: { color: COLORS.subtext, fontSize: FONT.sizes.sm, lineHeight: 20, marginBottom: SPACING.sm },
  label: { fontSize: FONT.sizes.xs, color: COLORS.subtext, fontWeight: FONT.weights.semibold, textTransform: 'uppercase', letterSpacing: 1, marginTop: SPACING.sm },
  input: {
    borderRadius: RADIUS.md, borderWidth: 1.5, borderColor: COLORS.border,
    backgroundColor: COLORS.surface, paddingHorizontal: SPACING.md,
    paddingVertical: Platform.OS === 'ios' ? 10 : 8,
    fontSize: FONT.sizes.md, color: COLORS.text,
  },
  menu: { borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.surface, overflow: 'hidden' },
  menuItem: { paddingHorizontal: SPACING.md, paddingVertical: 10 },
  menuText: { color: COLORS.text, fontSize: FONT.sizes.md },
  errBanner: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: COLORS.dangerLight, borderRadius: RADIUS.md, padding: 10 },
  errText: { color: COLORS.danger, fontSize: FONT.sizes.sm, flex: 1 },
  okBanner: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: COLORS.successLight, borderRadius: RADIUS.md, padding: 10 },
  okText: { color: COLORS.success, fontSize: FONT.sizes.sm, flex: 1 },
  sendBtn: { marginTop: SPACING.md, backgroundColor: COLORS.primary, borderRadius: RADIUS.md, height: 48, alignItems: 'center', justifyContent: 'center' },
  sendBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.md },
});
