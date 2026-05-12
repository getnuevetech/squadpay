/**
 * Friendly error helpers.
 *
 * Why this exists: raw API/network/framework errors leak ugly strings into
 * toasts ("Network request failed", "[object Object]", stack traces, JSON
 * blobs, HTTP status codes, axios payloads). This helper sanitises them
 * into something a non-technical user can understand, and lets callers
 * supply a context-specific fallback when the underlying message is too
 * cryptic.
 *
 * Usage:
 *
 *   try {
 *     await api.scanReceipt(b64);
 *   } catch (e) {
 *     toast.error(friendlyError(e, 'We couldn\'t read that receipt. Try a clearer photo.'));
 *   }
 */

// Patterns that look like framework / dev / network plumbing rather than
// real user-facing copy. If `e.message` matches any of these, we drop it
// and use the caller's fallback instead.
const CODE_LIKE_PATTERNS: RegExp[] = [
  /^(\[object\s+\w+\])$/i,                          // [object Object]
  /^Network\s+request\s+failed$/i,                   // RN fetch
  /^Failed\s+to\s+fetch$/i,                          // browser fetch
  /^TypeError:/i,                                    // TypeError: ...
  /^SyntaxError:/i,                                  // JSON parse etc.
  /^ReferenceError:/i,
  /^AxiosError/i,
  /\bENETUNREACH\b|\bECONNREFUSED\b|\bETIMEDOUT\b/i, // node net errors
  /^\s*\{.*\}\s*$/s,                                 // raw JSON
  /^\s*<!?DOCTYPE\b/i,                               // HTML error page
  /\bstack:\s/i,                                     // stack traces
  /\bat\s+\w+\s*\(/i,                                // ... at Function (file.js:...)
  /^HTTP\s+\d{3}\b/i,                                // HTTP 500 ...
  /^\d{3}\s/,                                        // 400 Bad Request
  /^Internal\s+Server\s+Error/i,
  /^Bad\s+Gateway/i,
  /^Gateway\s+Time-?out/i,
  /^Service\s+Unavailable/i,
];

/** Pick the human-readable message out of an unknown error value, with a
 *  context-aware fallback. */
export function friendlyError(err: unknown, fallback: string): string {
  if (!err) return fallback;

  // Direct strings (some callers throw plain strings).
  if (typeof err === 'string') {
    return looksTechnical(err) ? fallback : softenCopy(err);
  }

  // Error objects / API rejections.
  const anyErr = err as any;
  const msg = (anyErr?.message || anyErr?.detail || anyErr?.error || '').toString();
  if (!msg) return fallback;
  if (looksTechnical(msg)) return fallback;
  return softenCopy(msg);
}

function looksTechnical(s: string): boolean {
  const trimmed = (s || '').trim();
  if (!trimmed) return true;
  // Very long messages usually contain a stack trace.
  if (trimmed.length > 240) return true;
  return CODE_LIKE_PATTERNS.some((rx) => rx.test(trimmed));
}

/** Tiny copy polish for messages that are kept (sentence case + period). */
function softenCopy(s: string): string {
  const t = s.trim();
  if (!t) return t;
  const cap = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?]$/.test(cap) ? cap : `${cap}.`;
}
