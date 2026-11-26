"use strict";

/**
 * Page shell: <head>, design tokens, navigation, footer. Section HTML comes from sections.js.
 *
 * Styling is Tailwind. The brand's colours/fonts/radius are NOT baked into the stylesheet:
 * they are emitted per request as CSS variables (--site-*), and styles/input.css maps them to
 * Tailwind theme values (bg-primary, text-ink, font-heading, rounded-site, ...). One compiled
 * stylesheet therefore serves every project.
 */

const { esc, hexOr, fontName, onColor, isObj } = require("./util");
const { renderSection } = require("./sections");

// Static class strings per spacing token (whole literals, so the Tailwind build sees them).
const SECTION_PAD = {
  compact: "py-12 md:py-16",
  comfortable: "py-16 md:py-24",
  spacious: "py-24 md:py-32",
};
// [cards/images, buttons]
const RADIUS = {
  none: ["0", "0"],
  sm: [".25rem", ".25rem"],
  md: [".5rem", ".5rem"],
  lg: ["1rem", ".75rem"],
  full: ["1.5rem", "999px"],
};

const LINK = "font-medium opacity-90 underline-offset-4 transition hover:underline hover:opacity-100";
const DROPDOWN =
  "invisible absolute left-0 top-full min-w-44 rounded-site bg-primary p-2 opacity-0 shadow-lg " +
  "ring-1 ring-on-primary/20 transition group-hover:visible group-hover:opacity-100 " +
  "group-focus-within:visible group-focus-within:opacity-100";

const DEFAULTS = {
  primary: "#0f172a", secondary: "#334155", accent: "#2563eb",
  background: "#ffffff", surface: "#f8fafc", text: "#0f172a",
};

/** Design tokens -> `:root{...}` declarations. Every value is validated, none is passed through raw. */
const tokenCss = (tokens) => {
  const t = tokens || {};
  const col = t.colors || {};
  const c = Object.fromEntries(Object.entries(DEFAULTS).map(([k, d]) => [k, hexOr(col[k], d)]));
  const [radius, btnRadius] = RADIUS[t.radius] || RADIUS.md;
  const size = Number(t.base_font_size_px);
  const base = Number.isFinite(size) && size >= 14 && size <= 20 ? size : 16;
  return `:root{
    --site-primary:${c.primary};--site-secondary:${c.secondary};--site-accent:${c.accent};
    --site-bg:${c.background};--site-surface:${c.surface};--site-text:${c.text};
    --site-on-primary:${onColor(c.primary)};--site-on-accent:${onColor(c.accent)};
    --site-font-heading:${fontName(t.heading_font, "Georgia")};--site-font-body:${fontName(t.body_font, "Inter")};
    --site-radius:${radius};--site-radius-btn:${btnRadius};
  }html{font-size:${base}px}`;
};

const MENU_ICON =
  '<svg class="size-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
  'stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>';

/**
 * @param {object} doc        the SiteDocument (JSON from the backend)
 * @param {object} page       one of doc.pages
 * @param {string} projectId
 * @param {{nonce?: string, cssVersion?: string}} [opts]
 */
