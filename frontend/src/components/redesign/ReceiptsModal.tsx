/**
 * ReceiptsModal — full-screen lightbox for a squad's stored receipts.
 *
 * Lists every receipt attached to the group via
 * `GET /api/groups/{group_id}/receipts`, lazy-loads the actual JPEG bytes
 * per-tile via `GET /api/receipts/{id}`, and supports tap-to-zoom into a
 * single full-bleed image. Used by:
 *   • Lead/member dashboard (squad detail screen) — "View Receipts" CTA
 *   • Admin group inspector (future) — same component, reused
 *
 * UX notes:
 *   - Empty state: shows a friendly "No receipt yet" message with an
 *     inline ScanLine icon — never a blank black screen.
 *   - Lazy load: tiles ask for their image only when first rendered, so
 *     opening a group with 5 receipts doesn't fetch 5 × 300KB upfront.
 *   - Fullscreen mode dismisses on tap (mobile convention).
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { X, ScanLine, ImageOff } from 'lucide-react-native';
import { api } from '../../api';
import { COLORS, FONT, RADIUS, SPACING } from '../../theme';

type ReceiptListEntry = {
  receipt_id: string;
  mime: string;
  stored_size?: number;
  created_at: string;
  expires_at?: string;
};

type Props = {
  visible: boolean;
  groupId: string;
  onClose: () => void;
};

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

/** Single tile that lazy-loads its receipt image on first mount. */
function ReceiptTile({
  receipt,
  onPress,
}: {
  receipt: ReceiptListEntry;
  onPress: (src: string) => void;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .getReceiptImage(receipt.receipt_id)
      .then((res) => {
        if (!alive) return;
        if (res.image_base64) {
          setSrc(`data:${res.mime || 'image/jpeg'};base64,${res.image_base64}`);
        } else {
          setFailed(true);
        }
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [receipt.receipt_id]);

  const dateLabel = useMemo(() => {
    try {
      const d = new Date(receipt.created_at);
      return d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
    } catch {
      return '';
    }
  }, [receipt.created_at]);

  return (
    <TouchableOpacity
      style={styles.tile}
      activeOpacity={0.85}
      onPress={() => src && onPress(src)}
      disabled={!src}
      testID={`receipt-tile-${receipt.receipt_id}`}
    >
      {src ? (
        <Image source={{ uri: src }} style={styles.tileImage} resizeMode="cover" />
      ) : failed ? (
        <View style={styles.tilePlaceholder}>
          <ImageOff size={24} color={COLORS.subtext} />
          <Text style={styles.tilePlaceholderText}>Unavailable</Text>
        </View>
      ) : (
        <View style={styles.tilePlaceholder}>
          <ActivityIndicator color={COLORS.primary} />
        </View>
      )}
      <Text style={styles.tileLabel} numberOfLines={1}>
        {dateLabel}
      </Text>
    </TouchableOpacity>
  );
}

export function ReceiptsModal({ visible, groupId, onClose }: Props) {
  const [loading, setLoading] = useState(true);
  const [receipts, setReceipts] = useState<ReceiptListEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [fullscreenSrc, setFullscreenSrc] = useState<string | null>(null);

  useEffect(() => {
    if (!visible || !groupId) return;
    let alive = true;
    setLoading(true);
    setError(null);
    api
      .listGroupReceipts(groupId)
      .then((res) => {
        if (!alive) return;
        const items = Array.isArray(res?.items) ? res.items : [];
        // Newest first — backend stores in append-order so we reverse.
        setReceipts([...items].reverse());
      })
      .catch((e: any) => {
        if (alive) setError(e?.message || 'Could not load receipts');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [visible, groupId]);

  return (
    <Modal
      visible={visible}
      animationType="slide"
      onRequestClose={onClose}
      transparent={false}
    >
      <View style={styles.root}>
        <View style={styles.header}>
          <Text style={styles.title}>Receipts</Text>
          <TouchableOpacity
            onPress={onClose}
            style={styles.closeBtn}
            testID="receipts-modal-close"
            hitSlop={{ top: 12, right: 12, bottom: 12, left: 12 }}
          >
            <X size={22} color={COLORS.text} />
          </TouchableOpacity>
        </View>

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator color={COLORS.primary} />
          </View>
        ) : error ? (
          <View style={styles.center}>
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : receipts.length === 0 ? (
          <View style={styles.center}>
            <ScanLine size={42} color={COLORS.subtext} />
            <Text style={styles.emptyTitle}>No receipt yet</Text>
            <Text style={styles.emptySub}>
              Scanned receipts attach automatically. They're kept for 90 days.
            </Text>
          </View>
        ) : (
          <ScrollView contentContainerStyle={styles.grid}>
            {receipts.map((rcpt) => (
              <ReceiptTile key={rcpt.receipt_id} receipt={rcpt} onPress={setFullscreenSrc} />
            ))}
          </ScrollView>
        )}
      </View>

      {/* Tap-anywhere-to-dismiss fullscreen lightbox. */}
      <Modal
        visible={!!fullscreenSrc}
        transparent
        animationType="fade"
        onRequestClose={() => setFullscreenSrc(null)}
      >
        <Pressable
          style={styles.lightboxBackdrop}
          onPress={() => setFullscreenSrc(null)}
          testID="receipts-lightbox-backdrop"
        >
          {fullscreenSrc && (
            <Image
              source={{ uri: fullscreenSrc }}
              style={styles.lightboxImage}
              resizeMode="contain"
            />
          )}
        </Pressable>
      </Modal>
    </Modal>
  );
}

const TILE_WIDTH = 150;

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.surface },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.md,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
  },
  title: {
    fontSize: FONT.sizes.lg,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
  },
  closeBtn: { padding: 4 },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: SPACING.md,
    padding: SPACING.md,
  },
  tile: { width: TILE_WIDTH, alignItems: 'center' },
  tileImage: {
    width: TILE_WIDTH,
    height: TILE_WIDTH * 1.3,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.bg,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  tilePlaceholder: {
    width: TILE_WIDTH,
    height: TILE_WIDTH * 1.3,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.bg,
    borderWidth: 1,
    borderColor: COLORS.border,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  tilePlaceholderText: { fontSize: 11, color: COLORS.subtext },
  tileLabel: {
    marginTop: 6,
    fontSize: FONT.sizes.xs,
    color: COLORS.subtext,
    maxWidth: TILE_WIDTH,
  },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACING.lg, gap: SPACING.sm },
  emptyTitle: { fontSize: FONT.sizes.md, fontWeight: FONT.weights.semibold, color: COLORS.text, marginTop: 8 },
  emptySub: { fontSize: FONT.sizes.sm, color: COLORS.subtext, textAlign: 'center', maxWidth: 280 },
  errorText: { color: COLORS.danger, fontSize: FONT.sizes.sm, textAlign: 'center' },
  lightboxBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.96)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  lightboxImage: { width: '100%', height: '100%' },
});
