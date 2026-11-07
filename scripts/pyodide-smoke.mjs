// Runs the Python side inside Pyodide under Node - the same runtime and packages the browser uses.
//   npm run pack && node scripts/pyodide-smoke.mjs
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "../public/pyodide/pyodide.mjs";

const short = (e) => String(e?.message ?? e).slice(-2500);

try {
  const t0 = Date.now();
  const indexURL = fileURLToPath(new URL("../public/pyodide/", import.meta.url));
  const py = await loadPyodide({ indexURL });
  await py.loadPackage(["numpy", "shapely", "affine", "typing-extensions", "fonttools"], { messageCallback: () => {} });
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

  // the stamp case: the house logo as the page would put it (only if it's on this PC), a real case if there is one,
  // and a 16-stamp case; warm builds against the 300 ms target (stamp-case-merge.md)
  const logo = "C:/Projects/eating voltage Fonts/logos/slogo_30mm_lite.svg";
  if (existsSync(logo)) {
    py.FS.mkdirTree("/logos");
    py.FS.writeFile("/logos/slogo_30mm_lite.svg", readFileSync(logo));
  }
  const scMat = { key: "poplar3.6", thickness: 3.7, kerf_x: 0.33, kerf_y: 0.26 };
  const sixteen = { project: "SIXTEEN", pockets: Array.from({ length: 16 }, (_, i) => ({ name: `Stamp ${i + 1}`, w: 30 + (i % 4) * 8, h: 40 + (i % 3) * 10 })) };
  const packed = timed("stamp case repack 16", "stampcase_op", { generator: "StampCase", params: sixteen, material: scMat, op: "repack" });
  const cases = [["16 stamps", packed.params]];
  const elements = "C:/Projects/ELEMENTS SYNTH/hw/packaging/ELEMENTS REV.C PACKAGING.stampcase";
  if (existsSync(elements)) cases.unshift(["ELEMENTS (9)", JSON.parse(readFileSync(elements, "utf8"))]);
  for (const [label, params] of cases) {
    const r = { generator: "StampCase", params, material: scMat };
    const first = timed(`stamp case build ${label} (cold)`, "build", r);
    console.log("  ", first.parts?.map((p) => p.name).join(", "), "| problems", first.stampcase?.problems.length,
                "| sheets", first.sheets?.length, "| logo", first.stampcase?.logos.length ? "yes" : "none");
    const ms = [];
    for (let k = 0; k < 3; k++) {
      const t = Date.now();
      call("build", r);
      ms.push(Date.now() - t);
    }
    console.log(`   warm builds: ${ms.join(", ")} ms`);
    timed(`stamp case export ${label}`, "export", { ...r, layout: first.placements, name: label });
  }
} catch (e) {
  console.log("ERROR:", short(e));
  process.exitCode = 1;
}
