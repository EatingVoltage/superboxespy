// The sheet view's rest pieces (src/sheetview.ts) for the layouts in a JSON file, as JSON on stdout: test_core checks
// them against the export's (python/superboxes/sheets.py). Run by the test with node --experimental-transform-types.
import { readFileSync } from "node:fs";

const { restPieces } = await import(new URL("../src/sheetview.ts", import.meta.url).href);
const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));
console.log(JSON.stringify(cases.map((c) => c.sheets.map((n) =>
  restPieces(c.parts, c.placements, c.sheet, n).map((r) => [r.name, r.x0, r.y0, r.x1, r.y1])))));
