/**
 * PhoneInput — strict US mobile phone input.
 *
 * Behaviour:
 *   • Uses `keyboardType="phone-pad"` (or `numeric` on web fallback).
 *   • Auto-formats with libphonenumber-js's `AsYouType('US')` formatter
 *     → user types `5551234567`, sees `(555) 123-4567`.
 *   • Hard-rejects any non-digit characters and any input beyond 10 digits
 *     (or 11 if the leading char is "1" — the US country code).
 *   • Exposes the *digits-only* E.164-ish string via `onChangeText` so the
 *     parent never has to strip formatting.
 *   • Validates US-mobile syntax via libphonenumber-js's `parsePhoneNumberFromString`
 *     and surfaces a per-field error when the user blurs.
 *
 * Usage:
 *   const [phone, setPhone] = useState('');
 *   const [phoneValid, setPhoneValid] = useState(false);
 *   <PhoneInput
 *     value={phone}                         // 10-digit raw e.g. "5551234567"
 *     onChangeText={setPhone}
 *     onValidChange={setPhoneValid}
 *     testID="auth-phone-input"
 *   />
 *
 * Server contract:
 *   The backend `phone` field continues to accept the raw 10-digit US
 *   number OR a +1-prefixed E.164. We strip formatting on send.
 */
import { forwardRef, useCallback, useEffect, useMemo, useState } from 'react';
import { Platform, StyleSheet, Text, TextInput, View } from 'react-native';
import { AsYouType, parsePhoneNumberFromString } from 'libphonenumber-js';
import { COLORS, FONT, RADIUS, SPACING } from '../theme';

type Props = {
  /** 10-digit raw value (or empty). The parent owns this state. */
  value: string;
  /** Callback fired with the digit-only string (e.g. "5551234567"). */
  onChangeText: (digits: string) => void;
  /** Fires whenever validity changes (validates US-mobile syntax). */
  onValidChange?: (isValid: boolean) => void;
  /** Optional placeholder; defaults to "(555) 123-4567". */
  placeholder?: string;
  /** Show inline validation error when the user blurs an invalid value. */
  showInlineError?: boolean;
  /** Render in error state from an external source (e.g. server rejection). */
  externalError?: string | null;
  autoFocus?: boolean;
  testID?: string;
  /** Called when the user hits "Next" / "Done" on the soft keyboard. */
  onSubmitEditing?: () => void;
  /** Override the input style (merges with internal styles). */
  style?: any;
};

const MAX_DIGITS = 11; // 10-digit US OR 11 with leading "1"

/** Returns digits-only, sanitised so a leading "1" is preserved as a country
 *  prefix but no other non-digit chars survive. */
function stripToDigits(input: string): string {
  return (input || '').replace(/\D/g, '').slice(0, MAX_DIGITS);
}

/** Returns the user-facing formatted string for display, e.g. "(555) 123-…". */
function formatForDisplay(digits: string): string {
  if (!digits) return '';
  const typer = new AsYouType('US');
  return typer.input(digits);
}

/** Validates the digit string as a US mobile / fixed-line number. */
export function isValidUSPhone(digits: string): boolean {
  if (!digits) return false;
  // libphonenumber needs +1 prefix for E.164 parsing.
  const e164 = digits.length === 10 ? `+1${digits}` : `+${digits}`;
  const parsed = parsePhoneNumberFromString(e164, 'US');
  if (!parsed) return false;
  if (parsed.country !== 'US') return false;
  return parsed.isValid();
}

/** Returns the E.164 representation (+15551234567) for a valid digit string,
 *  or empty when invalid. Useful for sending to the server. */
export function toE164(digits: string): string {
  if (!isValidUSPhone(digits)) return '';
  const e164 = digits.length === 10 ? `+1${digits}` : `+${digits}`;
  const parsed = parsePhoneNumberFromString(e164, 'US');
  return parsed?.number || '';
}

export const PhoneInput = forwardRef<TextInput, Props>(function PhoneInput(
  {
    value,
    onChangeText,
    onValidChange,
    placeholder = '(555) 123-4567',
    showInlineError = true,
    externalError = null,
    autoFocus = false,
    testID,
    onSubmitEditing,
    style,
  },
  ref,
) {
  const [blurred, setBlurred] = useState(false);
  const [internalDisplay, setInternalDisplay] = useState(() => formatForDisplay(value || ''));

  // Whenever the parent updates `value` externally, refresh the display.
  useEffect(() => {
    setInternalDisplay(formatForDisplay(value || ''));
  }, [value]);

  const valid = useMemo(() => isValidUSPhone(value), [value]);

  // Notify parent of validity changes — fire-and-forget side effect.
  useEffect(() => {
    if (onValidChange) onValidChange(valid);
  }, [valid, onValidChange]);

  const handleChange = useCallback(
    (raw: string) => {
      const digits = stripToDigits(raw);
      setInternalDisplay(formatForDisplay(digits));
      onChangeText(digits);
    },
    [onChangeText],
  );

  const showError =
    externalError ||
    (blurred && showInlineError && value.length > 0 && !valid
      ? 'Enter a valid US mobile number'
      : null);

  return (
    <View>
      <TextInput
        ref={ref}
        testID={testID}
        value={internalDisplay}
        onChangeText={handleChange}
        placeholder={placeholder}
        placeholderTextColor={COLORS.disabledText}
        // Strict mobile keyboard everywhere — no alpha access.
        keyboardType={Platform.OS === 'web' ? 'numeric' : 'phone-pad'}
        // Help iOS auto-fill propose the user's own number.
        textContentType="telephoneNumber"
        autoComplete="tel"
        autoCorrect={false}
        autoCapitalize="none"
        inputMode={Platform.OS === 'web' ? 'tel' : undefined}
        maxLength={20} // formatted display can be slightly longer than digits
        autoFocus={autoFocus}
        returnKeyType="next"
        onSubmitEditing={onSubmitEditing}
        onBlur={() => setBlurred(true)}
        style={[styles.input, showError ? styles.inputError : null, style]}
      />
      {showError ? (
        <Text style={styles.errorText} testID={testID ? `${testID}-error` : undefined}>
          {showError}
        </Text>
      ) : null}
    </View>
  );
});

PhoneInput.displayName = 'PhoneInput';
export default PhoneInput;

const styles = StyleSheet.create({
  input: {
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.md,
    paddingVertical: Platform.OS === 'ios' ? 14 : 10,
    fontSize: FONT.body,
    color: COLORS.text,
    backgroundColor: COLORS.surface,
  },
  inputError: { borderColor: COLORS.danger },
  errorText: { color: COLORS.danger, fontSize: FONT.small, marginTop: 6 },
});
