"use strict";

/* ------------------------------------------------------------------ *
 * Escaping + sanitising. Everything that reaches the HTML goes through
 * one of these; section content is data, never markup.
 * ------------------------------------------------------------------ */

// HTML text / attribute-safe escaping.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Match Python's urllib.parse.quote(s, safe="/") exactly (mirrors ImagePlaceholder.url).
const pyQuote = (s) => encodeURIComponent(String(s ?? ""))
  .replace(/%2F/gi, "/")
  .replace(/!/g, "%21")
  .replace(/\*/g, "%2A")
  .replace(/'/g, "%27")
  .replace(/\(/g, "%28")
  .replace(/\)/g, "%29");

const HEX = /^#[0-9a-fA-F]{6}$/;
const hexOr = (value, fallback) => (HEX.test(String(value ?? "")) ? String(value) : fallback);

// A font family name as a quoted CSS string; anything unusual is dropped.
const fontName = (value, fallback) => {
  const name = String(value ?? "").replace(/[^\w \-]/g, "").replace(/\s+/g, " ").trim().slice(0, 60);
  return `'${name || fallback}'`;
};

/* WCAG relative luminance, used to pick a readable text colour on top of a brand colour. */
const channel = (v) => {
  const c = v / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const luminance = (hex) => {
  const h = hex.slice(1);
  const [r, g, b] = [0, 2, 4].map((i) => channel(parseInt(h.slice(i, i + 2), 16)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
const onColor = (bg) => (contrast(bg, "#ffffff") >= contrast(bg, "#0f172a") ? "#ffffff" : "#0f172a");

/* ------------------------------------------------------------------ *
 * Content normalizers. Section content is a free-form dict; new output
 * follows contracts/section_rules.py, but older documents (and hand
 * edits) may use the legacy shapes, so every accessor takes both.
 * ------------------------------------------------------------------ */

const str = (v) => (typeof v === "string" ? v : v == null ? "" : String(v));
const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

const pick = (it, ...keys) => {
  if (!isObj(it)) return "";
  for (const k of keys) if (it[k] != null && it[k] !== "") return str(it[k]);
  return "";
};

const itemTitle = (it) => (isObj(it) ? pick(it, "title", "name", "heading", "question") : str(it));
const itemBody = (it) => pick(it, "description", "body", "text", "subtitle", "answer");
const ctaLabel = (cta) => (isObj(cta) ? pick(cta, "label", "text") || "Get Started" : str(cta) || "Get Started");

// "para one\n\npara two" -> ["para one", "para two"]
const paragraphs = (text) => str(text).split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);

/* ------------------------------------------------------------------ *
 * Image placeholders - mirrors contracts/site.py::ImagePlaceholder.url
 * (the Python `url` is a @property, so it is NOT serialised; rebuild it).
 * ------------------------------------------------------------------ */

const hex6 = (v, fallback) => (/^[0-9a-fA-F]{6}$/.test(String(v ?? "")) ? String(v) : fallback);
const dim = (v, fallback) => (Number.isInteger(v) && v >= 100 && v <= 1920 ? v : fallback);

const placeholderUrl = (ip) => {
  if (!ip) return "";
  const width = dim(ip.width, 800);
  const height = dim(ip.height, 400);
  return `https://placehold.co/${width}x${height}/${hex6(ip.bg_hex, "e2e8f0")}/${hex6(ip.text_hex, "1e293b")}?text=${pyQuote(ip.label ?? "Image")}`;
};

module.exports = {
  esc, pyQuote, hexOr, fontName, onColor, contrast,
  str, isObj, pick, itemTitle, itemBody, ctaLabel, paragraphs, placeholderUrl,
};
