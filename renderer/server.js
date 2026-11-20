const http = require("http");

const BACKEND_URL = process.env.BACKEND_URL || "http://backend:8000";

/* ------------------------------------------------------------------ *
 * Escaping helpers
 * ------------------------------------------------------------------ */

// HTML text / attribute-safe escaping.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// CSS-value-safe: strips characters that could break out of a declaration.
// The token values come from the validated Pydantic model, but defense in depth.
const cssSafe = (s) => String(s ?? "").replace(/[<>{};]/g, "");

// Match Python's urllib.parse.quote(s, safe="/") exactly.
// (encodeURIComponent additionally leaves !*'() alone and encodes / — undo both.)
const pyQuote = (s) => encodeURIComponent(String(s ?? ""))
  .replace(/%2F/gi, "/")   // restore /
  .replace(/!/g, "%21")    // encode !
  .replace(/\*/g, "%2A")   // encode *
  .replace(/'/g, "%27")    // encode '
  .replace(/\(/g, "%28")   // encode (
  .replace(/\)/g, "%29");  // encode )

/* ------------------------------------------------------------------ *
 * Content normalizers (content.items / content.fields / primary_cta
 * are typed as Any in the Pydantic model — the LLM may emit many shapes)
 * ------------------------------------------------------------------ */

const itemTitle = (it) => (it && typeof it === "object")
  ? (it.title || it.name || it.heading || "")
  : String(it || "");
const itemBody  = (it) => (it && typeof it === "object")
  ? (it.description || it.body || it.text || it.subtitle || "")
  : "";
const ctaLabel  = (cta) => (cta && typeof cta === "object")
  ? (cta.label || cta.text || "Get Started")
  : String(cta || "Get Started");

/* ------------------------------------------------------------------ *
 * Image placeholders — mirrors contracts/site.py::ImagePlaceholder.url
 * (the Python `url` is a @property, so it is NOT serialized; we rebuild it)
 * ------------------------------------------------------------------ */

const placeholderUrl = (ip) => {
  if (!ip) return "";
  const width  = ip.width  ?? 800;
  const height = ip.height ?? 400;
  const bg     = ip.bg_hex ?? "e2e8f0";
  const fg     = ip.text_hex ?? "1e293b";
  const label  = ip.label  ?? "Image";
  return `https://placehold.co/${width}x${height}/${bg}/${fg}?text=${pyQuote(label)}`;
};

/* ------------------------------------------------------------------ *
 * Design-token maps
 * ------------------------------------------------------------------ */

const radiusMap = { none: "0", sm: "4px", md: "8px", lg: "16px", full: "999px" };
const spaceMap  = { compact: "1.25rem", comfortable: "2rem", spacious: "3rem" };

/* ------------------------------------------------------------------ *
 * Section rendering
 * ------------------------------------------------------------------ */

const renderSection = (s, ctx) => {
  const { navHref, ctaHref } = ctx;
  const c = s.content || {};
  const ip = placeholderUrl(s.image_placeholder);
  const img = ip
    ? `<img src="${esc(ip)}" alt="${esc(s.image_placeholder?.label || "")}" loading="lazy" />`
    : "";
  const cta = c.primary_cta
    ? `<a class="btn" href="${esc(ctaHref(c.primary_cta))}">${esc(ctaLabel(c.primary_cta))}</a>`
    : "";
  const items = Array.isArray(c.items) ? c.items : [];

  switch (s.type) {
    case "hero":
      return `<section class="hero">${img}<h1>${esc(c.heading)}</h1><p class="sub">${esc(c.subheading || "")}</p>${cta}</section>`;

    case "features":
    case "services":
    case "team":
    case "testimonials":
    case "process_steps":
    case "catalog":
    case "pricing":
    case "faq":
      return `<section class="grid-sec"><h2>${esc(c.heading || "")}</h2><div class="grid">${
        items.map((it) =>
          `<div class="card"><h3>${esc(itemTitle(it))}</h3><p>${esc(itemBody(it))}</p></div>`
        ).join("")
      }</div></section>`;

    case "gallery": {
      const base = s.image_placeholder || {};
      return `<section class="grid-sec"><h2>${esc(c.heading || "")}</h2><div class="grid">${
        items.map((it) => {
          const itemLabel = (it && typeof it === "object" && it.label)
            || itemTitle(it) || base.label || "Image";
          const merged = { ...base, label: itemLabel };
          // Respect per-item placeholder overrides if the LLM emitted them.
          if (it && typeof it === "object") {
            if (it.width  != null) merged.width  = it.width;
            if (it.height != null) merged.height = it.height;
            if (it.bg_hex)   merged.bg_hex   = it.bg_hex;
            if (it.text_hex) merged.text_hex = it.text_hex;
          }
          const url = placeholderUrl(merged);
          const alt = itemTitle(it) || itemLabel;
          return `<div class="card"><img src="${esc(url)}" alt="${esc(alt)}" loading="lazy"/></div>`;
        }).join("")
      }</div></section>`;
    }

    case "stats":
      return `<section class="stats"><div class="grid">${
        items.map((it) =>
          `<div class="stat"><strong>${esc(itemTitle(it))}</strong><span>${esc(itemBody(it))}</span></div>`
        ).join("")
      }</div></section>`;

    case "cta_banner":
      return `<section class="banner"><h2>${esc(c.heading || "")}</h2>${cta}</section>`;

    case "contact_form": {
      const fields = Array.isArray(c.fields) ? c.fields : [];
      return `<section class="grid-sec"><h2>${esc(c.heading || "")}</h2><form class="form">${
        fields.map((f) => {
          const name = typeof f === "object" ? (f.name || f.label || "") : String(f);
          const type = (typeof f === "object" && f.type)
            ? f.type
            : (name.toLowerCase().includes("email") ? "email" : "text");
          return `<label>${esc(name)}<input type="${esc(type)}" placeholder="${esc(name)}"/></label>`;
        }).join("")
      }<button class="btn" type="button">Send</button></form></section>`;
    }

    case "map_location":
      return `<section class="grid-sec"><h2>${esc(c.heading || "")}</h2><p>${esc(c.address || "")}</p>${img}</section>`;

    case "about":
    case "rich_text":
      return `<section class="prose"><h2>${esc(c.heading || "")}</h2><p>${esc(c.body || "")}</p>${img}</section>`;

    case "blog_list":
      return `<section class="grid-sec"><h2>${esc(c.heading || "")}</h2><p>Posts coming soon.</p></section>`;

    default:
      return `<section class="prose"><h2>${esc(c.heading || "")}</h2><p>${esc(c.body || c.subheading || "")}</p>${img}</section>`;
  }
};

/* ------------------------------------------------------------------ *
 * Page rendering
 * ------------------------------------------------------------------ */

const render = (doc, page, projectId) => {
  const t = doc.tokens || {};
  const col = t.colors || {};

  // base_font_size_px is 14..20 per the model; still guard defensively.
  const rawSize = Number(t.base_font_size_px);
  const baseFontSize = (Number.isFinite(rawSize) && rawSize >= 14 && rawSize <= 20)
    ? rawSize
    : 16;

  // Href resolver scoped to this project + URL-encoded path segments.
  const pid = encodeURIComponent(projectId);
  const navHref = (slug) => {
    const parts = String(slug || "/").split("/").filter(Boolean).map(encodeURIComponent);
    return `/preview/${pid}/${parts.join("/")}`;
  };

  const hasContact = doc.pages.some((p) => p.slug === "/contact");
  const ctaHref = (cta) => {
    if (cta && typeof cta === "object" && typeof cta.href === "string" && cta.href) {
      return /^https?:\/\//i.test(cta.href) ? cta.href : navHref(cta.href);
    }
    return navHref(hasContact ? "/contact" : "/");
  };

  // Navigation — top level + children as hover dropdowns.
  const renderNavItem = (n) => {
    const label = esc(n.label);
    const href  = esc(navHref(n.slug));
    const kids  = Array.isArray(n.children) ? n.children : [];
    if (kids.length === 0) return `<a href="${href}">${label}</a>`;
    return `<span class="has-children"><a href="${href}">${label}</a><span class="children">${
      kids.map((ch) => `<a href="${esc(navHref(ch.slug))}">${esc(ch.label)}</a>`).join("")
    }</span></span>`;
  };
  const nav = (doc.navigation || []).map(renderNavItem).join("");

  // Footer links — list[Slug]; use the target page's title as label.
  const footerLinks = (doc.footer_links || []).map((slug) => {
    const target = doc.pages.find((p) => p.slug === slug);
    const label = target ? target.title : slug;
    return `<a href="${esc(navHref(slug))}">${esc(label)}</a>`;
  }).join("");

  const ctx = { navHref, ctaHref };

  return `<!doctype html><html lang="en"><head><meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>${esc(page.meta?.title || page.title)}</title>
  <meta name="description" content="${esc(page.meta?.description || "")}"/>
  <style>
    :root{
      --primary:${cssSafe(col.primary)};
      --secondary:${cssSafe(col.secondary)};
      --accent:${cssSafe(col.accent)};
      --bg:${cssSafe(col.background)};
      --surface:${cssSafe(col.surface || "#f8fafc")};
      --text:${cssSafe(col.text)};
      --fh:${cssSafe(t.heading_font)};
      --fb:${cssSafe(t.body_font)};
      --r:${radiusMap[t.radius] || "8px"};
      --sp:${spaceMap[t.spacing] || "2rem"};
    }
    *{box-sizing:border-box}
    html{font-size:${baseFontSize}px}
    body{margin:0;font-family:var(--fb);color:var(--text);background:var(--bg);line-height:1.6}
    h1,h2,h3{font-family:var(--fh);color:var(--primary);line-height:1.2}
    nav{position:sticky;top:0;background:var(--primary);padding:1rem var(--sp);display:flex;gap:1.25rem;align-items:center;z-index:10}
    nav a{color:#fff;text-decoration:none;font-family:var(--fh);font-weight:600}
    nav .brand{margin-right:auto;font-size:1.25rem}
    nav .has-children{position:relative;display:inline-block}
    nav .has-children > .children{display:none;position:absolute;top:100%;left:0;background:var(--primary);padding:.5rem 1rem;min-width:180px;box-shadow:0 4px 12px rgba(0,0,0,.2);flex-direction:column;gap:.5rem}
    nav .has-children:hover > .children{display:flex}
    section{padding:calc(var(--sp)*2) var(--sp)}
    .hero{text-align:center;background:var(--surface)}
    .hero img{max-width:100%;border-radius:var(--r);margin-bottom:var(--sp);box-shadow:0 10px 30px rgba(0,0,0,.12)}
    .hero h1{font-size:clamp(2rem,5vw,3.25rem)}
    .hero .sub{font-size:1.2rem;opacity:.8;max-width:640px;margin:0 auto var(--sp)}
    .btn{display:inline-block;background:var(--accent);color:#fff;padding:.8rem 1.6rem;border-radius:var(--r);text-decoration:none;font-weight:700;border:none;cursor:pointer}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:var(--sp);max-width:1100px;margin:0 auto}
    .grid-sec h2,.prose h2,.banner h2{text-align:center;margin-bottom:var(--sp)}
    .card{background:#fff;padding:var(--sp);border-radius:var(--r);box-shadow:0 1px 3px rgba(0,0,0,.08)}
    .card img{width:100%;border-radius:var(--r)}
    .stats{background:var(--primary);color:#fff}
    .stats .grid{color:#fff}
    .stat{text-align:center}
    .stat strong{font-size:2rem;display:block;font-family:var(--fh)}
    .banner{background:var(--surface);text-align:center}
    .form{max-width:520px;margin:0 auto;display:flex;flex-direction:column;gap:1rem}
    .form label{display:flex;flex-direction:column;gap:.35rem;font-weight:600}
    .form input{padding:.7rem;border:1px solid #cbd5e1;border-radius:var(--r);font:inherit}
    footer{background:var(--surface);padding:var(--sp);text-align:center;border-top:1px solid rgba(0,0,0,.08)}
    footer .footer-links{display:flex;justify-content:center;gap:1rem;margin-top:.5rem;flex-wrap:wrap}
    footer .footer-links a{color:var(--primary);text-decoration:none;font-weight:600}
  </style></head><body>
  <nav><span class="brand">${esc(doc.brand_name)}</span>${nav}</nav>
  <main>${(page.sections || []).map((s) => renderSection(s, ctx)).join("")}</main>
  <footer>
    <p>&copy; ${new Date().getFullYear()} ${esc(doc.brand_name)}</p>
    ${footerLinks ? `<div class="footer-links">${footerLinks}</div>` : ""}
  </footer>
  </body></html>`;
};

/* ------------------------------------------------------------------ *
 * HTTP server
 * ------------------------------------------------------------------ */

http.createServer(async (req, res) => {
  const urlPath = (req.url || "").split("?")[0]; // strip query string
  const m = urlPath.match(/^\/preview\/([^/]+)(?:\/v(\d+))?(?:\/(.*))?$/);
  if (!m) {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    return res.end("Not found");
  }

  const [, projectId, , rest] = m;
  const slug = rest && rest.length
    ? "/" + rest.replace(/^\/+|\/+$/g, "")
    : "/";

  try {
    const r = await fetch(`${BACKEND_URL}/v1/projects/${encodeURIComponent(projectId)}/site`);
    if (!r.ok) throw new Error(`backend ${r.status}`);
    const doc = await r.json();

    const page = doc.pages.find((p) => p.slug === slug);
    if (!page) {
      res.writeHead(404, { "Content-Type": "text/html; charset=utf-8" });
      return res.end(`<!doctype html><html><head><title>404</title></head><body>
        <h1>404 Not Found</h1>
        <p>No page at <code>${esc(slug)}</code>.</p>
        <p><a href="/preview/${encodeURIComponent(projectId)}/">Back to home</a></p>
      </body></html>`);
    }

    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(render(doc, page, projectId));
  } catch (e) {
    console.error("Render error:", e.message);
    res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Error rendering site");
  }
}).listen(4000, "0.0.0.0", () => console.log("renderer listening on :4000"));