"use strict";

/**
 * One function per section type; each returns the section's complete HTML, styled with
 * Tailwind utility classes (compiled ahead of time by `npm run build:css`, which scans this
 * directory - so classes must appear as WHOLE literal strings, never be assembled from parts).
 *
 * Every section is wrapped by `wrap()` with data-section-* attributes. That is the hook for
 * conversational editing: the preview selects a section by `data-section-id`, and the content
 * hash tells it whether its copy of the section is stale.
 */

const {
  esc, str, isObj, pick, itemTitle, itemBody, ctaLabel, paragraphs, placeholderUrl,
} = require("./util");

/* ------------------------------------------------------------------ *
 * Shared class strings
 * ------------------------------------------------------------------ */

const CONTAINER = "mx-auto w-full max-w-6xl px-6";
const H2 = "font-heading text-3xl font-bold tracking-tight text-ink text-balance md:text-4xl";
const SUB = "mt-4 text-lg text-ink/75 text-pretty";
const BTN =
  "inline-flex items-center justify-center rounded-btn bg-accent px-6 py-3 text-base font-semibold " +
  "text-on-accent shadow-sm transition hover:brightness-110 focus-visible:outline-2 " +
  "focus-visible:outline-offset-2 focus-visible:outline-accent";

const TONES = {
  canvas: "bg-canvas text-ink",
  surface: "bg-surface text-ink",
  primary: "bg-primary text-on-primary",
};

// Cards sit on the opposite tone from their section so they stay visible.
const cardBg = (tone) => (tone === "surface" ? "bg-canvas" : "bg-surface");
const CARD = "rounded-site p-6 ring-1 ring-ink/10 shadow-sm";

// Literal class strings per column count (see the note at the top about whole literals).
const gridCols = (n) => {
  if (n <= 2) return "mx-auto grid max-w-3xl gap-6 sm:grid-cols-2";
  if (n === 4) return "grid gap-6 sm:grid-cols-2 lg:grid-cols-4";
  return "grid gap-6 sm:grid-cols-2 lg:grid-cols-3";
};

/* ------------------------------------------------------------------ *
 * Building blocks
 * ------------------------------------------------------------------ */

const statCols = (n) => {
  if (n <= 2) return "mx-auto grid max-w-xl gap-8 sm:grid-cols-2";
  if (n === 3) return "mx-auto grid max-w-3xl gap-8 sm:grid-cols-3";
  return "mx-auto grid max-w-5xl gap-8 sm:grid-cols-2 lg:grid-cols-4";
};

const items = (c) => (Array.isArray(c.items) ? c.items : []);

const heading = (c, align = "text-center") =>
  c.heading ? `<div class="${align} mb-12"><h2 class="${H2}">${esc(c.heading)}</h2>${
    c.subheading ? `<p class="${SUB} ${align === "text-center" ? "mx-auto max-w-2xl" : ""}">${esc(c.subheading)}</p>` : ""
  }</div>` : "";

const cta = (c, ctx) => c.primary_cta
  ? `<a class="${BTN}" href="${esc(ctx.ctaHref(c.primary_cta))}">${esc(ctaLabel(c.primary_cta))}</a>`
  : "";

const img = (ph, { cls, eager = false } = {}) => {
  const url = placeholderUrl(ph);
  if (!url) return "";
  const w = ph.width ?? 800;
  const h = ph.height ?? 400;
  return `<img src="${esc(url)}" alt="${esc(ph.label || "")}" width="${esc(w)}" height="${esc(h)}" ` +
    `${eager ? 'fetchpriority="high"' : 'loading="lazy"'} class="${cls}"/>`;
};

// Alternate canvas/surface down the page unless a section asks for a fixed tone.
const toneOf = (ctx, fixed) => fixed || (ctx.index % 2 === 0 ? "canvas" : "surface");

const wrap = (s, ctx, inner, tone) =>
  `<section id="${esc(s.section_id)}" data-section-id="${esc(s.section_id)}" ` +
  `data-section-type="${esc(s.type)}" data-section-hash="${esc(s.content_hash || "")}" ` +
  `class="${TONES[toneOf(ctx, tone)]} ${ctx.pad}"><div class="${CONTAINER}">${inner}</div></section>`;

/* ------------------------------------------------------------------ *
 * Section renderers
 * ------------------------------------------------------------------ */

const hero = (s, ctx) => {
  const c = s.content;
  const image = img(s.image_placeholder, {
    eager: true,
    cls: "aspect-video w-full rounded-site object-cover shadow-xl ring-1 ring-ink/10",
  });
  const text = (center) => `<div class="${center ? "mx-auto max-w-3xl text-center" : "text-center lg:text-left"}">
      <h1 class="font-heading text-4xl font-bold tracking-tight text-ink text-balance md:text-6xl">${esc(c.heading)}</h1>
      <p class="mt-6 text-lg text-ink/80 text-pretty md:text-xl ${center ? "mx-auto" : "mx-auto max-w-xl lg:mx-0"}">${esc(c.subheading || "")}</p>
      <div class="mt-8">${cta(c, ctx)}</div></div>`;
  return wrap(s, ctx,
    image ? `<div class="grid items-center gap-12 lg:grid-cols-2">${text(false)}${image}</div>` : text(true),
    "surface");
};

