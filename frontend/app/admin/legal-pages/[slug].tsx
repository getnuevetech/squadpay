/**
 * Admin → Legal page editor (rebuilt May 2026).
 *
 * Goals
 * -----
 * - Admin never sees raw HTML. Storage is **markdown**.
 * - Toolbar buttons wrap / insert markdown syntax around the selection so
 *   the admin gets a Slack/Discord-style "type-or-click" experience.
 * - Live preview shows exactly what users will see, rendered by `marked`
 *   on the client into HTML and then by the existing `<LegalHtml/>`
 *   component (same renderer the public pages use, so WYSIWYG parity).
 * - Image upload still posts to /api/admin/legal/upload and inserts a
 *   markdown image tag `![](url)` at the cursor.
 *
 * Backwards compat: legacy pages that only had `content_html` get a
 * server-side html→md conversion (html2text) on first read, so the editor
 * always opens with valid markdown.
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
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import {
  ArrowLeft,
  Save,
  Image as ImageIcon,
  Eye,
  Pencil,
  Bold,
  Italic,
  Heading2,
  Heading3,
  Heading4,
  List as ListIcon,
  ListOrdered,
  Link as LinkIcon,
  Quote,
  Strikethrough,
  Code as CodeIcon,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react-native';
import * as ImagePicker from 'expo-image-picker';
import { marked } from 'marked';
import { legalApi, LegalPage } from '../../../src/adminApi/legal';
import { COLORS, FONT, RADIUS, SPACING } from '../../../src/theme';
import { LegalHtml } from '../../../src/components/LegalHtml';

type Slug = 'support' | 'privacy' | 'terms';
const VALID: Slug[] = ['support', 'privacy', 'terms'];
const SLUG_LABEL: Record<Slug, string> = {
  support: 'Support',
  privacy: 'Privacy Policy',
  terms: 'Terms & Conditions',
};

// `marked` v14 — keep GFM-ish, line breaks honored. We don't enable raw
// HTML in markdown (admin should never need it).
marked.setOptions({ gfm: true, breaks: true });

/**
 * Wraps the current selection with a `prefix` and `suffix`, or — when no
 * text is selected — inserts a sensible placeholder so the toolbar always
 * does something useful. The caller decides whether to act on line-level
 * (`linePrefix`) or inline marks.
 */
type Selection = { start: number; end: number };
function applyInlineMark(
  text: string,
  sel: Selection,
  prefix: string,
  suffix = prefix,
  placeholder = 'text',
): { next: string; nextSel: Selection } {
  const { start, end } = sel;
  const selected = text.slice(start, end);
  const body = selected || placeholder;
  const next = text.slice(0, start) + prefix + body + suffix + text.slice(end);
  const nextStart = start + prefix.length;
  const nextEnd = nextStart + body.length;
  return { next, nextSel: { start: nextStart, end: nextEnd } };
}

function applyLinePrefix(
  text: string,
  sel: Selection,
  prefix: string,
): { next: string; nextSel: Selection } {
  // Find the start of the current line.
  const lineStart = text.lastIndexOf('\n', sel.start - 1) + 1;
  // If the line already has the same prefix, toggle it off.
  const alreadyHas = text.slice(lineStart, lineStart + prefix.length) === prefix;
  const next = alreadyHas
    ? text.slice(0, lineStart) + text.slice(lineStart + prefix.length)
    : text.slice(0, lineStart) + prefix + text.slice(lineStart);
  const delta = alreadyHas ? -prefix.length : prefix.length;
  return {
    next,
    nextSel: { start: sel.start + delta, end: sel.end + delta },
  };
}

function insertAtCursor(
  text: string,
  sel: Selection,
  chunk: string,
): { next: string; nextSel: Selection } {
  const next = text.slice(0, sel.start) + chunk + text.slice(sel.end);
  const pos = sel.start + chunk.length;
  return { next, nextSel: { start: pos, end: pos } };
}

