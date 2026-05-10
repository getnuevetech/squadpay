/**
 * Admin — Legal page editor.
 * URL: /admin/legal-pages/[slug]  (slug = support | privacy | terms)
 *
 * Approach:
 * - Single textarea-based HTML editor with a small toolbar that wraps the
 *   selected text in common tags (h2/h3/h4/p/strong/em/ul/ol/li/a/br) or
 *   inserts a tag at the cursor.
 * - Live preview rendered with the same <LegalHtml/> component used on the
 *   public legal pages, so admins see exactly what users will see.
 * - Image/video uploads call POST /api/admin/legal/upload (multipart) and the
 *   returned `<img src=…>` tag is inserted at the cursor. Native (Expo Go)
 *   uses expo-image-picker; web uses an <input type="file"> via DOM.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  TextInput as RNTextInput,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import {
  ArrowLeft,
  Save,
  Image as ImageIcon,
  Eye,
  Code as CodeIcon,
  Bold,
  Italic,
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  Link as LinkIcon,
  Quote,
  RotateCcw,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react-native';
import * as ImagePicker from 'expo-image-picker';
import { adminApi, LegalPage } from '../../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { LegalHtml } from '../../../src/components/LegalHtml';

type Slug = 'support' | 'privacy' | 'terms';
const VALID: Slug[] = ['support', 'privacy', 'terms'];

const SLUG_LABEL: Record<Slug, string> = {
  support: 'Support',
  privacy: 'Privacy Policy',
  terms: 'Terms & Conditions',
};

export default function AdminLegalPageEditor() {
  const { slug: rawSlug } = useLocalSearchParams<{ slug: string }>();
  const router = useRouter();
  const slug = (VALID.includes(rawSlug as Slug) ? (rawSlug as Slug) : null);

  const [page, setPage] = useState<LegalPage | null>(null);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [originalContent, setOriginalContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [view, setView] = useState<'edit' | 'preview'>('edit');
  const [toast, setToast] = useState<{ kind: 'ok' | 'err'; msg: string } | null>(null);
  const taRef = useRef<RNTextInput | null>(null);
  // Track selection for tag-wrapping. Falls back to "insert at end" if unknown.
  const [selection, setSelection] = useState<{ start: number; end: number }>({ start: 0, end: 0 });

  const dirty = content !== originalContent || (page && title !== page.title);

  const load = useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    try {
      const res = await adminApi.listLegalPages();
      const found = res.pages.find((p) => p.slug === slug);
      if (!found) throw new Error('Page not found');
      setPage(found);
      setTitle(found.title);
      setContent(found.content_html);
      setOriginalContent(found.content_html);
    } catch (e: any) {
      setToast({ kind: 'err', msg: e?.message || 'Failed to load page' });
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  // ──────────────── Toolbar helpers ────────────────

  const replaceSelection = useCallback(
    (mutate: (selected: string) => string) => {
      const { start, end } = selection;
      const before = content.slice(0, start);
      const sel = content.slice(start, end);
      const after = content.slice(end);
      const replaced = mutate(sel);
      setContent(before + replaced + after);
      // Re-focus textarea so user can keep typing.
      setTimeout(() => taRef.current?.focus(), 30);
    },
    [content, selection],
  );

  const wrapTag = (tag: string) =>
    replaceSelection((sel) => {
      const inner = sel || `${tag} text`;
      return `<${tag}>${inner}</${tag}>`;
    });

  const insertBlock = (open: string, close: string, placeholder: string) =>
    replaceSelection((sel) => `${open}${sel || placeholder}${close}`);

  const insertLink = () => {
    const promptFn: (msg: string, def?: string) => string | null =
      typeof window !== 'undefined' && (window as any).prompt
        ? (m, d) => (window as any).prompt(m, d || '')
        : (m) => {
            // Native fallback — prompt unavailable; log a hint instead.
            console.log(m);
            return null;
          };
    const url = promptFn('Link URL', 'https://');
    if (!url) return;
    replaceSelection((sel) => `<a href="${url}">${sel || url}</a>`);
  };

  const insertList = (ordered: boolean) => {
    const tag = ordered ? 'ol' : 'ul';
    replaceSelection((sel) => {
      const items = (sel || 'First item\nSecond item').split(/\n+/).filter(Boolean);
      return `<${tag}>\n${items.map((i) => `  <li>${i}</li>`).join('\n')}\n</${tag}>`;
    });
  };

  // ──────────────── Image / video upload ────────────────

  const onPickAndUpload = useCallback(async () => {
    try {
      setUploading(true);
      let asset: { uri: string; mimeType?: string | null; fileName?: string | null; type?: string | null } | null = null;

      if (Platform.OS === 'web') {
        // Web: use native <input type="file"> for direct File access.
        const file: File | null = await new Promise((resolve) => {
          const input = document.createElement('input');
          input.type = 'file';
          input.accept = 'image/*,video/*';
          input.onchange = () => resolve(input.files && input.files[0] ? input.files[0] : null);
          input.click();
        });
        if (!file) {
          setUploading(false);
          return;
        }
        const res = await adminApi.uploadLegalMedia({
          blob: file,
          name: file.name,
          mime: file.type || 'application/octet-stream',
        });
        const mime = file.type || '';
        const tag = mime.startsWith('video/')
          ? `<video src="${res.url}" controls style="max-width:100%"></video>`
          : `<img src="${res.url}" alt="" style="max-width:100%" />`;
        replaceSelection(() => `\n${tag}\n`);
        setToast({ kind: 'ok', msg: 'Uploaded' });
      } else {
        // Native: expo-image-picker (images + videos).
        const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!perm.granted) {
          Alert.alert('Permission denied', 'Cannot access media library.');
          setUploading(false);
          return;
        }
        const result = await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.All,
          quality: 0.8,
        });
        if (result.canceled || !result.assets || result.assets.length === 0) {
          setUploading(false);
          return;
        }
        asset = result.assets[0] as any;
        if (!asset) {
          setUploading(false);
          return;
        }
        const mime = asset.mimeType || (asset.type === 'video' ? 'video/mp4' : 'image/jpeg');
        const fileName = asset.fileName || `upload.${mime.split('/')[1] || 'bin'}`;
        const res = await adminApi.uploadLegalMedia({
          uri: asset.uri,
          name: fileName,
          mime,
        });
        const tag = mime.startsWith('video/')
          ? `<video src="${res.url}" controls style="max-width:100%"></video>`
          : `<img src="${res.url}" alt="" style="max-width:100%" />`;
        replaceSelection(() => `\n${tag}\n`);
        setToast({ kind: 'ok', msg: 'Uploaded' });
      }
    } catch (e: any) {
      setToast({ kind: 'err', msg: e?.message || 'Upload failed' });
    } finally {
      setUploading(false);
    }
  }, [replaceSelection]);

  // ──────────────── Save ────────────────

  const onSave = useCallback(async () => {
    if (!slug) return;
    if (!title.trim()) {
      setToast({ kind: 'err', msg: 'Title cannot be empty' });
      return;
    }
    setSaving(true);
    try {
      const updated = await adminApi.updateLegalPage(slug, {
        title: title.trim(),
        content_html: content,
      });
      setPage({
        slug,
        title: updated.title,
        content_html: updated.content_html,
        updated_at: updated.updated_at,
        updated_by: updated.updated_by,
        is_default: false,
      });
      setOriginalContent(updated.content_html);
      setToast({ kind: 'ok', msg: 'Saved' });
    } catch (e: any) {
      setToast({ kind: 'err', msg: e?.message || 'Save failed' });
    } finally {
      setSaving(false);
    }
  }, [slug, title, content]);

  const onRevert = useCallback(() => {
    if (!page) return;
    setContent(originalContent);
    setTitle(page.title);
  }, [page, originalContent]);

  // Auto-clear toast after 2.5s.
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2500);
    return () => clearTimeout(t);
  }, [toast]);

  if (!slug) {
    return (
      <View style={styles.center}>
        <Text style={styles.errorText}>Unknown legal page slug.</Text>
      </View>
    );
  }
  if (loading) {
    return (
      <View style={styles.center} testID="admin-legal-edit-loading">
        <ActivityIndicator color={COLORS.primary} />
      </View>
    );
  }

  return (
    <ScrollView
      contentContainerStyle={{ paddingBottom: 80 }}
      testID={`admin-legal-edit-${slug}`}
      keyboardShouldPersistTaps="handled"
    >
      <TouchableOpacity
        onPress={() => router.replace('/admin/legal-pages')}
        style={styles.backBtn}
        activeOpacity={0.7}
        testID="admin-legal-back"
      >
        <ArrowLeft size={16} color={COLORS.subtext} />
        <Text style={styles.backText}>All legal pages</Text>
      </TouchableOpacity>

      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: SPACING.md, gap: SPACING.sm, flexWrap: 'wrap' }}>
        <View>
          <Text style={styles.heading}>{SLUG_LABEL[slug]}</Text>
          <Text style={styles.subheading}>
            URL: /legal/{slug} · {page?.is_default ? 'Showing default copy' : `Last edited ${page?.updated_at ? new Date(page.updated_at).toLocaleString() : '—'}`}
          </Text>
        </View>
        <View style={{ flexDirection: 'row', gap: 6 }}>
          <TouchableOpacity
            onPress={() => setView(view === 'edit' ? 'preview' : 'edit')}
            style={[styles.viewToggle, view === 'preview' && styles.viewToggleActive]}
            activeOpacity={0.85}
            testID="admin-legal-view-toggle"
          >
            {view === 'edit' ? (
              <>
                <Eye size={14} color={COLORS.text} />
                <Text style={styles.viewToggleText}>Preview</Text>
              </>
            ) : (
              <>
                <CodeIcon size={14} color="#fff" />
                <Text style={[styles.viewToggleText, { color: '#fff' }]}>Edit HTML</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </View>

      {/* Title */}
      <Text style={styles.label}>Page title</Text>
      <TextInput
        style={styles.titleInput}
        value={title}
        onChangeText={setTitle}
        placeholder="Privacy Policy"
        placeholderTextColor={COLORS.disabledText}
        testID="admin-legal-title"
      />

      {view === 'edit' ? (
        <>
          {/* Toolbar */}
          <View style={styles.toolbar}>
            <ToolBtn icon={<Heading1 size={14} color={COLORS.text} />} label="H2" onPress={() => wrapTag('h2')} testID="tb-h2" />
            <ToolBtn icon={<Heading2 size={14} color={COLORS.text} />} label="H3" onPress={() => wrapTag('h3')} testID="tb-h3" />
            <ToolBtn icon={<Heading3 size={14} color={COLORS.text} />} label="H4" onPress={() => wrapTag('h4')} testID="tb-h4" />
            <ToolBtn icon={<Quote size={14} color={COLORS.text} />} label="P" onPress={() => wrapTag('p')} testID="tb-p" />
            <ToolBtn icon={<Bold size={14} color={COLORS.text} />} label="Bold" onPress={() => wrapTag('strong')} testID="tb-bold" />
            <ToolBtn icon={<Italic size={14} color={COLORS.text} />} label="Italic" onPress={() => wrapTag('em')} testID="tb-italic" />
            <ToolBtn icon={<List size={14} color={COLORS.text} />} label="Bullets" onPress={() => insertList(false)} testID="tb-ul" />
            <ToolBtn icon={<ListOrdered size={14} color={COLORS.text} />} label="Numbers" onPress={() => insertList(true)} testID="tb-ol" />
            <ToolBtn icon={<LinkIcon size={14} color={COLORS.text} />} label="Link" onPress={insertLink} testID="tb-link" />
            <ToolBtn
              icon={uploading ? <ActivityIndicator size="small" color={COLORS.primary} /> : <ImageIcon size={14} color={COLORS.primary} />}
              label={uploading ? 'Uploading…' : 'Image / Video'}
              onPress={onPickAndUpload}
              testID="tb-upload"
              primary
              disabled={uploading}
            />
          </View>

          {/* Editor textarea */}
          <TextInput
            ref={taRef as any}
            multiline
            value={content}
            onChangeText={setContent}
            onSelectionChange={(e) => setSelection(e.nativeEvent.selection)}
            placeholder="<h2>Hello</h2>\n<p>Page content here…</p>"
            placeholderTextColor={COLORS.disabledText}
            style={styles.editor}
            scrollEnabled={false}
            textAlignVertical="top"
            autoCapitalize="none"
            autoCorrect={false}
            spellCheck={false}
            testID="admin-legal-editor-textarea"
          />
          <Text style={styles.helpText}>
            HTML is allowed (h2/h3/h4, p, ul/ol/li, strong, em, a, img, video, br, hr).
            Scripts and event handlers are stripped on save.
          </Text>
        </>
      ) : (
        <View style={styles.previewBox} testID="admin-legal-preview">
          <LegalHtml html={content} />
        </View>
      )}

      {/* Footer actions */}
      <View style={styles.footerRow}>
        <TouchableOpacity
          onPress={onRevert}
          disabled={!dirty || saving}
          style={[styles.secondaryBtn, (!dirty || saving) && { opacity: 0.5 }]}
          activeOpacity={0.85}
          testID="admin-legal-revert"
        >
          <RotateCcw size={14} color={COLORS.subtext} />
          <Text style={styles.secondaryBtnText}>Revert</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={onSave}
          disabled={!dirty || saving}
          style={[styles.primaryBtn, (!dirty || saving) && { opacity: 0.6 }]}
          activeOpacity={0.85}
          testID="admin-legal-save"
        >
          {saving ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <>
              <Save size={14} color="#fff" />
              <Text style={styles.primaryBtnText}>{dirty ? 'Save changes' : 'Saved'}</Text>
            </>
          )}
        </TouchableOpacity>
      </View>

      {toast ? (
        <View
          style={[styles.toast, toast.kind === 'ok' ? styles.toastOk : styles.toastErr]}
          testID={`admin-legal-toast-${toast.kind}`}
        >
          {toast.kind === 'ok' ? (
            <CheckCircle2 size={14} color="#fff" />
          ) : (
            <AlertTriangle size={14} color="#fff" />
          )}
          <Text style={styles.toastText}>{toast.msg}</Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

function ToolBtn({
  icon,
  label,
  onPress,
  testID,
  primary,
  disabled,
}: {
  icon: React.ReactNode;
  label: string;
  onPress: () => void;
  testID?: string;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <TouchableOpacity
      onPress={onPress}
      style={[styles.toolBtn, primary && styles.toolBtnPrimary, disabled && { opacity: 0.6 }]}
      activeOpacity={0.85}
      testID={testID}
      disabled={disabled}
    >
      {icon}
      <Text style={[styles.toolBtnText, primary && { color: COLORS.primary, fontWeight: FONT.weights.bold }]}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.lg },
  backBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: SPACING.md },
  backText: { color: COLORS.subtext, fontSize: FONT.sizes.sm, fontWeight: FONT.weights.medium },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.xs, color: COLORS.subtext, marginTop: 2 },
  viewToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: RADIUS.pill,
    borderWidth: 1,
    borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
  },
  viewToggleActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  viewToggleText: { fontSize: FONT.sizes.xs, fontWeight: FONT.weights.bold, color: COLORS.text },
  label: {
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    fontWeight: FONT.weights.medium,
    marginBottom: 4,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  titleInput: {
    height: 44,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    paddingHorizontal: SPACING.md,
    color: COLORS.text,
    backgroundColor: COLORS.surface,
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.semibold,
    marginBottom: SPACING.md,
  },
  toolbar: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    padding: 8,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    marginBottom: SPACING.sm,
  },
  toolBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 6,
    backgroundColor: COLORS.bg,
    borderRadius: RADIUS.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  toolBtnPrimary: { backgroundColor: COLORS.primaryLight, borderColor: COLORS.primary },
  toolBtnText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.medium },
  editor: {
    minHeight: 360,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.md,
    color: COLORS.text,
    backgroundColor: COLORS.surface,
    fontSize: 13,
    lineHeight: 20,
    fontFamily: Platform.OS === 'web' ? 'monospace' : Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  helpText: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 6 },
  previewBox: {
    padding: SPACING.lg,
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    minHeight: 360,
  },
  footerRow: {
    flexDirection: 'row',
    gap: SPACING.sm,
    marginTop: SPACING.lg,
    justifyContent: 'flex-end',
  },
  primaryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: COLORS.primary,
    paddingHorizontal: SPACING.lg,
    paddingVertical: 10,
    borderRadius: RADIUS.md,
  },
  primaryBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm },
  secondaryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: COLORS.surface,
    paddingHorizontal: SPACING.md,
    paddingVertical: 10,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  secondaryBtnText: { color: COLORS.subtext, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  errorText: { color: COLORS.danger, fontSize: FONT.sizes.md },
  toast: {
    position: 'absolute',
    bottom: 24,
    left: 16,
    right: 16,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: SPACING.md,
    paddingVertical: 10,
    borderRadius: RADIUS.md,
  },
  toastOk: { backgroundColor: COLORS.success },
  toastErr: { backgroundColor: COLORS.danger },
  toastText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.sm, flex: 1 },
});
