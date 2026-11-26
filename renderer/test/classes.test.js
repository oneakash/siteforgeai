"use strict";

const test = require("node:test");
const assert = require("node:assert");
const { site, LIGHT } = require("./fixtures");
const { renderPage } = require("../lib/page");
const { compiler, classesIn } = require("./tailwind-helper");

// Markers that Tailwind reads but that deliberately generate no CSS of their own.
const NO_CSS = new Set(["group"]);

test("every class the renderer emits is a real Tailwind utility (typos ship as silent no-ops)", async () => {
  // every spacing token, so the per-token class variants are covered too
  const html = ["compact", "comfortable", "spacious"].flatMap((spacing) => {
    const doc = site(LIGHT, { spacing });
    return doc.pages.map((p) => renderPage(doc, p, "p1"));
  }).join("\n");
  const { build } = await compiler();

  const unknown = classesIn(html).filter((c) => !NO_CSS.has(c) && !build([c]).includes(c.replace(/[:/[\]&>.()#%]/g, (ch) => "\\" + ch)));
  assert.deepStrictEqual(unknown, []);
});

test("brand tokens resolve to theme utilities backed by the --site-* variables", async () => {
  const { build } = await compiler();
  const css = build(["bg-primary", "text-on-accent", "font-heading", "rounded-site", "ring-ink/10", "bg-canvas"]);
  for (const v of ["--site-primary", "--site-on-accent", "--site-font-heading", "--site-radius", "--site-text", "--site-bg"]) {
    assert.ok(css.includes(v), `${v} missing from compiled CSS`);
  }
});