const cards = (s, ctx) => {
  const c = s.content, list = items(c), tone = toneOf(ctx);
  const bg = cardBg(tone);
  const body = list.map((it, i) => {
    const price = pick(it, "price");
    const lead =
      s.type === "process_steps"
        ? `<span class="mb-4 flex size-10 items-center justify-center rounded-full bg-primary font-bold text-on-primary">${i + 1}</span>`
        : s.type === "team"
          ? `<span class="mb-4 flex size-14 items-center justify-center rounded-full bg-primary font-heading text-xl font-bold text-on-primary" aria-hidden="true">${esc(itemTitle(it).charAt(0).toUpperCase())}</span>`
          : "";
    return `<div class="${bg} ${CARD}">${lead}
      <h3 class="font-heading text-xl font-semibold text-ink">${esc(itemTitle(it))}</h3>
      <p class="mt-2 text-ink/75">${esc(itemBody(it))}</p>
      ${price ? `<p class="mt-4 font-semibold text-accent">${esc(price)}</p>` : ""}</div>`;
  }).join("");
  return wrap(s, ctx, `${heading(c)}<div class="${gridCols(list.length)}">${body}</div>`, tone);
};

const pricing = (s, ctx) => {
  const c = s.content, list = items(c), tone = toneOf(ctx), bg = cardBg(tone);
  const body = list.map((it) => {
    const features = Array.isArray(it.features) ? it.features : [];
    return `<div class="${bg} ${CARD} flex flex-col">
      <h3 class="font-heading text-xl font-semibold text-ink">${esc(itemTitle(it))}</h3>
      <p class="mt-4 font-heading text-4xl font-bold text-ink">${esc(pick(it, "price"))}</p>
      ${itemBody(it) ? `<p class="mt-3 text-ink/75">${esc(itemBody(it))}</p>` : ""}
      ${features.length ? `<ul class="mt-6 space-y-2 text-ink/80">${features.map((f) =>
        `<li class="flex gap-2"><span class="text-accent" aria-hidden="true">&#10003;</span><span>${esc(f)}</span></li>`).join("")}</ul>` : ""}
      <a class="${BTN} mt-8" href="${esc(ctx.ctaHref(null))}">Get started</a></div>`;
  }).join("");
  return wrap(s, ctx, `${heading(c)}<div class="${gridCols(list.length)}">${body}</div>`, tone);
};

const faq = (s, ctx) => {
  const c = s.content, tone = toneOf(ctx), bg = cardBg(tone);
  const body = items(c).map((it) =>
    `<details class="group ${bg} rounded-site p-5 ring-1 ring-ink/10">
      <summary class="flex cursor-pointer list-none items-center justify-between gap-4 font-semibold text-ink [&::-webkit-details-marker]:hidden">
        <span>${esc(itemTitle(it))}</span>
        <span class="text-2xl leading-none text-accent transition group-open:rotate-45" aria-hidden="true">+</span>
      </summary>
      <p class="mt-3 text-ink/75">${esc(itemBody(it))}</p></details>`).join("");
  return wrap(s, ctx, `${heading(c)}<div class="mx-auto max-w-3xl space-y-3">${body}</div>`, tone);
};

const testimonials = (s, ctx) => {
  const c = s.content, list = items(c), tone = toneOf(ctx), bg = cardBg(tone);
  const body = list.map((it) => {
    const quote = pick(it, "quote", "description", "body", "text");
    const author = pick(it, "author", "title", "name");
    const role = pick(it, "role");
    return `<figure class="${bg} ${CARD} flex flex-col justify-between">
      <blockquote class="text-lg text-ink/90">&ldquo;${esc(quote)}&rdquo;</blockquote>
      <figcaption class="mt-6"><span class="font-semibold text-ink">${esc(author)}</span>${
        role ? `<span class="block text-sm text-ink/60">${esc(role)}</span>` : ""}</figcaption></figure>`;
  }).join("");
  return wrap(s, ctx, `${heading(c)}<div class="${gridCols(list.length)}">${body}</div>`, tone);
};

const stats = (s, ctx) => {
  const c = s.content, list = items(c);
  const body = list.map((it) => `<div class="text-center">
      <p class="font-heading text-4xl font-bold md:text-5xl">${esc(pick(it, "value", "title", "name") || itemTitle(it))}</p>
      <p class="mt-2 text-sm uppercase tracking-wide opacity-80">${esc(pick(it, "label", "description", "body"))}</p></div>`).join("");
  return wrap(s, ctx, `${heading(c)}<div class="${statCols(list.length)}">${body}</div>`, "primary");
};

