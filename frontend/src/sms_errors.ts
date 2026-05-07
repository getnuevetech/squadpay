/**
 * Phase H7.1 — Map raw SMS-provider errors (which we surface from the backend
 * as 502 details) into short, friendly messages for end-users.
 *
 * Backend currently returns details like:
 *   "Could not send verification SMS. signalwire=signalwire 422: {"errors":[{...,"code":"integration_test_verified_caller_required",...}]}"
 *
 * We pattern-match on the embedded error code or status to produce a clean
 * 2-line message. Falls back to a generic "Couldn't send SMS — try a different
 * number" for anything we don't recognize.
 */

export function friendlySmsError(raw: string | undefined | null): {
  title: string;
  message: string;
} {
  const s = (raw || '').toLowerCase();

  // SignalWire trial / Twilio trial: number not verified.
  if (
    s.includes('integration_test_verified_caller_required') ||
    s.includes('verified caller id') ||
    s.includes('trial campaign') ||
    (s.includes('unverified') && s.includes('twilio'))
  ) {
    return {
      title: 'Number not verified',
      message: 'Contact Support For Help',
    };
  }

  // Carrier blocked / invalid
  if (s.includes('21211') || s.includes('invalid') && s.includes('phone')) {
    return {
      title: 'Invalid phone number',
      message: 'Please double-check the number and try again. Use the format 555 123 4567.',
    };
  }
  if (s.includes('21610') || s.includes('blocked')) {
    return {
      title: 'Number blocked',
      message: 'This phone number has unsubscribed from messages. Try another number.',
    };
  }
  if (s.includes('21614') || s.includes('not a valid mobile')) {
    return {
      title: 'Landline detected',
      message: 'SMS can only be sent to mobile numbers. Please use a mobile phone.',
    };
  }

  // Auth / config failures
  if (s.includes('401') || s.includes('unauthorized') || s.includes('authentication')) {
    return {
      title: 'SMS service unavailable',
      message: 'We could not reach the SMS provider. Please try again in a moment.',
    };
  }

  // Rate limits
  if (s.includes('429') || s.includes('rate limit') || s.includes('too many')) {
    return {
      title: 'Too many requests',
      message: 'Please wait a minute before requesting another code.',
    };
  }

  // Network failures
  if (s.includes('exception') || s.includes('timeout') || s.includes('network')) {
    return {
      title: 'Network issue',
      message: 'We could not reach the SMS provider. Please try again.',
    };
  }

  // Default: short, friendly
  return {
    title: 'Could not send code',
    message:
      'We were unable to send a verification SMS to this number. ' +
      'Please double-check it and try again, or use a different number.',
  };
}
