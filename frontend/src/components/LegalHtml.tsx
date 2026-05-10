/**
 * LegalHtml — render admin-authored HTML safely on web + native.
 *
 * Web: uses `dangerouslySetInnerHTML` after sanitizing with a small allowlist
 *      (no <script>, no `on*` event handlers, no javascript: URLs).
 *
 * Native (iOS / Android Expo Go / EAS): uses a lightweight HTML→RN mapper for
 *      the limited tag set we expose in the admin editor (h2/h3/h4, p, ul/ol/li,
 *      strong/em/a, img, video, br, hr). Heavy 3rd-party libs avoided to keep
 *      the bundle small.
 *
 * The mapper is intentionally conservative — anything not recognized is shown
 * as plain text. This is safe to embed inside ScrollViews on legal screens.
 */
import React, { useMemo } from 'react';
import { Platform, Text, View, StyleSheet, Image, Linking } from 'react-native';
import { COLORS, FONT, SPACING } from '../theme';

const BACKEND_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

// ───────────────────────── Sanitization ─────────────────────────

/**
 * Strip dangerous tags/attributes from arbitrary admin-supplied HTML.
 * We keep this minimal & explicit (no DOMPurify dep) since the editor only
 * emits a known whitelist of tags.
 */
function sanitizeHtml(raw: string): string {
  if (!raw) return '';
  let s = raw;
  // Remove <script>...</script> and <style>...</style>.
  s = s.replace(/<script[\s\S]*?<\/script>/gi, '');
  s = s.replace(/<style[\s\S]*?<\/style>/gi, '');
  // Strip on* event handlers (onclick=, onload=, ...).
  s = s.replace(/\s+on\w+\s*=\s*"[^"]*"/gi, '');
  s = s.replace(/\s+on\w+\s*=\s*'[^']*'/gi, '');
  // Block javascript: and data:text/html URLs in href/src.
  s = s.replace(/(href|src)\s*=\s*"javascript:[^"]*"/gi, '$1="#"');
  s = s.replace(/(href|src)\s*=\s*'javascript:[^']*'/gi, "$1='#'");
  s = s.replace(/(href|src)\s*=\s*"data:text\/html[^"]*"/gi, '$1="#"');
  return s;
}

/** Resolve a possibly-relative media URL to an absolute one (native needs full URLs). */
function absolutize(url: string): string {
  if (!url) return url;
  if (/^(https?:|data:|file:)/i.test(url)) return url;
  if (url.startsWith('/api/')) {
    const base = BACKEND_BASE.replace(/\/$/, '');
    return base + url;
  }
  return url;
}

// ───────────────────────── Native renderer ─────────────────────────

type Node =
  | { type: 'text'; text: string }
  | { type: 'tag'; name: string; attrs: Record<string, string>; children: Node[] };

function parseHtml(html: string): Node[] {
  // Very small, regex-based HTML parser. Handles nested tags well enough for
  // the tag whitelist used by the legal editor. NOT a general-purpose parser.
  const out: Node[] = [];
  let i = 0;
  const stack: Node[][] = [out];
  const tagStack: string[] = [];

  while (i < html.length) {
    if (html[i] === '<') {
      const end = html.indexOf('>', i);
      if (end < 0) break;
      const raw = html.slice(i + 1, end).trim();
      i = end + 1;

      if (raw.startsWith('!--')) continue; // comment
      if (raw.startsWith('/')) {
        const closeName = raw.slice(1).toLowerCase().split(/\s/)[0];
        // Pop until we close the matching tag (tolerant of unbalanced HTML).
        while (tagStack.length && tagStack[tagStack.length - 1] !== closeName) {
          tagStack.pop();
          stack.pop();
        }
        if (tagStack.length) {
          tagStack.pop();
          stack.pop();
        }
        continue;
      }

      const selfClose = raw.endsWith('/');
      const cleaned = selfClose ? raw.slice(0, -1).trim() : raw;
      const m = cleaned.match(/^([a-zA-Z0-9]+)([\s\S]*)$/);
      if (!m) continue;
      const name = m[1].toLowerCase();
      const attrs: Record<string, string> = {};
      const attrRe = /([a-zA-Z_:][\w:-]*)\s*=\s*"([^"]*)"|([a-zA-Z_:][\w:-]*)\s*=\s*'([^']*)'/g;
      let am: RegExpExecArray | null;
      while ((am = attrRe.exec(m[2])) !== null) {
        const k = (am[1] || am[3]).toLowerCase();
        attrs[k] = am[2] || am[4];
      }
      const node: Node = { type: 'tag', name, attrs, children: [] };
      stack[stack.length - 1].push(node);
      const voids = new Set(['br', 'hr', 'img', 'meta', 'link', 'input']);
      if (!selfClose && !voids.has(name)) {
        stack.push(node.children);
        tagStack.push(name);
      }
    } else {
      const next = html.indexOf('<', i);
      const text = (next < 0 ? html.slice(i) : html.slice(i, next))
        .replace(/&nbsp;/g, ' ')
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'");
      if (text.trim()) {
        stack[stack.length - 1].push({ type: 'text', text });
      }
      i = next < 0 ? html.length : next;
    }
  }
  return out;
}

