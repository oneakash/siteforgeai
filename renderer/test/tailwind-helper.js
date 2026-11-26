"use strict";

// Compiles with Tailwind's own engine, using the project's real theme (styles/input.css).
// Used to prove that every class the renderer emits is an actual utility: Tailwind silently
// ignores unknown classes, so a typo would otherwise ship as "unstyled" with no error.

const fs = require("fs");
const path = require("path");
const { compile } = require("tailwindcss");

const root = path.dirname(require.resolve("tailwindcss/package.json"));

const loadStylesheet = async (id, base) => {
  const file = id === "tailwindcss" ? path.join(root, "index.css")
    : id.startsWith(".") ? path.resolve(base, id) : require.resolve(id);
  return { path: file, base: path.dirname(file), content: fs.readFileSync(file, "utf8") };
};

async function compiler() {
  const css = fs.readFileSync(path.join(__dirname, "..", "styles", "input.css"), "utf8");
  return compile(css, { base: __dirname, loadStylesheet });
}

/** class="a b c" attributes in rendered HTML -> unique tokens */
const classesIn = (html) =>
  [...new Set([...html.matchAll(/class="([^"]*)"/g)].flatMap((m) => m[1].split(/\s+/)).filter(Boolean))];

module.exports = { compiler, classesIn };
