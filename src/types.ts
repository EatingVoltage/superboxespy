// Shapes of what Python sends back (superboxes.api) and of the files this app saves.

export type Pt = [number, number];
export type Seg = [number, number] | [number, number, number, number, number, number]; // line end | c1 c2 end

export interface Subpath { start: Pt; segs: Seg[]; closed: boolean }
export interface ShapePoly { outer: Pt[]; holes: Pt[][] }
export interface Wall { x: number; y: number; edges: string; label: string; frame: number[] }

export interface PartJ {
  index: number;
  name: string;
  w: number;
  h: number;
  paths: Record<string, Subpath[]>;       // "2" = CUT, "1" = LINE, "30" = T1
  labels: { text: string; x: number; y: number; size: number; align: string }[];
  shape: ShapePoly[] | null;
  children?: ShapePoly[][];
  area: number;
  walls: Wall[];
  deco: { layer: number; lines: Pt[][] }[];
}

export interface Placement { part: number; sheet: number; x: number; y: number; rot: number }

export interface Build {
  ok: boolean;
  error?: string;
  title: string;
  parts: PartJ[];
  placements: Placement[];
  too_big: number[];
  sheets: { index: number; offcut: number }[];
  warnings: string[];
  info: { cli: string; thickness: number; burn: number; layout?: string };
  boxes_version: string;
  mark: string;
  notes?: string;
  assembly?: unknown;
  stampcase?: StampData;       // StampCase only: what the board editor draws and hit-tests
}

// ------------------------------------------------------------------ the stamp case (python/superboxes/stampcase)
export type Side = "left" | "right" | "bottom" | "top";
export interface Pocket {
  name: string; w: number; h: number; x: number; y: number;      // stamp size as placed, air not included
  notch_side: Side; notch_end: "low" | "high"; label_pos: "notch" | "side" | "end"; id: string;
  thickness?: number;                                            // optional stamp thickness, 0 = not given
}
export interface Block { x: number; y: number; size: number; rot: number; placed: boolean }
export type BlockKey = "top_block" | "lid_title" | "lid_logo";
/** A stamp case: the .box.json's params for generator "StampCase" (model.Case). */
export interface Case {
  project: string; pocket_boards: number; air: number; logo: string;
  pockets: Pocket[]; magnets: [number, number][]; magnets_auto: boolean;
  top_block: Block; lid_title: Block; lid_logo: Block;
}
export interface Problem { level: "error" | "warning"; text: string; refs: string[] }
export interface StampData {
  rect: [number, number, number, number];
  origin: [number, number];                 // design = part coordinates + origin
  boards: { key: string; title: string; part: number }[];
  top_key: string;
  pockets: { id: string; hole: ShapePoly[]; rect: [number, number, number, number]; label_box: ShapePoly[] | null;
             label_fits: boolean; lid_band: ShapePoly[] | null }[];
  magnets: [number, number][];
  magnet_r: number;
  blocks: Record<BlockKey, { region: ShapePoly[] | null; x: number; y: number; size: number; rot: number; placed: boolean }>;
  problems: Problem[];
  size: [number, number];
  max_board: [number, number];
  per_sheet: number;
  sheets: number | null;
  hint: [number, string, number] | null;    // (mm smaller, "narrower" | "shorter", sheets then)
  depth: number;
  logos: string[];
  snap: number; air: number; web: number; magnet_wood: number;
}

export interface Param {
  name: string;
  kind: "float" | "int" | "bool" | "choice" | "edge" | "sections" | "ints" | "text";
  default: any;
  help: string;
  min?: number;
  max?: number;
  step?: number;
  choices?: string[];
  labels?: Record<string, string>;
}
export interface Group { title: string; advanced: boolean; params: Param[] }

export interface Sheet { name: string; w: number; h: number; usable: number }
export const A3: Sheet = { name: "A3", w: 297, h: 420, usable: 390 };

export type Fit = "press" | "glue";

// What a material is right now on this machine: thickness and fits measured with calipers.
export interface MaterialProfile {
  key: string;                 // evlaser machine.MATERIALS key - decides the LightBurn layer values
  label: string;
  thickness: number;
  thicknessMeasured: boolean;
  kerfX: number | null;        // mm, from the 00a strips
  kerfY: number | null;
  fitPress: number | null;     // winners from the 00b comb, as offsets on top of kerf / 2
  fitGlue: number | null;
  measuredOn: string | null;   // ISO date of the last calibration entry
}

export interface Options {
  labels_engrave: boolean;
  mark: { enabled: boolean; text: string | null; part: number | null };
}

// A saved box (.box.json). Every parameter is stored, not only the changed ones, so a later boxes.py with other
// defaults still makes the same box.
export interface BoxConfig {
  app: "superboxespy";
  version: 1;
  name: string;
  generator: string;
  boxes_version: string;
  params: Record<string, any>;
  material: { key: string; thickness: number; fit: Fit; burn: number; burn_x?: number; burn_y?: number;
              kerf_x?: number; kerf_y?: number };   // kerf: what a stamp case is cut with (kerf / 2, no fit)
  sheet: Sheet;
  layout: Placement[] | null;  // the hand-arranged layout, null = packed automatically
  options: Options;
  notes: string;
  saved: string;
}

export interface OutFile { name: string; kind: "lbrn2" | "svg"; content: string; minutes?: Record<string, number>; offcut?: number }
/** export / calibration_export: ONE .lbrn2 project (a page per sheet), one .svg per sheet, the numbers per sheet. */
export interface ExportResult {
  ok: boolean;
  error?: string;
  files: OutFile[];
  sheets: { minutes: Record<string, number>; offcut: number }[];
  kept: boolean;               // layer settings carried over from a LightBurn-saved version of the project
}