function renderNode(n: Node, key: string | number): React.ReactNode {
  if (n.type === 'text') return <Text key={key}>{n.text}</Text>;
  const k = String(key);
  const kids = n.children.map((c, idx) => renderNode(c, `${k}.${idx}`));
  switch (n.name) {
    case 'h1':
    case 'h2':
      return (
        <Text key={k} style={s.h2}>
          {kids}
        </Text>
      );
    case 'h3':
      return (
        <Text key={k} style={s.h3}>
          {kids}
        </Text>
      );
    case 'h4':
      return (
        <Text key={k} style={s.h4}>
          {kids}
        </Text>
      );
    case 'p':
      return (
        <Text key={k} style={s.p}>
          {kids}
        </Text>
      );
    case 'ul':
    case 'ol':
      return (
        <View key={k} style={s.list}>
          {kids}
        </View>
      );
    case 'li':
      return (
        <View key={k} style={s.li}>
          <Text style={s.liDot}>•  </Text>
          <Text style={[s.p, { flex: 1 }]}>{kids}</Text>
        </View>
      );
    case 'strong':
    case 'b':
      return (
        <Text key={k} style={s.bold}>
          {kids}
        </Text>
      );
    case 'em':
    case 'i':
      return (
        <Text key={k} style={s.italic}>
          {kids}
        </Text>
      );
    case 'a':
      return (
        <Text
          key={k}
          style={s.link}
          onPress={() => {
            const href = n.attrs.href || '';
            if (href) Linking.openURL(absolutize(href)).catch(() => {});
          }}
        >
          {kids}
        </Text>
      );
    case 'img':
      return (
        <Image
          key={k}
          source={{ uri: absolutize(n.attrs.src || '') }}
          style={s.img}
          resizeMode="contain"
        />
      );
    case 'br':
      return <Text key={k}>{'\n'}</Text>;
    case 'hr':
      return <View key={k} style={s.hr} />;
    default:
      // Unknown tag — render children inline.
      return <React.Fragment key={k}>{kids}</React.Fragment>;
  }
}

// ───────────────────────── Component ─────────────────────────

export function LegalHtml({ html }: { html: string }) {
  const safe = useMemo(() => sanitizeHtml(html || ''), [html]);

  if (Platform.OS === 'web') {
    // Wrap in a div whose styles inherit from the surrounding RN layout.
    return (
      // @ts-ignore — RN-Web passes through unknown DOM attributes
      <div
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: safe }}
        style={{
          color: COLORS.text,
          fontSize: 16,
          lineHeight: 1.55,
          fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif',
        }}
      />
    );
  }

  const tree = useMemo(() => parseHtml(safe), [safe]);
  return <View>{tree.map((n, i) => renderNode(n, i))}</View>;
}

const s = StyleSheet.create({
  h2: {
    fontSize: 22,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginTop: SPACING.lg,
    marginBottom: SPACING.sm,
  },
  h3: {
    fontSize: 18,
    fontWeight: FONT.weights.bold,
    color: COLORS.text,
    marginTop: SPACING.md,
    marginBottom: SPACING.xs,
  },
  h4: {
    fontSize: 16,
    fontWeight: FONT.weights.semibold,
    color: COLORS.text,
    marginTop: SPACING.md,
    marginBottom: 4,
  },
  p: {
    fontSize: FONT.sizes.md,
    lineHeight: 22,
    color: COLORS.text,
    marginBottom: SPACING.sm,
  },
  list: { marginBottom: SPACING.sm },
  li: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 4 },
  liDot: { color: COLORS.text, fontSize: FONT.sizes.md, lineHeight: 22 },
  bold: { fontWeight: FONT.weights.bold },
  italic: { fontStyle: 'italic' },
  link: { color: COLORS.primary, textDecorationLine: 'underline' },
  img: {
    width: '100%',
    aspectRatio: 16 / 9,
    borderRadius: 8,
    marginVertical: SPACING.sm,
    backgroundColor: COLORS.surface,
  },
  hr: {
    height: 1,
    backgroundColor: COLORS.border,
    marginVertical: SPACING.md,
  },
});

export default LegalHtml;
