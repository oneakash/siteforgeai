"use strict";

const http = require("http");
const fs = require("fs/promises");
const path = require("path");
const crypto = require("crypto");

const { esc } = require("./lib/util");
const { renderPage } = require("./lib/page");

const PORT = Number(process.env.PORT || 4000);
const BACKEND_URL = process.env.BACKEND_URL || "http://backend:8000";
const FETCH_TIMEOUT_MS = Number(process.env.BACKEND_TIMEOUT_MS || 10_000);
const PROD = process.env.NODE_ENV === "production";
// Origins allowed to embed the preview in an <iframe> (comma separated).
const FRAME_ANCESTORS = (process.env.FRONTEND_ORIGIN || "http://localhost:3000").split(",").map((s) => s.trim()).join(" ");
const CSS_PATH = path.join(__dirname, "public", "tailwind.css");

/* ------------------------------------------------------------------ *
 * Backend access
 * ------------------------------------------------------------------ */

class NotFound extends Error {}

async function fetchSite(projectId) {
  const r = await fetch(`${BACKEND_URL}/v1/projects/${encodeURIComponent(projectId)}/site`, {
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (r.status === 404) throw new NotFound("site not generated yet");
  if (!r.ok) throw new Error(`backend responded ${r.status}`);
  return r.json();
}

/* ------------------------------------------------------------------ *
 * Compiled Tailwind stylesheet (public/tailwind.css, built by `npm run build:css`)
 * ------------------------------------------------------------------ */

let cssCache = { mtime: 0, body: null, version: "" };

async function loadCss() {
  const st = await fs.stat(CSS_PATH); // throws ENOENT when the build step was skipped
  if (st.mtimeMs !== cssCache.mtime) {
    const body = await fs.readFile(CSS_PATH);
    cssCache = { mtime: st.mtimeMs, body, version: crypto.createHash("sha1").update(body).digest("hex").slice(0, 10) };
  }
  return cssCache;
}

/* ------------------------------------------------------------------ *
 * Responses
 * ------------------------------------------------------------------ */

const text = (res, status, body, type = "text/plain; charset=utf-8", headers = {}) => {
  res.writeHead(status, { "Content-Type": type, "X-Content-Type-Options": "nosniff", ...headers });
  res.end(body);
};

// Previews contain no script. Styles: the compiled sheet + one nonce'd token block. Images: placehold.co.
const previewHeaders = (nonce) => ({
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Content-Security-Policy": [
    "default-src 'none'",
    `style-src 'self' 'nonce-${nonce}'`,
    "img-src https://placehold.co data:",
    "base-uri 'none'",
    "form-action 'none'",
    `frame-ancestors ${FRAME_ANCESTORS}`,
  ].join("; "),
});

const errorPage = (res, status, title, message, nonce) => text(
  res, status,
  `<!doctype html><html lang="en"><head><meta charset="utf-8"/><title>${esc(title)}</title></head>` +
  `<body style="font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem">` +
  `<h1>${esc(title)}</h1><p>${message}</p></body></html>`,
  "text/html; charset=utf-8",
  { ...previewHeaders(nonce), "Content-Security-Policy": `default-src 'none'; style-src 'unsafe-inline'; frame-ancestors ${FRAME_ANCESTORS}` },
);

/* ------------------------------------------------------------------ *
 * App
 * ------------------------------------------------------------------ */

/**
 * @param {{getSite?: (projectId: string) => Promise<object>}} [deps]  injectable for tests
 */
function createServer({ getSite = fetchSite } = {}) {
  return http.createServer(async (req, res) => {
    const urlPath = (req.url || "").split("?")[0];

    if (req.method !== "GET" && req.method !== "HEAD") return text(res, 405, "Method not allowed", undefined, { Allow: "GET, HEAD" });
    if (urlPath === "/healthz") return text(res, 200, "ok");

    if (urlPath === "/assets/tailwind.css") {
      try {
        const css = await loadCss();
        const immutable = PROD && (req.url || "").includes("?v=");
        return text(res, 200, css.body, "text/css; charset=utf-8", {
          "Cache-Control": immutable ? "public, max-age=31536000, immutable" : "no-cache",
        });
      } catch {
        return text(res, 503, "Stylesheet not built. Run: npm run build:css");
      }
    }

    const m = urlPath.match(/^\/preview\/([^/]+)(?:\/v(\d+))?(?:\/(.*))?$/);
    if (!m) return text(res, 404, "Not found");

    const nonce = crypto.randomBytes(16).toString("base64");
    const [, rawId, , rest] = m;
    let projectId;
    try { projectId = decodeURIComponent(rawId); } catch { return text(res, 400, "Bad request"); }
    const slug = rest && rest.length ? "/" + rest.replace(/^\/+|\/+$/g, "") : "/";

    try {
      const css = await loadCss().catch(() => null);
      if (!css) return errorPage(res, 503, "Renderer not ready", "The Tailwind stylesheet has not been built. Run <code>npm run build:css</code>.", nonce);

      const doc = await getSite(projectId);
      const page = doc.pages.find((p) => p.slug === slug);
      if (!page) {
        return errorPage(res, 404, "404 Not Found", `No page at <code>${esc(slug)}</code>. <a href="/preview/${esc(encodeURIComponent(projectId))}/">Back to home</a>`, nonce);
      }
      return text(res, 200, renderPage(doc, page, projectId, { nonce, cssVersion: css.version }),
        "text/html; charset=utf-8", previewHeaders(nonce));
    } catch (e) {
      if (e instanceof NotFound) {
        return errorPage(res, 404, "No site yet", "This project has no generated site yet. It will appear here when generation finishes.", nonce);
      }
      console.error("Render error:", e.message);
      return errorPage(res, 502, "Preview unavailable", "The renderer could not load this site. Try again in a moment.", nonce);
    }
  });
}

module.exports = { createServer, NotFound };

if (require.main === module) {
  const server = createServer();
  server.listen(PORT, "0.0.0.0", () => console.log(`renderer listening on :${PORT} (backend: ${BACKEND_URL})`));
  loadCss().catch(() => console.warn("WARNING: public/tailwind.css is missing. Run `npm run build:css` (previews will return 503)."));
  const stop = () => server.close(() => process.exit(0));
  process.on("SIGTERM", stop);
  process.on("SIGINT", stop);
}
