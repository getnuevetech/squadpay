/**
 * QRScannerModal — cross-platform QR code scanner using expo-camera v55+.
 *
 * Mounts the device camera in a full-screen modal, decodes QR codes, and
 * calls `onScanned(data)` with the raw string payload.
 *
 * Web support: expo-camera v55 includes web fallback via the browser's
 * native BarcodeDetector / ZXing-WASM, so this works in the Expo web
 * preview too (with the user's permission to use their webcam).
 *
 * Usage:
 *   <QRScannerModal
 *     visible={scannerOpen}
 *     onClose={() => setScannerOpen(false)}
 *     onScanned={(payload) => { setCode(extractCode(payload)); setScannerOpen(false); }}
 *   />
 */
import React, { useState, useRef } from 'react';
import {
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
  ActivityIndicator,
  Platform,
} from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { X, Camera as CameraIcon } from 'lucide-react-native';
import { COLORS, FONT, RADIUS, SPACING } from './theme';

interface QRScannerModalProps {
  visible: boolean;
  onClose: () => void;
  onScanned: (data: string) => void;
  /** Label shown above the camera viewfinder. */
  prompt?: string;
}

export function QRScannerModal({
  visible,
  onClose,
  onScanned,
  prompt = 'Point your camera at the QR code',
}: QRScannerModalProps) {
  const [permission, requestPermission] = useCameraPermissions();
  // Guard against re-firing onScanned for the same QR while the modal closes.
  const scannedRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    if (visible) {
      scannedRef.current = false;
      setError(null);
      // Request permission lazily — first time the modal opens.
      if (permission && !permission.granted && permission.canAskAgain) {
        requestPermission().catch(() => undefined);
      }
    }
  }, [visible, permission, requestPermission]);

  const handleBarcode = (data: string) => {
    if (scannedRef.current) return;
    scannedRef.current = true;
    onScanned(data);
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      onRequestClose={onClose}
      presentationStyle="fullScreen"
    >
      <View style={styles.root}>
        {/* Close button */}
        <Pressable
          onPress={onClose}
          style={styles.closeBtn}
          hitSlop={10}
          testID="qr-scanner-close"
        >
          <X size={24} color="#fff" />
        </Pressable>

        {/* Prompt */}
        <Text style={styles.prompt}>{prompt}</Text>

        {/* Body */}
        <View style={styles.body}>
          {!permission ? (
            <View style={styles.permGate}>
              <ActivityIndicator color="#fff" />
              <Text style={styles.permText}>Checking camera permission…</Text>
            </View>
          ) : !permission.granted ? (
            <View style={styles.permGate}>
              <CameraIcon size={48} color="#fff" />
              <Text style={styles.permTitle}>Camera access needed</Text>
              <Text style={styles.permText}>
                SquadPay needs your camera to scan QR codes for joining a bill.
              </Text>
              <Pressable
                onPress={() => requestPermission()}
                style={styles.permBtn}
                testID="qr-scanner-grant"
              >
                <Text style={styles.permBtnText}>Grant camera access</Text>
              </Pressable>
            </View>
          ) : error ? (
            <View style={styles.permGate}>
              <Text style={styles.permText}>{error}</Text>
            </View>
          ) : (
            <CameraView
              style={StyleSheet.absoluteFill}
              facing="back"
              barcodeScannerSettings={{
                barcodeTypes: ['qr'],
              }}
              onBarcodeScanned={(r) => r?.data && handleBarcode(r.data)}
            />
          )}

          {/* Viewfinder overlay (visual only) */}
          {permission?.granted && !error && <View style={styles.viewfinder} pointerEvents="none" />}
        </View>

        <Text style={styles.hint}>
          {Platform.OS === 'web'
            ? 'Allow camera access in your browser when prompted.'
            : 'Hold steady — the code will scan automatically.'}
        </Text>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#000' },
  closeBtn: {
    position: 'absolute',
    top: Platform.OS === 'ios' ? 56 : 28,
    right: 18,
    zIndex: 10,
    width: 40, height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(0,0,0,0.55)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  prompt: {
    color: '#fff',
    fontSize: FONT.sizes.md,
    fontWeight: FONT.weights.bold,
    textAlign: 'center',
    paddingHorizontal: SPACING.lg,
    paddingTop: Platform.OS === 'ios' ? 60 : 36,
    paddingBottom: SPACING.md,
  },
  body: { flex: 1, position: 'relative' },
  viewfinder: {
    position: 'absolute',
    top: '20%',
    left: '12%',
    right: '12%',
    aspectRatio: 1,
    borderColor: '#fff',
    borderWidth: 3,
    borderRadius: 24,
  },
  hint: {
    color: '#cbd1ea',
    fontSize: FONT.sizes.xs,
    textAlign: 'center',
    paddingBottom: SPACING.lg,
    paddingHorizontal: SPACING.lg,
  },
  permGate: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 14,
    paddingHorizontal: SPACING.lg,
  },
  permTitle: { color: '#fff', fontSize: FONT.sizes.lg, fontWeight: FONT.weights.heavy },
  permText: { color: '#cbd1ea', textAlign: 'center', fontSize: FONT.sizes.sm, lineHeight: 20 },
  permBtn: { backgroundColor: COLORS.primary, paddingHorizontal: 22, paddingVertical: 12, borderRadius: RADIUS.md, marginTop: 8 },
  permBtnText: { color: '#fff', fontWeight: FONT.weights.bold },
});