export default function LegalPageEditor() {
  const router = useRouter();
  const params = useLocalSearchParams<{ slug?: string }>();
  const slug = (VALID.includes(params.slug as Slug) ? (params.slug as Slug) : 'support') as Slug;

  const [page, setPage] = useState<LegalPage | null>(null);
  const [title, setTitle] = useState('');
  const [markdown, setMarkdown] = useState('');
  const [selection, setSelection] = useState<Selection>({ start: 0, end: 0 });
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const inputRef = useRef<TextInput | null>(null);

  // ── Load existing page ─────────────────────────────────────────────────
  useEffect(() => {
    let cancel = false;
    (async () => {
      setLoading(true);
      try {
        const res = await legalApi.list();
        if (cancel) return;
        const found = res.pages.find((p) => p.slug === slug);
        if (found) {
          setPage(found);
          setTitle(found.title);
          // The new editor is markdown-first. Backend always provides
          // content_md (auto-derived from legacy HTML if needed).
          setMarkdown(found.content_md ?? '');
          setSavedAt(found.updated_at);
        }
      } catch (e: any) {
        Alert.alert('Could not load page', e?.message || 'Unknown error');
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => { cancel = true; };
  }, [slug]);

  // ── Derived: HTML preview rendered from markdown via `marked` ──────────
  const previewHtml = useMemo(() => {
    try {
      return marked.parse(markdown || '', { async: false }) as string;
    } catch {
      return '';
    }
  }, [markdown]);

  // ── Toolbar handlers ──────────────────────────────────────────────────
  const mutate = useCallback(
    (fn: (t: string, s: Selection) => { next: string; nextSel: Selection }) => {
      const { next, nextSel } = fn(markdown, selection);
      setMarkdown(next);
      // Re-focus + re-select after the state flush so the caret lands in
      // the new spot. On native the selection prop is honored when set
      // synchronously after the text change.
      requestAnimationFrame(() => {
        try { inputRef.current?.focus(); } catch {}
        setSelection(nextSel);
      });
    },
    [markdown, selection],
  );

  const onBold = () => mutate((t, s) => applyInlineMark(t, s, '**', '**', 'bold text'));
  const onItalic = () => mutate((t, s) => applyInlineMark(t, s, '*', '*', 'italic text'));
  const onStrike = () => mutate((t, s) => applyInlineMark(t, s, '~~', '~~', 'strikethrough'));
  const onCode = () => mutate((t, s) => applyInlineMark(t, s, '`', '`', 'code'));
  const onH2 = () => mutate((t, s) => applyLinePrefix(t, s, '## '));
  const onH3 = () => mutate((t, s) => applyLinePrefix(t, s, '### '));
  const onH4 = () => mutate((t, s) => applyLinePrefix(t, s, '#### '));
  const onQuote = () => mutate((t, s) => applyLinePrefix(t, s, '> '));
  const onUL = () => mutate((t, s) => applyLinePrefix(t, s, '- '));
  const onOL = () => mutate((t, s) => applyLinePrefix(t, s, '1. '));

  const onLink = useCallback(() => {
    mutate((t, s) => {
      const selected = t.slice(s.start, s.end) || 'link text';
      const chunk = `[${selected}](https://)`;
      const next = t.slice(0, s.start) + chunk + t.slice(s.end);
      // Land caret inside the URL slot.
      const urlStart = s.start + selected.length + 3; // `[` + text + `](`
      return { next, nextSel: { start: urlStart, end: urlStart + 8 } };
    });
  }, [mutate]);

  // ── Image upload ──────────────────────────────────────────────────────
  const onImage = useCallback(async () => {
    try {
      if (Platform.OS !== 'web') {
        const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!perm.granted) {
          Alert.alert('Permission needed', 'Allow photo library access to insert an image.');
          return;
        }
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 0.9,
        // On web we need a blob; on native we need a uri. Image-picker
        // hands us both via `asset.uri`. The backend accepts either via
        // multipart, and `legalApi.uploadMedia` translates accordingly.
      });
      if (result.canceled) return;
      const asset = result.assets?.[0];
      if (!asset) return;
      setUploading(true);

      let blob: Blob | undefined;
      if (Platform.OS === 'web' && asset.uri?.startsWith('data:')) {
        const r = await fetch(asset.uri);
        blob = await r.blob();
      }
      const mime = asset.mimeType || 'image/jpeg';
      const name = (asset.fileName || `legal-${Date.now()}.jpg`).replace(/[^\w.\-]/g, '_');
      const uploaded = await legalApi.uploadMedia({
        uri: asset.uri,
        blob,
        name,
        mime,
      });
      // Insert the markdown image tag at the caret.
      mutate((t, s) => insertAtCursor(t, s, `\n![](${uploaded.url})\n`));
    } catch (e: any) {
      Alert.alert('Upload failed', e?.message || 'Could not upload image');
    } finally {
      setUploading(false);
    }
  }, [mutate]);

  // ── Save ──────────────────────────────────────────────────────────────
  const onSave = useCallback(async () => {
    if (!title.trim()) {
      Alert.alert('Missing title', 'Please give this page a title.');
      return;
    }
    setSaving(true);
    try {
      const updated = await legalApi.update(slug, {
        title: title.trim(),
        content_md: markdown,
      });
      setSavedAt(updated.updated_at);
      setPage(updated);
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || 'Unknown error');
    } finally {
      setSaving(false);
    }
  }, [slug, title, markdown]);

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <View style={styles.screen}>
      <View style={styles.topBar}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <ArrowLeft size={20} color={COLORS.text} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.crumb}>Admin / Legal Pages</Text>
          <Text style={styles.h1}>{SLUG_LABEL[slug]}</Text>
        </View>
        <View style={styles.modeSwitch}>
          <ModeBtn label="Edit" active={mode === 'edit'} icon={<Pencil size={14} color={mode === 'edit' ? '#fff' : COLORS.subtext} />} onPress={() => setMode('edit')} />
          <ModeBtn label="Preview" active={mode === 'preview'} icon={<Eye size={14} color={mode === 'preview' ? '#fff' : COLORS.subtext} />} onPress={() => setMode('preview')} />
        </View>
        <TouchableOpacity
          onPress={onSave}
          disabled={saving || loading}
          style={[styles.saveBtn, (saving || loading) && { opacity: 0.6 }]}
          testID="legal-save"
        >
          {saving ? <ActivityIndicator color="#fff" size="small" /> : <Save size={16} color="#fff" />}
          <Text style={styles.saveBtnText}>{saving ? 'Saving…' : 'Save'}</Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.loading}>
          <ActivityIndicator color={COLORS.primary} />
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.body}>
          {/* Title */}
          <Text style={styles.label}>Page title</Text>
          <TextInput
            value={title}
            onChangeText={setTitle}
            style={styles.titleInput}
            placeholder="e.g. Privacy Policy"
            placeholderTextColor={COLORS.subtext}
            testID="legal-title"
          />

          {/* Toolbar — only shown when in edit mode */}
          {mode === 'edit' ? (
            <View style={styles.toolbar}>
              <ToolBtn onPress={onH2} title="Heading 2"><Heading2 size={16} color={COLORS.text} /></ToolBtn>
              <ToolBtn onPress={onH3} title="Heading 3"><Heading3 size={16} color={COLORS.text} /></ToolBtn>
              <ToolBtn onPress={onH4} title="Heading 4"><Heading4 size={16} color={COLORS.text} /></ToolBtn>
              <Divider />
              <ToolBtn onPress={onBold} title="Bold"><Bold size={16} color={COLORS.text} /></ToolBtn>
              <ToolBtn onPress={onItalic} title="Italic"><Italic size={16} color={COLORS.text} /></ToolBtn>
              <ToolBtn onPress={onStrike} title="Strikethrough"><Strikethrough size={16} color={COLORS.text} /></ToolBtn>
              <ToolBtn onPress={onCode} title="Inline code"><CodeIcon size={16} color={COLORS.text} /></ToolBtn>
              <Divider />
              <ToolBtn onPress={onUL} title="Bulleted list"><ListIcon size={16} color={COLORS.text} /></ToolBtn>
              <ToolBtn onPress={onOL} title="Numbered list"><ListOrdered size={16} color={COLORS.text} /></ToolBtn>
              <ToolBtn onPress={onQuote} title="Quote"><Quote size={16} color={COLORS.text} /></ToolBtn>
              <Divider />
              <ToolBtn onPress={onLink} title="Link"><LinkIcon size={16} color={COLORS.text} /></ToolBtn>
              <ToolBtn onPress={onImage} title="Image" disabled={uploading}>
                {uploading ? <ActivityIndicator size="small" color={COLORS.primary} /> : <ImageIcon size={16} color={COLORS.text} />}
              </ToolBtn>
            </View>
          ) : null}

          {/* Edit OR Preview pane */}
          {mode === 'edit' ? (
            <TextInput
              ref={inputRef}
              value={markdown}
              onChangeText={setMarkdown}
              onSelectionChange={(e) => setSelection(e.nativeEvent.selection)}
              selection={selection}
              multiline
              textAlignVertical="top"
              style={styles.editor}
              placeholder={'Start typing…\n\nUse the toolbar above for formatting. Markdown shortcuts also work (# Heading, **bold**, - list).'}
              placeholderTextColor={COLORS.subtext}
              testID="legal-editor"
            />
          ) : (
            <View style={styles.previewWrap}>
              <Text style={styles.previewBadge}>Preview</Text>
              <LegalHtml html={previewHtml} />
            </View>
          )}

          {/* Footer status */}
          <View style={styles.footerRow}>
            {savedAt ? (
              <View style={styles.savedHint}>
                <CheckCircle2 size={14} color={COLORS.success} />
                <Text style={styles.savedHintText}>Last saved {new Date(savedAt).toLocaleString()}</Text>
              </View>
            ) : (
              <View style={styles.savedHint}>
                <AlertTriangle size={14} color={COLORS.warning} />
                <Text style={[styles.savedHintText, { color: COLORS.warning }]}>Default content — not yet customized</Text>
              </View>
            )}
            <Text style={styles.charCount}>{markdown.length.toLocaleString()} chars</Text>
          </View>
        </ScrollView>
      )}
    </View>
  );
}

