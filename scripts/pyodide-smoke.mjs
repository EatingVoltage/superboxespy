// Runs the Python side inside Pyodide under Node - the same runtime and packages the browser uses.
//   npm run pack && node scripts/pyodide-smoke.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "../public/pyodide/pyodide.mjs";

const short = (e) => String(e?.message ?? e).slice(-2500);

try {
  const t0 = Date.now();
  const indexURL = fileURLToPath(new URL("../public/pyodide/", import.meta.url));
  const py = await loadPyodide({ indexURL });
  await py.loadPackage(["numpy", "shapely", "affine", "typing-extensions"], { messageCallback: () => {} });
  const zip = readFileSync(fileURLToPath(new URL("../public/py.zip", import.meta.url)));
  py.unpackArchive(zip.buffer.slice(zip.byteOffset, zip.byteOffset + zip.byteLength), "zip", { extractDir: "/app" });
  py.runPython("import sys; sys.path.insert(0, '/app')");
  console.log(`runtime ready in ${Date.now() - t0} ms`);

  const call = (fn, req) => {
    py.globals.set("_fn", fn);
    py.globals.set("_req", JSON.stringify(req));
    return JSON.parse(py.runPython("from superboxes import api\napi.call(_fn, _req)"));
  };
  const timed = (label, fn, req) => {
    const t = Date.now();
    const r = call(fn, req);
    console.log(label, r.ok ? "ok" : "FAILED " + r.error + "\n" + (r.trace ?? ""), `${Date.now() - t} ms`);
    return r;
  };

  const cat = timed("catalog", "catalog", {});
  console.log("  ", cat.generators?.map((g) => g.name).join(", "), "| boxes", cat.boxes_version);
  timed("schema TypeTray", "schema", { generator: "TypeTray" });
  const req = { generator: "ABox", params: { x: 50, y: 50, h: 50, outside: true },
                material: { key: "poplar3.6", thickness: 3.6, burn: 0.1 } };
  const b = timed("build ABox 50", "build", req);
  console.log("  ", b.parts?.length, "parts", JSON.stringify(b.sheets), "mark", b.mark);
  const e = timed("export ABox 50", "export", { ...req, layout: b.placements });
  console.log("  ", e.files?.map((f) => `${f.name} (${f.content.length} chars)`).join(", "));
  timed("build Console2", "build", { ...req, generator: "Console2", params: {} });
  timed("kerf sheet", "kerf_sheet", { material: req.material });
  timed("comb sheet", "comb_sheet", { material: req.material });
  timed("comb export", "calibration_export", { which: "comb", material: req.material });
} catch (e) {
  console.log("ERROR:", short(e));
  process.exitCode = 1;
}
