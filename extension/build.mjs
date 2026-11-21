// The whole build. Three entry points, no config file, no plugin.
//
// bundle: true and format "iife" for the content script -- Chrome will not
// load an ES module as an injected script, and an unbundled import would
// resolve against the PORTAL's origin, not ours.
import { build } from "esbuild";
import { cp, mkdir, rm, writeFile } from "node:fs/promises";

// --test writes dist-test with test-only hooks and attributes on; dist never has them.
const test = process.argv.includes("--test");
const out = test ? "dist-test" : "dist";
await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });

await build({
  entryPoints: {
    service_worker: "src/service_worker.ts",
    content: "src/content/index.ts",
    panel: "src/panel/panel.ts",
  },
  outdir: out,
  define: { __ELMIFY_TEST__: String(test) },
  bundle: true,
  treeShaking: false,
  minifySyntax: true, // drops the `if (false)` of __ELMIFY_TEST__ so test hooks never ship
  format: "iife",
  target: "chrome120",
  sourcemap: false,
  legalComments: "none",
});

await cp("manifest.json", `${out}/manifest.json`);
await cp("src/panel/panel.html", `${out}/panel.html`);
await cp("icons", `${out}/icons`, { recursive: true });

// The four-language wording sheet's source (plan 6): every panel string and
// every mark label, from the same modules the bundles are built from, so the
// sheet cannot drift from what ships.
const catalogue = await build({
  stdin: {
    contents:
      'export { STRINGS } from "./src/panel/i18n.ts";\n' +
      'export { MARK_LABELS } from "./src/content/labels.ts";',
    resolveDir: ".",
    loader: "ts",
  },
  bundle: true,
  write: false,
  format: "esm",
  platform: "neutral",
});
const source = Buffer.from(catalogue.outputFiles[0].text).toString("base64");
const { STRINGS, MARK_LABELS } = await import(`data:text/javascript;base64,${source}`);
const sheet = {};
for (const lang of Object.keys(STRINGS)) {
  sheet[lang] = { ...STRINGS[lang] };
  for (const [key, text] of Object.entries(MARK_LABELS[lang])) sheet[lang][`mark_${key}`] = text;
}
await writeFile(`${out}/i18n.json`, JSON.stringify(sheet, null, 2));
