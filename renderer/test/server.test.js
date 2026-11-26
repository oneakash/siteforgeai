"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const { site } = require("./fixtures");

// The server serves public/tailwind.css (a build artifact). Provide a stand-in if it isn't built.
const cssPath = path.join(__dirname, "..", "public", "tailwind.css");
const hadCss = fs.existsSync(cssPath);
if (!hadCss) {
  fs.mkdirSync(path.dirname(cssPath), { recursive: true });
  fs.writeFileSync(cssPath, "/* test stand-in */");
}
test.after(() => { if (!hadCss) fs.rmSync(cssPath); });

const { createServer } = require("../server");

async function withServer(getSite, fn) {
  const server = createServer({ getSite });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  try { await fn(`http://127.0.0.1:${server.address().port}`); } finally { await new Promise((r) => server.close(r)); }
}

test("serves a styled page with a strict CSP that allows only the nonce'd token block", async () => {
  await withServer(async () => site(), async (base) => {
    const r = await fetch(`${base}/preview/p1/v3`);
    assert.strictEqual(r.status, 200);
    const csp = r.headers.get("content-security-policy");
    const html = await r.text();
    const nonce = html.match(/<style nonce="([^"]+)"/)[1];
    assert.ok(csp.includes(`style-src 'self' 'nonce-${nonce}'`));
    assert.ok(csp.includes("default-src 'none'") && csp.includes("form-action 'none'"));
    assert.ok(csp.includes("frame-ancestors http://localhost:3000"));
    assert.strictEqual(r.headers.get("cache-control"), "no-store");
    assert.match(html, /data-section-id="home-hero"/);
  });
});

test("subpages, unknown pages, and health", async () => {
  await withServer(async () => site(), async (base) => {
    assert.strictEqual((await fetch(`${base}/preview/p1/contact`)).status, 200);
    assert.strictEqual((await fetch(`${base}/preview/p1/nope`)).status, 404);
    assert.strictEqual((await fetch(`${base}/healthz`)).status, 200);
    assert.strictEqual((await fetch(`${base}/other`)).status, 404);
    assert.strictEqual((await fetch(`${base}/preview/p1`, { method: "POST" })).status, 405);
  });
});

test("the stylesheet is served with its content version", async () => {
  await withServer(async () => site(), async (base) => {
    const r = await fetch(`${base}/assets/tailwind.css`);
    assert.strictEqual(r.status, 200);
    assert.match(r.headers.get("content-type"), /text\/css/);
  });
});

test("backend states map to honest statuses: no site yet -> 404 page, backend down -> 502", async () => {
  const { NotFound } = require("../server");
  const err = console.error; console.error = () => {};
  try {
    await withServer(async () => { throw new NotFound("none"); }, async (base) => {
      const r = await fetch(`${base}/preview/p1`);
      assert.strictEqual(r.status, 404);
      assert.match(await r.text(), /No site yet/);
    });
    await withServer(async () => { throw new Error("connect ECONNREFUSED"); }, async (base) => {
      const r = await fetch(`${base}/preview/p1`);
      assert.strictEqual(r.status, 502);
      assert.ok(!(await r.text()).includes("ECONNREFUSED"), "internal errors are not leaked");
    });
  } finally { console.error = err; }
});
