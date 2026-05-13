import { useEffect, useState, useCallback } from 'react';
import { View, Text, TextInput, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator, Alert, Modal, Platform } from 'react-native';
import { Plus, Trash2, Pencil, FileText, Eye, EyeOff } from 'lucide-react-native';
import { cmsApi, CmsPage } from '../../src/adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../src/theme';
import { toast } from '../../src/components/Toast';

/**
 * Admin → CMS Pages
 *
 * Lets admins author public content pages (e.g. /about, /tos-summary,
 * /faq) with an editable URL slug. Pages are stored in db.cms_pages and
 * served at /api/cms/pages/{slug} for the public Expo route
 * /[cms_slug].tsx to render.
 */
export default function AdminCmsPages() {
  const [items, setItems] = useState<CmsPage[]>([]);
  const [busy, setBusy] = useState(true);
  const [editing, setEditing] = useState<Partial<CmsPage> | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await cmsApi.list();
      setItems(r.items);
    } catch (e: any) {
      Alert.alert('Error', e?.message || 'Failed to load CMS pages');
    } finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const onNew = () => setEditing({ title: '', slug: '', body: '', body_format: 'markdown', published: true, visibility: 'both' });
  const onEdit = async (id: string) => {
    try {
      const full = await cmsApi.get(id);
      setEditing(full);
    } catch (e: any) { Alert.alert('Error', e?.message || 'Failed to load page'); }
  };
  const onDelete = async (p: CmsPage) => {
    if (Platform.OS !== 'web') {
      // Native: avoid deeplinked confirm flows. Use Alert.
      Alert.alert('Delete page?', `"${p.title}" will be permanently removed.`, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: async () => {
          try { await cmsApi.remove(p.id); toast.success('Deleted'); load(); }
          catch (e: any) { Alert.alert('Error', e?.message || 'Failed to delete'); }
        }},
      ]);
      return;
    }
    if (!confirm(`Delete "${p.title}"? This is permanent.`)) return;
    try { await cmsApi.remove(p.id); toast.success('Deleted'); load(); }
    catch (e: any) { Alert.alert('Error', e?.message || 'Failed to delete'); }
  };

  const save = async () => {
    if (!editing) return;
    if (!editing.title?.trim() || !editing.body?.trim()) {
      Alert.alert('Missing fields', 'Title and body are required.');
      return;
    }
    try {
      if (editing.id) {
        await cmsApi.update(editing.id, editing);
        toast.success('Page saved');
      } else {
        await cmsApi.create(editing);
        toast.success('Page created');
      }
      setEditing(null);
      load();
    } catch (e: any) {
      Alert.alert('Save failed', e?.message || 'Could not save');
    }
  };

  if (busy) return <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>;

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 80 }}>
      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.heading} testID="cms-heading">CMS Pages</Text>
          <Text style={styles.subheading}>Create content pages with custom URL slugs. Pages with visibility="both" or "web" render at /{`{slug}`} on the public web.</Text>
        </View>
        <TouchableOpacity onPress={onNew} style={styles.newBtn} testID="cms-new">
          <Plus size={14} color="#fff" />
          <Text style={styles.newBtnText}>New page</Text>
        </TouchableOpacity>
      </View>

      {items.length === 0 ? <Text style={styles.empty}>No pages yet. Click "New page" to add one.</Text> : null}
      <View style={styles.tableWrap}>
        <View style={[styles.tableRow, styles.tableHeaderRow]}>
          <Text style={[styles.th, { flex: 2 }]}>Title</Text>
          <Text style={[styles.th, { flex: 2 }]}>Slug</Text>
          <Text style={[styles.th, { flex: 1 }]}>Visibility</Text>
          <Text style={[styles.th, { flex: 1 }]}>Status</Text>
          <Text style={[styles.th, { flex: 1.5 }]}>Updated</Text>
          <Text style={[styles.th, { flex: 1 }]}>Actions</Text>
        </View>
        {items.map((p, idx) => (
          <View key={p.id} style={[styles.tableRow, idx % 2 === 0 ? styles.rowEven : styles.rowOdd]} testID={`cms-row-${p.id}`}>
            <View style={{ flex: 2, flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <FileText size={14} color={COLORS.subtext} />
              <Text style={[styles.td, styles.strong]} numberOfLines={1}>{p.title}</Text>
            </View>
            <Text style={[styles.td, styles.mono, { flex: 2 }]} numberOfLines={1}>/{p.slug}</Text>
            <Text style={[styles.td, { flex: 1 }]}>{p.visibility}</Text>
            <View style={{ flex: 1 }}>
              {p.published
                ? <View style={[styles.pill, { backgroundColor: COLORS.successLight }]}><Eye size={11} color={COLORS.success} /><Text style={[styles.pillText, { color: COLORS.success }]}>Published</Text></View>
                : <View style={[styles.pill, { backgroundColor: COLORS.bg }]}><EyeOff size={11} color={COLORS.subtext} /><Text style={[styles.pillText, { color: COLORS.subtext }]}>Draft</Text></View>}
            </View>
            <Text style={[styles.td, { flex: 1.5, fontSize: 11 }]}>{new Date(p.updated_at).toLocaleString()}</Text>
            <View style={{ flex: 1, flexDirection: 'row', gap: 6 }}>
              <TouchableOpacity onPress={() => onEdit(p.id)} style={styles.rowBtn}><Pencil size={12} color={COLORS.primary} /></TouchableOpacity>
              <TouchableOpacity onPress={() => onDelete(p)} style={[styles.rowBtn, { borderColor: COLORS.dangerLight }]}><Trash2 size={12} color={COLORS.danger} /></TouchableOpacity>
            </View>
          </View>
        ))}
      </View>

      {/* Editor modal */}
      <Modal visible={!!editing} animationType="slide" transparent onRequestClose={() => setEditing(null)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalHeading}>{editing?.id ? 'Edit page' : 'New page'}</Text>
            <ScrollView style={{ maxHeight: 520 }} contentContainerStyle={{ gap: 10 }}>
              <View>
                <Text style={styles.fieldLabel}>Title</Text>
                <TextInput style={styles.input} value={editing?.title || ''} onChangeText={(v) => setEditing({ ...editing!, title: v })} placeholder="About SquadPay" placeholderTextColor={COLORS.disabledText} testID="cms-edit-title" />
              </View>
              <View>
                <Text style={styles.fieldLabel}>Slug (URL)</Text>
                <TextInput style={styles.input} value={editing?.slug || ''} onChangeText={(v) => setEditing({ ...editing!, slug: v.toLowerCase() })} autoCapitalize="none" placeholder="about-us" placeholderTextColor={COLORS.disabledText} testID="cms-edit-slug" />
                <Text style={styles.hint}>URL will be /{editing?.slug || '<slug>'}. Auto-generated from title if left blank.</Text>
              </View>
              <View>
                <Text style={styles.fieldLabel}>Visibility</Text>
                <View style={styles.chipsRow}>
                  {(['both', 'web', 'mobile'] as const).map((v) => (
                    <TouchableOpacity key={v} onPress={() => setEditing({ ...editing!, visibility: v })} style={[styles.chip, editing?.visibility === v && styles.chipActive]}>
                      <Text style={[styles.chipText, editing?.visibility === v && styles.chipTextActive]}>{v}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </View>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <TouchableOpacity onPress={() => setEditing({ ...editing!, published: !editing?.published })} style={[styles.toggle, editing?.published && styles.toggleOn]}>
                  <View style={[styles.toggleKnob, editing?.published && styles.toggleKnobOn]} />
                </TouchableOpacity>
                <Text style={styles.fieldLabel}>{editing?.published ? 'Published' : 'Draft (hidden from public)'}</Text>
              </View>
              <View>
                <Text style={styles.fieldLabel}>Body (Markdown)</Text>
                <TextInput style={[styles.input, { height: 220, textAlignVertical: 'top' }]} multiline value={editing?.body || ''} onChangeText={(v) => setEditing({ ...editing!, body: v })} placeholder="# Hello SquadPay\n\nWrite your content here..." placeholderTextColor={COLORS.disabledText} testID="cms-edit-body" />
              </View>
              <View>
                <Text style={styles.fieldLabel}>Meta description (SEO)</Text>
                <TextInput style={styles.input} value={editing?.meta_description || ''} onChangeText={(v) => setEditing({ ...editing!, meta_description: v })} placeholder="Short summary shown in search results" placeholderTextColor={COLORS.disabledText} />
              </View>
            </ScrollView>
            <View style={styles.modalActions}>
              <TouchableOpacity onPress={() => setEditing(null)} style={styles.cancelBtn}><Text style={styles.cancelBtnText}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity onPress={save} style={styles.saveBtn} testID="cms-save"><Text style={styles.saveBtnText}>Save</Text></TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading: { fontSize: FONT.sizes.xl, fontWeight: FONT.weights.bold, color: COLORS.text },
  subheading: { fontSize: FONT.sizes.sm, color: COLORS.subtext, marginTop: 2, maxWidth: 720 },
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: SPACING.md, gap: SPACING.sm },
  newBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, height: 36, borderRadius: RADIUS.md, backgroundColor: COLORS.primary },
  newBtnText: { color: '#fff', fontWeight: FONT.weights.bold, fontSize: FONT.sizes.xs },
  empty: { fontSize: FONT.sizes.sm, color: COLORS.subtext, fontStyle: 'italic', marginTop: 24 },
  tableWrap: { backgroundColor: COLORS.surface, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, overflow: 'hidden' },
  tableRow: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: SPACING.sm, paddingVertical: 10, gap: 6, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  tableHeaderRow: { backgroundColor: COLORS.bg, borderBottomWidth: 2 },
  rowEven: { backgroundColor: COLORS.surface },
  rowOdd: { backgroundColor: COLORS.bg },
  th: { fontSize: 11, color: COLORS.subtext, fontWeight: FONT.weights.bold, textTransform: 'uppercase', letterSpacing: 0.4 },
  td: { fontSize: FONT.sizes.sm, color: COLORS.text },
  strong: { fontWeight: FONT.weights.semibold },
  mono: { fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }), color: COLORS.subtext },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, height: 22, borderRadius: RADIUS.pill, alignSelf: 'flex-start' },
  pillText: { fontSize: 11, fontWeight: FONT.weights.bold },
  rowBtn: { width: 28, height: 28, borderRadius: RADIUS.md, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.border },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', alignItems: 'center', justifyContent: 'center', padding: SPACING.md },
  modalCard: { width: '100%', maxWidth: 760, backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, padding: SPACING.lg, gap: SPACING.md },
  modalHeading: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  fieldLabel: { fontSize: 10, color: COLORS.subtext, textTransform: 'uppercase', fontWeight: FONT.weights.bold, letterSpacing: 0.4, marginBottom: 4 },
  input: { borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.md, paddingVertical: 8, color: COLORS.text, backgroundColor: COLORS.bg, fontSize: FONT.sizes.sm, minHeight: 38 },
  hint: { fontSize: 11, color: COLORS.subtext, marginTop: 4, fontStyle: 'italic' },
  chipsRow: { flexDirection: 'row', gap: 6 },
  chip: { paddingHorizontal: 10, height: 30, borderRadius: RADIUS.pill, borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.bg, alignItems: 'center', justifyContent: 'center' },
  chipActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { fontSize: FONT.sizes.xs, color: COLORS.text, fontWeight: FONT.weights.medium },
  chipTextActive: { color: '#fff' },
  toggle: { width: 42, height: 24, borderRadius: 12, backgroundColor: COLORS.border, padding: 2 },
  toggleOn: { backgroundColor: COLORS.primary },
  toggleKnob: { width: 20, height: 20, borderRadius: 10, backgroundColor: '#fff' },
  toggleKnobOn: { marginLeft: 'auto' },
  modalActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: SPACING.sm, marginTop: SPACING.sm },
  cancelBtn: { paddingHorizontal: SPACING.md, height: 38, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, alignItems: 'center', justifyContent: 'center' },
  cancelBtnText: { color: COLORS.subtext, fontWeight: FONT.weights.semibold },
  saveBtn: { paddingHorizontal: SPACING.lg, height: 38, borderRadius: RADIUS.md, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  saveBtnText: { color: '#fff', fontWeight: FONT.weights.bold },
});
