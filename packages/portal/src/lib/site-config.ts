/**
 * Single source of truth for the app's identity: name, description, and brand
 * icon.
 *
 * Consumed by:
 *  - app/layout.tsx        — document <title>/<meta description> and the favicon
 *                            (an inline SVG data URI built from siteIconSvg)
 *  - components/navbar.tsx — the brand icon + name + tagline (header)
 *
 * `name` and `tagline` are overridable per deployment via NEXT_PUBLIC_SITE_NAME
 * / NEXT_PUBLIC_SITE_TAGLINE (see .env.example) — navbar.tsx is a Client
 * Component, so only NEXT_PUBLIC_-prefixed env vars are readable here;
 * Next.js inlines them into the client bundle at build time.
 *
 * The icon is stored as raw SVG markup (not JSX) so the exact same artwork can
 * be both injected into a React <svg> (navbar) and serialized into the favicon
 * data URI. Paths use currentColor: the navbar recolors it via CSS to sit on
 * the white top bar, while the favicon wraps it in a filled brand-coloured tile
 * with a white glyph so it stands out on both light and dark browser tabs.
 */
export const siteConfig = {
  name: process.env.NEXT_PUBLIC_SITE_NAME || "TechneOS",
  // Short, punchy line for the home hero.
  tagline:
    process.env.NEXT_PUBLIC_SITE_TAGLINE ||
    "Codified workflows. Informed decisions. Accelerated discoveries.",
  // Fuller sentence for the <meta name="description"> tag.
  description:
    "One platform to orchestrate research workflows — from data and tools to pipelines and agents — so teams move from experiments to decisions faster.",
  icon: {
    viewBox: "0 0 32 32",
    // A central hub wired to four orbiting nodes — orchestrating research streams.
    inner: `
      <line x1="16" y1="16" x2="16" y2="6.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      <line x1="16" y1="16" x2="25.5" y2="16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      <line x1="16" y1="16" x2="16" y2="25.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      <line x1="16" y1="16" x2="6.5" y2="16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="16" cy="6" r="2.6" fill="currentColor"/>
      <circle cx="26" cy="16" r="2.6" fill="currentColor"/>
      <circle cx="16" cy="26" r="2.6" fill="currentColor"/>
      <circle cx="6" cy="16" r="2.6" fill="currentColor"/>
      <circle cx="16" cy="16" r="4.2" fill="none" stroke="currentColor" stroke-width="1.8"/>
      <circle cx="16" cy="16" r="1.7" fill="currentColor"/>
    `,
  },
} as const;

/**
 * The brand icon as a standalone SVG string for the favicon: a filled
 * brand-coloured tile (so it has contrast on light *and* dark tabs) with the
 * glyph in white. The glyph markup uses currentColor, set to white here.
 */
export function siteIconSvg(tile = "#4f46e5", glyph = "#ffffff"): string {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${siteConfig.icon.viewBox}" color="${glyph}">` +
    `<rect width="32" height="32" rx="7" fill="${tile}"/>` +
    `${siteConfig.icon.inner}</svg>`
  );
}

/** Favicon as an inline SVG data URI, derived from the same icon. */
export const siteIconDataUri = `data:image/svg+xml,${encodeURIComponent(siteIconSvg())}`;
