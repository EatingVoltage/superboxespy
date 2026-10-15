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
  material: { key: string; thickness: number; fit: Fit; burn: number; burn_x?: number; burn_y?: number };
  sheet: Sheet;
  layout: Placement[] | null;  // the hand-arranged layout, null = packed automatically
  options: Options;
  notes: string;
  saved: string;
}

export interface OutFile { name: string; kind: "lbrn2" | "svg"; content: string; minutes?: Record<string, number>; offcut?: number }