const renderPage = (doc, page, projectId, opts = {}) => {
  const pid = encodeURIComponent(projectId);
  const known = new Set(doc.pages.map((p) => p.slug));
  const slugOf = (s) => "/" + String(s || "").split("/").filter(Boolean).join("/");
  const navHref = (slug) => {
    const parts = String(slug || "/").split("/").filter(Boolean).map(encodeURIComponent);
    return `/preview/${pid}/${parts.join("/")}`;
  };

  // CTA targets: https URL, or a page that exists. Anything else falls back instead of 404ing.
  const fallback = navHref(known.has("/contact") ? "/contact" : "/");
  const ctaHref = (cta) => {
    const href = isObj(cta) ? cta.href : undefined;
    if (typeof href !== "string" || !href) return fallback;
    if (/^https?:\/\//i.test(href)) return href;
    return known.has(slugOf(href)) ? navHref(href) : fallback;
  };

  const desktopItem = (n) => {
    const kids = Array.isArray(n.children) ? n.children : [];
    const link = `<a class="${LINK}" href="${esc(navHref(n.slug))}">${esc(n.label)}</a>`;
    if (!kids.length) return link;
    return `<div class="group relative">${link}<div class="${DROPDOWN}">${kids.map((k) =>
      `<a class="block rounded-btn px-3 py-2 text-sm hover:bg-on-primary/10" href="${esc(navHref(k.slug))}">${esc(k.label)}</a>`
    ).join("")}</div></div>`;
  };
  const mobileItem = (n) => {
    const kids = Array.isArray(n.children) ? n.children : [];
    return `<a class="block rounded-btn px-3 py-2 font-medium hover:bg-on-primary/10" href="${esc(navHref(n.slug))}">${esc(n.label)}</a>${kids.map((k) =>
      `<a class="block rounded-btn py-2 pl-6 pr-3 text-sm opacity-90 hover:bg-on-primary/10" href="${esc(navHref(k.slug))}">${esc(k.label)}</a>`
    ).join("")}`;
  };
  const navItems = doc.navigation || [];

  const footerLinks = (doc.footer_links || []).map((slug) => {
    const target = doc.pages.find((p) => p.slug === slug);
    return `<a class="font-medium text-ink/80 underline-offset-4 hover:text-ink hover:underline" href="${esc(navHref(slug))}">${esc(target ? target.title : slug)}</a>`;
  }).join("");

  const pad = SECTION_PAD[(doc.tokens || {}).spacing] || SECTION_PAD.comfortable;
  const sections = (page.sections || [])
    .map((s, index) => renderSection(s, { ctaHref, pad, index }))
    .join("\n");

  const nonce = opts.nonce ? ` nonce="${esc(opts.nonce)}"` : "";
  const css = `/assets/tailwind.css${opts.cssVersion ? `?v=${encodeURIComponent(opts.cssVersion)}` : ""}`;

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>${esc((page.meta && page.meta.title) || page.title)}</title>
<meta name="description" content="${esc((page.meta && page.meta.description) || "")}"/>
<link rel="stylesheet" href="${esc(css)}"/>
<style${nonce}>${tokenCss(doc.tokens)}</style>
</head>
<body class="min-h-screen bg-canvas font-body text-ink antialiased">
<a href="#main" class="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-30 focus:rounded-btn focus:bg-accent focus:px-4 focus:py-2 focus:text-on-accent">Skip to content</a>
<header class="sticky top-0 z-20 border-b border-on-primary/15 bg-primary text-on-primary">
  <div class="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
    <a href="${esc(navHref("/"))}" class="font-heading text-xl font-bold">${esc(doc.brand_name)}</a>
    <nav aria-label="Main" class="hidden items-center gap-8 md:flex">${navItems.map(desktopItem).join("")}</nav>
    <details class="group relative md:hidden">
      <summary class="flex cursor-pointer list-none items-center rounded-btn p-2 hover:bg-on-primary/10 [&::-webkit-details-marker]:hidden" aria-label="Menu">${MENU_ICON}</summary>
      <nav aria-label="Mobile" class="absolute right-0 mt-3 w-60 rounded-site bg-primary p-2 shadow-lg ring-1 ring-on-primary/20">${navItems.map(mobileItem).join("")}</nav>
    </details>
  </div>
</header>
<main id="main">
${sections}
</main>
<footer class="border-t border-ink/10 bg-surface py-10 text-center text-sm text-ink/70">
  <div class="mx-auto max-w-6xl px-6">
    <p>&copy; ${new Date().getFullYear()} ${esc(doc.brand_name)}</p>
    ${footerLinks ? `<div class="mt-3 flex flex-wrap justify-center gap-x-6 gap-y-2">${footerLinks}</div>` : ""}
  </div>
</footer>
</body></html>`;
};

module.exports = { renderPage, tokenCss, SECTION_PAD };