const gallery = (s, ctx) => {
  const c = s.content, list = items(c), base = s.image_placeholder || {};
  const body = list.map((it) => {
    const label = (isObj(it) && (it.label || it.title)) || base.label || "Image";
    const merged = { ...base, label };
    if (isObj(it)) {
      if (it.width != null) merged.width = it.width;
      if (it.height != null) merged.height = it.height;
      if (it.bg_hex) merged.bg_hex = it.bg_hex;
      if (it.text_hex) merged.text_hex = it.text_hex;
    }
    const caption = pick(it, "caption");
    return `<figure>${img(merged, { cls: "aspect-4/3 w-full rounded-site object-cover ring-1 ring-ink/10" })}${
      caption ? `<figcaption class="mt-2 text-sm text-ink/70">${esc(caption)}</figcaption>` : ""}</figure>`;
  }).join("");
  return wrap(s, ctx, `${heading(c)}<div class="${gridCols(list.length)}">${body}</div>`);
};

const ctaBanner = (s, ctx) => {
  const c = s.content;
  return wrap(s, ctx, `<div class="mx-auto max-w-3xl text-center">
      <h2 class="${H2}">${esc(c.heading)}</h2>
      ${c.subheading ? `<p class="${SUB}">${esc(c.subheading)}</p>` : ""}
      <div class="mt-8">${cta(c, ctx)}</div></div>`, "surface");
};

const FIELD_TYPES = new Set(["text", "email", "tel", "textarea"]);
const INPUT = "mt-1.5 block w-full rounded-btn border border-ink/25 bg-canvas px-4 py-3 text-ink " +
  "placeholder:text-ink/50 focus:outline-2 focus:outline-offset-1 focus:outline-accent";

const contactForm = (s, ctx) => {
  const c = s.content;
  const fields = Array.isArray(c.fields) ? c.fields : [];
  const body = fields.map((f) => {
    const label = isObj(f) ? pick(f, "label", "name") : str(f);
    const type = isObj(f) && FIELD_TYPES.has(f.type) ? f.type : /e-?mail/i.test(label) ? "email" : "text";
    const required = isObj(f) && f.required === true ? " required" : "";
    const name = esc(label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, ""));
    const control = type === "textarea"
      ? `<textarea name="${name}" rows="4" class="${INPUT}"${required}></textarea>`
      : `<input name="${name}" type="${type}" class="${INPUT}"${required}/>`;
    return `<label class="block text-sm font-semibold text-ink">${esc(label)}${control}</label>`;
  }).join("");
  return wrap(s, ctx, `${heading(c)}<form class="mx-auto max-w-xl space-y-5">${body}
      <button class="${BTN} w-full" type="button">Send</button></form>`);
};

const mapLocation = (s, ctx) => {
  const c = s.content;
  const image = img(s.image_placeholder, { cls: "mt-8 aspect-video w-full rounded-site object-cover ring-1 ring-ink/10" });
  return wrap(s, ctx, `<div class="mx-auto max-w-3xl text-center">
      <h2 class="${H2}">${esc(c.heading)}</h2>
      <p class="mt-4 text-lg text-ink/75">${esc(c.address || "")}</p>${image}</div>`);
};

const prose = (s, ctx) => {
  const c = s.content;
  const text = paragraphs(c.body || c.subheading).map((p) => `<p>${esc(p)}</p>`).join("");
  const image = img(s.image_placeholder, { cls: "aspect-4/3 w-full rounded-site object-cover shadow-lg ring-1 ring-ink/10" });
  const copy = `<div>${c.heading ? `<h2 class="${H2}">${esc(c.heading)}</h2>` : ""}
      <div class="${c.heading ? "mt-6 " : ""}space-y-4 text-lg leading-relaxed text-ink/80">${text}</div></div>`;
  return wrap(s, ctx, image
    ? `<div class="grid items-center gap-12 lg:grid-cols-2">${copy}${image}</div>`
    : `<div class="mx-auto max-w-3xl">${copy}</div>`);
};

const blogList = (s, ctx) => wrap(s, ctx,
  `${heading(s.content)}<p class="text-center text-ink/70">Posts coming soon.</p>`);

/* ------------------------------------------------------------------ *
 * Dispatch
 * ------------------------------------------------------------------ */

const RENDERERS = {
  hero,
  features: cards,
  services: cards,
  process_steps: cards,
  catalog: cards,
  team: cards,
  pricing,
  faq,
  testimonials,
  stats,
  gallery,
  cta_banner: ctaBanner,
  contact_form: contactForm,
  map_location: mapLocation,
  about: prose,
  rich_text: prose,
  blog_list: blogList,
};

/**
 * @param {object} section  a Section from the Site Document
 * @param {{ctaHref: Function, pad: string, index: number}} ctx
 */
const renderSection = (section, ctx) => {
  const s = { ...section, content: isObj(section.content) ? section.content : {} };
  return (RENDERERS[s.type] || prose)(s, ctx);
};

module.exports = { renderSection };
