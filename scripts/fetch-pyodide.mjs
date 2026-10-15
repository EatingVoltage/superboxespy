// One-time setup: copies the Pyodide runtime out of node_modules and downloads the few Python packages the
// app needs into public/pyodide/, so the app runs offline afterwards. Every download is checked against the
// sha256 in pyodide-lock.json.
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const SRC = "node_modules/pyodide";
const DST = "public/pyodide";
const NEEDED = ["numpy", "shapely", "affine", "typing-extensions"];

const lock = JSON.parse(readFileSync(join(SRC, "pyodide-lock.json"), "utf8"));
const version = JSON.parse(readFileSync(join(SRC, "package.json"), "utf8")).version;
const CDN = `https://cdn.jsdelivr.net/pyodide/v${version}/full/`;

mkdirSync(DST, { recursive: true });
for (const f of ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]) {
  copyFileSync(join(SRC, f), join(DST, f));
}

const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");
for (const name of NEEDED) {
  const pkg = lock.packages[name];
  if (!pkg) throw new Error(`${name} is not in pyodide-lock.json`);
  const out = join(DST, pkg.file_name);
  if (existsSync(out) && sha256(readFileSync(out)) === pkg.sha256) {
    console.log(`ok     ${pkg.file_name}`);
    continue;
  }
  const res = await fetch(CDN + pkg.file_name);
  if (!res.ok) throw new Error(`${res.status} ${CDN + pkg.file_name}`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (sha256(buf) !== pkg.sha256) throw new Error(`sha256 mismatch: ${pkg.file_name}`);
  writeFileSync(out, buf);
  console.log(`fetched ${pkg.file_name} (${(buf.length / 1e6).toFixed(1)} MB)`);
}
console.log(`Pyodide ${version} ready in ${DST}`);