// ── Small subcomponents ──────────────────────────────────────────────────
function ModeBtn({ label, icon, active, onPress }: { label: string; icon: React.ReactNode; active: boolean; onPress: () => void }) {
  return (
    <TouchableOpacity onPress={onPress} style={[styles.modeBtn, active && styles.modeBtnActive]}>
      {icon}
      <Text style={[styles.modeBtnText, active && { color: '#fff' }]}>{label}</Text>
    </TouchableOpacity>
  );
}

function ToolBtn({ onPress, title, children, disabled }: { onPress: () => void; title: string; children: React.ReactNode; disabled?: boolean }) {
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled}
      // @ts-ignore — web-only tooltip
      accessibilityLabel={title}
      style={[styles.toolBtn, disabled && { opacity: 0.5 }]}
    >
      {children}
    </TouchableOpacity>
  );
}

function Divider() {
  return <View style={styles.divider} />;
}

// ── Styles ───────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: COLORS.bg },
  topBar: {
    flexDirection: 'row', alignItems: 'center', gap: SPACING.sm,
    paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm,
    backgroundColor: COLORS.surface, borderBottomWidth: 1, borderBottomColor: COLORS.border,
  },
  iconBtn: { padding: 6, borderRadius: 999, backgroundColor: COLORS.bg },
  crumb: { color: COLORS.subtext, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 },
  h1: { color: COLORS.text, fontSize: FONT.sizes.lg, fontWeight: FONT.weights.heavy },
  modeSwitch: { flexDirection: 'row', backgroundColor: COLORS.bg, borderRadius: 999, padding: 4, gap: 2 },
  modeBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999 },
  modeBtnActive: { backgroundColor: COLORS.primary },
  modeBtnText: { color: COLORS.subtext, fontSize: 12, fontWeight: FONT.weights.semibold },
  saveBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    backgroundColor: COLORS.primary, paddingHorizontal: 14, paddingVertical: 9,
    borderRadius: RADIUS.md,
  },
  saveBtnText: { color: '#fff', fontWeight: FONT.weights.bold },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 40 },
  body: { padding: SPACING.md, paddingBottom: 80, gap: SPACING.sm },
  label: { fontSize: 11, fontWeight: FONT.weights.bold, color: COLORS.subtext, textTransform: 'uppercase', letterSpacing: 0.5 },
  titleInput: {
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    paddingHorizontal: 12, paddingVertical: 10, borderRadius: RADIUS.md,
    color: COLORS.text, fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold,
  },
  toolbar: {
    flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 4,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    padding: 6, borderRadius: RADIUS.md,
  },
  toolBtn: {
    minWidth: 32, minHeight: 32, alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: 6, borderRadius: RADIUS.sm,
  },
  divider: { width: 1, height: 20, backgroundColor: COLORS.border, marginHorizontal: 4 },
  editor: {
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: RADIUS.md, padding: 12, minHeight: 320,
    color: COLORS.text, fontSize: FONT.sizes.sm, lineHeight: 22,
    // Monospaced for the markdown editing pane so syntax aligns visually.
    fontFamily: Platform.select({ web: 'ui-monospace, Menlo, Consolas, monospace', default: undefined }),
  },
  previewWrap: {
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: RADIUS.md, padding: SPACING.md, minHeight: 320,
  },
  previewBadge: {
    alignSelf: 'flex-start', backgroundColor: COLORS.primaryLight, color: COLORS.primary,
    paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999,
    fontSize: 10, fontWeight: FONT.weights.bold, letterSpacing: 0.5,
    textTransform: 'uppercase', marginBottom: SPACING.sm,
  },
  footerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: SPACING.sm },
  savedHint: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  savedHintText: { color: COLORS.subtext, fontSize: 12 },
  charCount: { color: COLORS.subtext, fontSize: 11 },
});
