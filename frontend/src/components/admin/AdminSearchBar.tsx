/**
 * Admin global search bar (June 2025).
 *
 * Sits in the admin top header. Debounced (250ms), calls
 * GET /api/admin/search?q=, groups results by category, and on tap
 * navigates to the result href.
 */
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Search, X } from 'lucide-react-native';
import { adminApi } from '../../adminApi';
import { COLORS, FONT, RADIUS, SPACING } from '../../theme';

type Hit = {
  category: 'users' | 'squads' | 'admins' | 'audit' | 'tickets' | 'nav';
  label: string;
  sub: string;
  href: string;
  id: string;
};

const CATEGORY_LABEL: Record<Hit['category'], string> = {
  nav: 'Navigation',
  users: 'Users',
  squads: 'Squads',
  admins: 'Admin users',
  audit: 'Audit log',
  tickets: 'Customer Service',
};

export function AdminSearchBar({ navItems }: { navItems: { href: string; label: string }[] }) {
  const router = useRouter();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [serverHits, setServerHits] = useState<Hit[]>([]);
  const debounceRef = useRef<any>(null);

  useEffect(() => {
    if (!q.trim() || q.trim().length < 2) {
      setServerHits([]);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const r = await adminApi.search(q.trim());
        setServerHits(r.items as Hit[]);
      } catch {
        setServerHits([]);
      } finally {
        setLoading(false);
      }
    }, 250);
  }, [q]);

  // Local nav match (no network) — fuzzy contains.
  const navHits: Hit[] = (q.trim().length >= 1 ? navItems : []).filter(
    (n) => n.label.toLowerCase().includes(q.trim().toLowerCase()),
  ).slice(0, 5).map((n) => ({
    category: 'nav',
    label: n.label,
    sub: n.href,
    href: n.href,
    id: n.href,
  }));

  const allHits: Hit[] = [...navHits, ...serverHits];
  const grouped = allHits.reduce<Record<string, Hit[]>>((acc, h) => {
    (acc[h.category] = acc[h.category] || []).push(h);
    return acc;
  }, {});

  const go = (href: string) => {
    setOpen(false);
    setQ('');
    setServerHits([]);
    router.push(href as any);
  };

  return (
    <View style={styles.wrap}>
      <View style={styles.input}>
        <Search size={16} color={COLORS.subtext} />
        <TextInput
          testID="admin-search-input"
          value={q}
          onChangeText={setQ}
          onFocus={() => setOpen(true)}
          placeholder="Search users, squads, audit…"
          placeholderTextColor={COLORS.disabledText}
          style={styles.text}
          autoCorrect={false}
          autoCapitalize="none"
        />
        {q ? (
          <TouchableOpacity onPress={() => { setQ(''); setServerHits([]); }} activeOpacity={0.7}>
            <X size={14} color={COLORS.subtext} />
          </TouchableOpacity>
        ) : null}
      </View>

      {open && q.trim().length >= 1 ? (
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)}>
          <Pressable style={styles.results} onPress={() => {}}>
            {loading && allHits.length === 0 ? (
              <View style={{ padding: SPACING.md, alignItems: 'center' }}>
                <ActivityIndicator color={COLORS.primary} />
              </View>
            ) : allHits.length === 0 ? (
              <Text style={styles.empty}>No matches for “{q}”</Text>
            ) : (
              (Object.keys(grouped) as Hit['category'][]).map((cat) => (
                <View key={cat}>
                  <Text style={styles.groupHeader}>{CATEGORY_LABEL[cat]}</Text>
                  {grouped[cat].map((h) => (
                    <TouchableOpacity
                      key={`${cat}:${h.id}`}
                      onPress={() => go(h.href)}
                      activeOpacity={0.7}
                      style={styles.hit}
                      testID={`admin-search-hit-${cat}-${h.id}`}
                    >
                      <Text style={styles.hitLabel} numberOfLines={1}>{h.label}</Text>
                      <Text style={styles.hitSub} numberOfLines={1}>{h.sub}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              ))
            )}
          </Pressable>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, position: 'relative', zIndex: 100 },
  input: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingHorizontal: 12, paddingVertical: Platform.OS === 'ios' ? 8 : 6,
    borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
  },
  text: { flex: 1, fontSize: FONT.sizes.sm, color: COLORS.text, ...(Platform.OS === 'web' ? { outlineStyle: 'none' as any } : {}) },
  backdrop: {
    position: 'absolute', top: 40, left: 0, right: 0,
    height: Platform.OS === 'web' ? ('80vh' as any) : 800,
  },
  results: {
    backgroundColor: COLORS.surface, borderRadius: RADIUS.md,
    borderWidth: 1, borderColor: COLORS.border,
    paddingVertical: SPACING.xs,
    maxHeight: Platform.OS === 'web' ? ('70vh' as any) : 480,
    overflow: 'hidden' as any,
    shadowColor: '#000', shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.12, shadowRadius: 16, elevation: 8,
  },
  groupHeader: {
    paddingHorizontal: SPACING.md, paddingTop: 8, paddingBottom: 4,
    fontSize: 10, fontWeight: FONT.weights.bold, color: COLORS.subtext,
    textTransform: 'uppercase', letterSpacing: 0.8,
  },
  hit: { paddingHorizontal: SPACING.md, paddingVertical: 8 },
  hitLabel: { color: COLORS.text, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
  hitSub: { color: COLORS.subtext, fontSize: FONT.sizes.xs, marginTop: 2 },
  empty: { padding: SPACING.md, color: COLORS.subtext, fontSize: FONT.sizes.sm, textAlign: 'center' },
});
