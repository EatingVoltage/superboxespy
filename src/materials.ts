// Material profiles: thickness, kerf and the two fit winners per material, kept in this browser (and in
// materials.json in the picked folder, and inside every saved box).
//
// The burn a box uses = base + fit offset:
//   base = kerf / 2 (measured on the 00a strips; per axis when X and Y differ), or boxes.py's 0.10 unmeasured
//   fit  = the press-fit or glue-fit winner from the 00b comb (0 until tested)
// With different X and Y kerf, Python compensates per machine axis (python/superboxes/kerf.py).

import type { Fit, MaterialProfile } from "./types";

const KEY = "superboxespy.materials.v1";
export const DEFAULT_BURN = 0.1;   // boxes.py's default; never measured on this machine
export const AXIS_THRESHOLD = 0.001; // kerf X and Y further apart than this -> per-axis compensation

const DEFAULTS: Record<string, MaterialProfile> = {
  "poplar3.6": {
    // the key stays "poplar3.6" (saved boxes refer to it); the sheets measure 3.7 (2026-10-11)
    key: "poplar3.6", label: "Poplar ply 3.7 mm (sold as 4 mm)", thickness: 3.7, thicknessMeasured: true,
    // measured 2026-10-11 (00a: 96.7 / 97.4 mm over 10 bars; 00b: press fit +0.02, 90° row confirmed) - also in
    // the eVlaser skill's fits table. A value entered in the Calibration tab overrides these.
    kerfX: 0.33, kerfY: 0.26, fitPress: 0.02, fitGlue: null, measuredOn: "2026-10-11",
  },
};

const MEASURED = ["kerfX", "kerfY", "fitPress", "fitGlue", "measuredOn"] as const;

/** Fill what a stored profile hasn't measured (null) from the built-in measured values; never overwrite. */
function withDefaults(key: string, v: MaterialProfile): MaterialProfile {
  const d = DEFAULTS[key];
  const out = { ...d, ...v };
  if (d) for (const f of MEASURED) if (v[f] == null) (out as any)[f] = d[f];
  return out;
}

function migrate(p: MaterialProfile & { burnPress?: number | null; burnGlue?: number | null }): MaterialProfile {
  // before fit offsets existed, winners were stored as absolute burns
  const base = baseBurn(p);
  const out = { ...p };
  if (out.fitPress == null && p.burnPress != null) out.fitPress = round4(p.burnPress - (base.x + base.y) / 2);
  if (out.fitGlue == null && p.burnGlue != null) out.fitGlue = round4(p.burnGlue - (base.x + base.y) / 2);
  delete (out as any).burnPress;
  delete (out as any).burnGlue;
  return out;
}

const REV = "superboxespy.materials.rev";

function load(): Record<string, MaterialProfile> {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const stored = JSON.parse(raw) as Record<string, MaterialProfile>;
      // rev 2: the poplar default went from 3.6 to 3.7 mm; a stored 3.6 is the old default (the calibration
      // form came prefilled with it), not a measurement, and the label was the old one
      if (localStorage.getItem(REV) !== "2") {
        const pop = stored["poplar3.6"];
        if (pop && pop.thickness === 3.6) Object.assign(pop, { thickness: 3.7 });
        if (pop) pop.label = DEFAULTS["poplar3.6"].label;
        localStorage.setItem(KEY, JSON.stringify(stored));
        localStorage.setItem(REV, "2");
      }
      const out = { ...DEFAULTS };
      for (const [k, v] of Object.entries(stored)) out[k] = migrate(withDefaults(k, v));
      return out;
    }
    localStorage.setItem(REV, "2");
  } catch {
    /* private window or blocked storage: defaults */
  }
  return { ...DEFAULTS };
}

let profiles = load();
const listeners: (() => void)[] = [];

const round4 = (v: number) => Math.round(v * 10000) / 10000;

export function all(): MaterialProfile[] {
  return Object.values(profiles);
}

export function get(key: string): MaterialProfile {
  return profiles[key] ?? profiles["poplar3.6"];
}

export function update(key: string, patch: Partial<MaterialProfile>) {
  profiles = { ...profiles, [key]: migrate({ ...get(key), ...patch }) };
  try {
    localStorage.setItem(KEY, JSON.stringify(profiles));
  } catch {
    /* not persisted here; materials.json and every saved box still carry it */
  }
  listeners.forEach((f) => f());
}

export function onChange(f: () => void) {
  listeners.push(f);
}

export function kerf(p: MaterialProfile): number | null {
  if (p.kerfX == null && p.kerfY == null) return null;
  if (p.kerfX == null) return p.kerfY;
  if (p.kerfY == null) return p.kerfX;
  return (p.kerfX + p.kerfY) / 2;
}

export function anisotropy(p: MaterialProfile): number | null {
  return p.kerfX != null && p.kerfY != null ? Math.abs(p.kerfX - p.kerfY) : null;
}

export function perAxis(p: MaterialProfile): boolean {
  const a = anisotropy(p);
  return a != null && a >= AXIS_THRESHOLD;
}

/** Burn without the fit offset, per axis: kerf / 2, or the unmeasured default. */
export function baseBurn(p: MaterialProfile): { x: number; y: number; measured: boolean } {
  if (perAxis(p)) return { x: p.kerfX! / 2, y: p.kerfY! / 2, measured: true };
  const k = kerf(p);
  return k != null ? { x: k / 2, y: k / 2, measured: true } : { x: DEFAULT_BURN, y: DEFAULT_BURN, measured: false };
}

export interface Comp {
  burn: number;               // one value (the mean, when per axis) - what boxes.py gets in isotropic mode
  bx: number;
  by: number;
  perAxis: boolean;
  delta: number;
  status: "measured" | "kerf" | "default";
}

/** What a box is cut with for this fit. */
export function compensation(p: MaterialProfile, fit: Fit): Comp {
  const base = baseBurn(p);
  const won = fit === "press" ? p.fitPress : p.fitGlue;
  const delta = won ?? 0;
  const bx = round4(base.x + delta);
  const by = round4(base.y + delta);
  return {
    burn: round4((bx + by) / 2), bx, by, perAxis: perAxis(p), delta,
    status: won != null ? "measured" : base.measured ? "kerf" : "default",
  };
}
