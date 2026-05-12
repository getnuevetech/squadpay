/**
 * User inbox / Notifications screen (June 2025).
 *
 * Surfaces admin broadcasts delivered to the in-app channel. Tappable
 * card with optional image preview and "Open link" CTA. Each message is
 * automatically marked as read once it appears on screen.
 */
import { useCallback, useEffect, useState } from 'react';
import * as Linking from 'expo-linking';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Linking as RNLinking,
  Platform,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { ArrowLeft, Inbox, ExternalLink } from 'lucide-react-native';
import { api } from '../src/api';
import { loadUser } from '../src/session';
import { COLORS, FONT, RADIUS, SPACING } from '../src/theme';
import { friendlyError } from '../src/errors';
import { toast } from '../src/components/Toast';

type InboxItem = {
  id: string;
  broadcast_id: string;
  message: string;
  image_url: string | null;
  link_url: string | null;
  read_at: string | null;
  created_at: string;
};

export default function NotificationsScreen() {
  const router = useRouter();
  const [userId, setUserId] = useState<string | null>(null);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const u = await loadUser();
    if (!u) {
      router.replace('/auth');
      return;
    }
    setUserId(u.id);
    try {
      const r = await api.getInbox(u.id);
      setItems(r.items || []);
      // Auto-mark-all-read on view so the bell badge clears.
      if ((r.unread || 0) > 0) {
        try { await api.markAllInboxRead(u.id); } catch {}
      }
    } catch (e: any) {
      toast.error(friendlyError(e, "We couldn't load your notifications."));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const openLink = async (url?: string | null) => {
    if (!url) return;
    try {
      const can = await RNLinking.canOpenURL(url);
      if (!can) throw new Error('cannot-open');
      await RNLinking.openURL(url);
    } catch {
      toast.error("We couldn't open that link.");
    }
  };

  return (
    <SafeAreaView edges={['top', 'bottom']} style={{ flex: 1, backgroundColor: COLORS.bg }}>
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.canGoBack() ? router.back() : router.replace('/')}
          style={styles.backBtn}
          activeOpacity={0.7}
          testID="notifications-back-btn"
        >
          <ArrowLeft size={20} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Notifications</Text>
        <View style={{ width: 40 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={COLORS.primary} /></View>
      ) : items.length === 0 ? (
        <View style={styles.empty}>
          <Inbox size={48} color={COLORS.border} />
          <Text style={styles.emptyTitle}>No notifications yet</Text>
          <Text style={styles.emptySub}>
            When SquadPay sends you an update, it'll show up here.
          </Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(it) => it.id}
          contentContainerStyle={{ padding: SPACING.md, gap: SPACING.sm }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />
          }
          renderItem={({ item }) => (
            <View style={styles.card} testID={`notification-${item.id}`}>
              {item.image_url ? (
                <Image
                  source={{ uri: item.image_url }}
                  style={styles.cardImage}
                  resizeMode="cover"
                />
              ) : null}
              <View style={{ padding: SPACING.md, gap: 6 }}>
                <Text style={styles.cardMsg}>{item.message}</Text>
                <Text style={styles.cardDate}>
                  {new Date(item.created_at).toLocaleString()}
                </Text>
                {item.link_url ? (
                  <TouchableOpacity
                    onPress={() => openLink(item.link_url)}
                    style={styles.linkBtn}
                    activeOpacity={0.85}
                    testID={`notification-link-${item.id}`}
                  >
                    <ExternalLink size={14} color={COLORS.primary} />
                    <Text style={styles.linkText}>Open link</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            </View>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
    backgroundColor: COLORS.surface,
  },
  backBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: COLORS.bg,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  title: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.lg, gap: SPACING.sm },
  emptyTitle: { fontSize: FONT.sizes.lg, fontWeight: FONT.weights.bold, color: COLORS.text },
  emptySub: { color: COLORS.subtext, fontSize: FONT.sizes.sm, textAlign: 'center' },
  card: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    overflow: 'hidden',
  },
  cardImage: { width: '100%', height: 160, backgroundColor: COLORS.bg },
  cardMsg: { color: COLORS.text, fontSize: FONT.sizes.md, lineHeight: 22 },
  cardDate: { color: COLORS.subtext, fontSize: FONT.sizes.xs },
  linkBtn: {
    marginTop: 6,
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: RADIUS.pill,
    backgroundColor: COLORS.primaryLight,
  },
  linkText: { color: COLORS.primary, fontWeight: FONT.weights.semibold, fontSize: FONT.sizes.sm },
});
