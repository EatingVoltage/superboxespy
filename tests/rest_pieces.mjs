// The sheet view's rest pieces (src/sheetview.ts) for the layouts in a JSON file, as JSON on stdout: test_core checks
// them against the export's (python/superboxes/sheets.py). sheetview.ts is bundled first, as Vite bundles the app:
// the app's imports leave out the extension (`./ui`), which Node's own loader can't resolve.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { build } from "rolldown";

const out = await build({ input: fileURLToPath(new URL("../src/sheetview.ts", import.meta.url)), platform: "node",
                          write: false, output: { format: "esm" } });
const { restPieces } = await import("data:text/javascript;base64," + Buffer.from(out.output[0].code).toString("base64"));
const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));
console.log(JSON.stringify(cases.map((c) => c.sheets.map((n) =>
  restPieces(c.parts, c.placements, c.sheet, n).map((r) => [r.name, r.x0, r.y0, r.x1, r.y1])))));
