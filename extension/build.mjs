// The whole build. Three entry points, no config file, no plugin.
//
// bundle: true and format "iife" for the content script -- Chrome will not
// load an ES module as an injected script, and an unbundled import would
// resolve against the PORTAL's origin, not ours.
import { build } from "esbuild";
import { cp, mkdir, rm } from "node:fs/promises";

await rm("dist", { recursive: true, force: true });
await mkdir("dist", { recursive: true });

await build({
  entryPoints: {
    service_worker: "src/service_worker.ts",
    content: "src/content/index.ts",
    panel: "src/panel/panel.ts",
  },
  outdir: "dist",
  bundle: true,
  treeShaking: false,
  format: "iife",
  target: "chrome120",
  sourcemap: false,
  legalComments: "none",
});

await cp("manifest.json", "dist/manifest.json");
await cp("src/panel/panel.html", "dist/panel.html");
await cp("icons", "dist/icons", { recursive: true });
