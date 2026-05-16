/**
 * Public /legal/terms screen.
 *
 * Rebuilt May 2026 to consume the admin-managed Terms content from
 * `/api/legal/pages/terms` like the other legal pages (privacy / support),
 * rather than rendering a hardcoded JSX wall. Previously every admin edit
 * appeared in the API but never reached the public page because this file
 * had the entire T&C baked into <Text> components.
 *
 * Deep-link backwards compatibility:
 *   - The old `?section=credits` URL is preserved for inbound links from
 *     SMS messages and the contribution success page. After the markdown
 *     is rendered we scan the document for a "credits" heading and scroll
 *     to it. If the admin removes the heading the parameter is ignored
 *     gracefully (page just opens at the top).
 */
import { useEffect } from 'react';
import { Platform } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { LegalPageScreen } from '../../src/components/LegalPageScreen';

export default function TermsScreen() {
  const params = useLocalSearchParams<{ section?: string }>();

  useEffect(() => {
    // Preserve the legacy `?section=credits` deep-link. After the markdown
    // has rendered, find a heading whose text contains "credit" and scroll
    // it into view. Native fallback: just leave the page at the top.
    if (Platform.OS !== 'web' || params.section !== 'credits') return;
    const tries = [80, 200, 400, 800, 1500];
    let cancelled = false;
    const attempt = () => {
      if (cancelled) return;
      const headings = Array.from(
        document.querySelectorAll('h1, h2, h3, h4'),
      ) as HTMLElement[];
      const target = headings.find((h) => /credit/i.test(h.textContent || ''));
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return true;
      }
      return false;
    };
    const timers = tries.map((t) =>
      setTimeout(() => {
        if (!cancelled) attempt();
      }, t),
    );
    return () => {
      cancelled = true;
      timers.forEach((id) => clearTimeout(id));
    };
  }, [params.section]);

  return <LegalPageScreen slug="terms" />;
}
