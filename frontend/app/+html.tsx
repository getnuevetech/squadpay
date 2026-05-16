// @ts-nocheck
import { ScrollViewStyleReset } from "expo-router/html";
import type { PropsWithChildren } from "react";

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en" style={{ height: "100%" }}>
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, shrink-to-fit=no"
        />

        {/* ─── Brand icons (May 2026 refresh) ────────────────────────────
            Multi-resolution favicon.ico + apple-touch-icon + OG/Twitter
            preview, all served from /public so they ship with every
            `expo export --platform web` build. Cache-buster `v` bumped
            whenever the logo changes so browsers refetch instead of
            holding the old icon for ages. */}
        <title>SquadPay</title>
        <meta name="description" content="Split bills with your squad in seconds — pay, scan receipts, settle up." />
        <meta name="theme-color" content="#7C3AED" />

        <link rel="icon" href="/favicon.ico?v=2" sizes="any" />
        <link rel="icon" type="image/png" sizes="32x32" href="/favicon.ico?v=2" />
        <link rel="icon" type="image/png" sizes="192x192" href="/apple-touch-icon.png?v=2" />
        <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png?v=2" />
        <link rel="mask-icon" href="/apple-touch-icon.png?v=2" color="#7C3AED" />

        {/* Open Graph / social preview */}
        <meta property="og:title" content="SquadPay — Split bills with your squad" />
        <meta property="og:description" content="Pay, scan receipts and settle up instantly." />
        <meta property="og:image" content="/og-image.png?v=2" />
        <meta property="og:type" content="website" />
        <meta property="og:url" content="https://www.squadpay.us/" />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:image" content="/og-image.png?v=2" />

        {/*
          Disable body scrolling on web to make ScrollView components work correctly.
          If you want to enable scrolling, remove `ScrollViewStyleReset` and
          set `overflow: auto` on the body style below.
        */}
        <ScrollViewStyleReset />
        <style
          dangerouslySetInnerHTML={{
            __html: `
              body > div:first-child { position: fixed !important; top: 0; left: 0; right: 0; bottom: 0; }
              [role="tablist"] [role="tab"] * { overflow: visible !important; }
              [role="heading"], [role="heading"] * { overflow: visible !important; }
            `,
          }}
        />
      </head>
      <body
        style={{
          margin: 0,
          height: "100%",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {children}
      </body>
    </html>
  );
}
