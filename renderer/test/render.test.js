"use strict";

const test = require("node:test");
const assert = require("node:assert");
const { site, everySection, LIGHT } = require("./fixtures");
const { renderPage, tokenCss } = require("../lib/page");
const { renderSection } = require("../lib/sections");
const { onColor, placeholderUrl, pyQuote } = require("../lib/util");

const home = (doc = site()) => renderPage(doc, doc.pages[0], "p1");
const ctx = { ctaHref: () => "/x", pad: "py-16", index: 0 };

test("every section type renders with its id, type and hash for the editor to select", () => {
  const types = new Set();
  const all = site().pages.flatMap((p) => p.sections);
  for (const s of all) {
    const html = renderSection(s, ctx);
    types.add(s.type);
    assert.match(html, new RegExp(`<section id="${s.section_id}" data-section-id="${s.section_id}" data-section-type="${s.type}" data-section-hash="${s.content_hash}"`));
  }
  assert.strictEqual(types.size, 17);
});

test("each section is self-contained HTML (one <section> per section)", () => {
  for (const s of everySection) {
    const html = renderSection(s, ctx);
    assert.strictEqual((html.match(/<section /g) || []).length, 1);
    assert.strictEqual((html.match(/<\/section>/g) || []).length, 1);
  }
});

test("content is escaped: markup in copy never becomes markup", () => {
  const evil = `<script>alert(1)</script><img src=x onerror=alert(2)>`;
  const doc = site();
  doc.brand_name = evil;
  doc.pages[0].sections = [
    { section_id: "home-hero", type: "hero", content: { heading: evil, subheading: evil, primary_cta: { label: evil, href: "javascript:alert(1)" } }, image_placeholder: { label: evil } },
    { section_id: "home-f", type: "features", content: { heading: evil, items: [{ title: evil, description: evil }, evil] } },
    { section_id: "home-form", type: "contact_form", content: { heading: "x", fields: [{ label: evil, type: "file" }] } },
  ];
  const html = home(doc);
  assert.ok(!/<script/i.test(html), "no script element");
  assert.ok(!/<img src=x/i.test(html), "no injected img");
  assert.ok(!/href="javascript:/i.test(html), "no javascript: links");
  assert.ok(!/type="file"/.test(html), "field types are allow-listed");
});

test("CTAs: https passes, known page resolves, unknown page and junk fall back to /contact", () => {
  const doc = site();
  const links = (href) => {
    doc.pages[0].sections = [{ section_id: "home-b", type: "cta_banner", content: { heading: "h", primary_cta: { label: "Go", href } } }];
    return home(doc).match(/<a class="inline-flex[^>]*href="([^"]*)"/)[1];
  };
  assert.strictEqual(links("https://example.com/book"), "https://example.com/book");
  assert.strictEqual(links("/about"), "/preview/p1/about");
  assert.strictEqual(links("/gone"), "/preview/p1/contact");
  assert.strictEqual(links("javascript:alert(1)"), "/preview/p1/contact");
  assert.strictEqual(links(undefined), "/preview/p1/contact");
});

test("legacy content shapes (title/body items, string fields, string CTA) still render", () => {
  const doc = site();
  doc.pages[0].sections = [
    { section_id: "home-h", type: "hero", content: { heading: "Hi", subheading: "There", primary_cta: "Enquire" } },
    { section_id: "home-f", type: "features", content: { heading: "F", items: [{ t: "odd" }, { name: "Named", body: "Body text" }] } },
    { section_id: "home-s", type: "stats", content: { items: [{ title: "99%", description: "Happy" }] } },
    { section_id: "home-c", type: "contact_form", content: { heading: "C", fields: ["name", "email"] } },
  ];
  const html = home(doc);
  assert.match(html, /Named/);
  assert.match(html, /Body text/);
  assert.match(html, /99%/);
  assert.match(html, /type="email"/);
  assert.match(html, />Enquire</);
});

test("unknown section types and missing content degrade to a prose section instead of throwing", () => {
  const html = renderSection({ section_id: "home-x", type: "future_type", content: { heading: "H", body: "B" } }, ctx);
  assert.match(html, /<h2[^>]*>H<\/h2>/);
  assert.doesNotThrow(() => renderSection({ section_id: "home-y", type: "hero" }, ctx));
});

test("design tokens: validated hex, readable on-colours, safe font names, bounded font size", () => {
  const css = tokenCss({ colors: { ...LIGHT, primary: "red;}body{display:none" }, heading_font: "A'; } x{", body_font: "Inter", base_font_size_px: 99, radius: "full", spacing: "x" });
  assert.ok(!css.includes("display:none"));
  assert.match(css, /--site-primary:#0f172a/); // invalid value -> default
  assert.match(css, /--site-font-heading:'A x'/);
  assert.match(css, /html\{font-size:16px\}/);
  assert.match(css, /--site-radius-btn:999px/);
  assert.strictEqual(onColor("#ffffff"), "#0f172a");
  assert.strictEqual(onColor("#0B3D2E"), "#ffffff");
  assert.strictEqual(onColor("#C9A227"), "#0f172a"); // gold: white text would be ~2.3:1
});

test("placeholder URLs match the backend's ImagePlaceholder.url", () => {
  assert.strictEqual(
    placeholderUrl({ width: 1200, height: 600, bg_hex: "1d3557", text_hex: "f1faee", label: "Hero (A&B)!" }),
    "https://placehold.co/1200x600/1d3557/f1faee?text=Hero%20%28A%26B%29%21",
  );
  assert.strictEqual(pyQuote("a/b c"), "a/b%20c");
  assert.match(placeholderUrl({ width: 5, bg_hex: "zz", label: "x" }), /800x400\/e2e8f0\/1e293b/);
});

test("page shell: stylesheet link, nonce'd token block, skip link, mobile + desktop nav", () => {
  const html = renderPage(site(), site().pages[0], "p/1", { nonce: "abc", cssVersion: "v1" });
  assert.match(html, /<link rel="stylesheet" href="\/assets\/tailwind\.css\?v=v1"/);
  assert.match(html, /<style nonce="abc">:root\{/);
  assert.match(html, /href="#main"/);
  assert.match(html, /href="\/preview\/p%2F1\/about"/); // project id is encoded
  assert.match(html, /aria-label="Mobile"/);
  assert.ok(!/<script/i.test(html));
});

test("section tones alternate down the page and cards flip against their section", () => {
  const a = renderSection(everySection[1], { ...ctx, index: 0 });
  const b = renderSection(everySection[1], { ...ctx, index: 1 });
  assert.match(a, /class="bg-canvas text-ink /);
  assert.match(a, /bg-surface rounded-site/);
  assert.match(b, /class="bg-surface text-ink /);
  assert.match(b, /bg-canvas rounded-site/);
});
