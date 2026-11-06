// Modèle en cours d'édition : lignes du tableau de fils, validation, conversion vers l'API.
// Aucun calcul électromagnétique ici : uniquement de la mise en forme et des contrôles de saisie.
//
// Symboles (jalon 6) : une case de fil peut contenir une formule (« -L/2 »). Elle est calculée
// par onec, via /validate, qui renvoie les fils en nombres : c'est ce « modèle résolu » qu'affichent
// la vue 3D et la colonne des longueurs. Aucune formule n'est évaluée dans le navigateur.
//
// Numérotation NEC : plusieurs lignes peuvent partager un tag (un arc importé devient une suite
// de petits fils de même tag). Leurs segments sont alors numérotés à la suite, de 1 au total,
// dans l'ordre du tableau ; l'alimentation est désignée par (tag, segment) dans ce sens.

import type {
  ExtraCard,
  GeometryIn,
  GroundIn,
  GroundKind,
  ImportOut,
  ModelIn,
  Preset,
  Value,
  Vec3,
  Wire,
} from '../api/client';

/** Case d'un fil : nombre, formule (texte) ou vide (null). */
export type Cell = number | string | null;

/** Une ligne du tableau. Les champs vides valent null. */
export interface WireRow {
  tag: number | null;
  x1: Cell;
  y1: Cell;
  z1: Cell;
  x2: Cell;
  y2: Cell;
  z2: Cell;
  radius: Cell;
  segments: number | null;
}

/** Une ligne du tableau des symboles. */
export interface SymbolRow {
  name: string;
  formula: string;
}

export const COORDS = ['x1', 'y1', 'z1', 'x2', 'y2', 'z2'] as const;
export const isFormula = (c: Cell): c is string => typeof c === 'string';

/** Saisie d'une case → nombre (virgule décimale acceptée), formule, ou null si vide. */
export function parseCell(text: string): Cell {
  let t = text.trim();
  if (!t) return null;
  if (/^[-+]?\d*,\d+$/.test(t)) t = t.replace(',', '.'); // « 1,5 » saisi à la française
  const n = Number(t);
  return Number.isFinite(n) && /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(t) ? n : t;
}

export const cellText = (c: Cell): string => (c == null ? '' : String(c));

/** Une formule vaut-elle un simple nombre ? (seuls ces symboles peuvent être optimisés) */
export function formulaNumber(formula: string): number | null {
  const c = parseCell(formula);
  return typeof c === 'number' ? c : null;
}

export interface Feed {
  tag: number;
  segment: number | null; // null = segment central du tag
  kind: 0 | 5;
  voltage_re: number;
  voltage_im: number;
}

/** Remarque la plus grave d'une ligne (contrôle du modèle) et son texte pour l'infobulle. */
export interface RowMark {
  severity: 'error' | 'warning' | 'info';
  text: string;
}

/** Remarques du contrôle → marque par ligne du tableau des fils, ou des symboles
 * (`key` = 'symbols') ; la plus grave l'emporte. */
export function rowMarks(
  issues: { severity: RowMark['severity']; message: string; wires: number[]; symbols?: number[] }[],
  key: 'wires' | 'symbols' = 'wires',
): Record<number, RowMark> {
  const rank = { error: 0, warning: 1, info: 2 } as const;
  const marks: Record<number, RowMark> = {};
  for (const issue of issues) {
    for (const row of issue[key] ?? []) {
      const m = marks[row];
      if (!m) marks[row] = { severity: issue.severity, text: issue.message };
      else {
        if (rank[issue.severity] < rank[m.severity]) m.severity = issue.severity;
        m.text += `\n${issue.message}`;
      }
    }
  }
  return marks;
}

export interface GroundState {
  kind: GroundKind;
  epsilon_r: number | null;
  conductivity: number | null; // S/m
  exact: boolean;
}

/** Balayage tel qu'on le saisit : début, fin, nombre de points (le pas s'en déduit). */
export interface SweepRange {
  start_mhz: number;
  stop_mhz: number;
  count: number;
}

/** Tout ce qui décrit l'antenne dans l'éditeur. */
export interface EditorModel {
  rows: WireRow[];
  feed: Feed;
  ground: GroundState;
  sweep: SweepRange;
  patternMhz: number;
  extra: ExtraCard[]; // cartes conservées d'un fichier importé, en lecture seule
  symbols: SymbolRow[];
}

export const MAX_SEGMENTS = 2000; // même limite que l'API (total)

export const defaultGround = (): GroundState => ({
  kind: 'real',
  epsilon_r: 13,
  conductivity: 0.005,
  exact: true,
});

export function rowFromWire(w: Wire): WireRow {
  const [x1, y1, z1] = w.start;
  const [x2, y2, z2] = w.end;
  return { tag: w.tag, x1, y1, z1, x2, y2, z2, radius: w.radius, segments: w.segments };
}

const finite = (v: Cell | undefined): v is number => typeof v === 'number' && Number.isFinite(v);
const num = (v: Cell | undefined): number => (finite(v) ? v : 0);

/** Une case décalée de d : nombre + d, ou formule « (f)+d ». */
const shifted = (c: Cell, d: number): Cell => (isFormula(c) ? `(${c})+${d}` : num(c) + d);

export function nextTag(rows: WireRow[]): number {
  return Math.max(0, ...rows.map((r) => (finite(r.tag) ? r.tag : 0))) + 1;
}

export function newRow(rows: WireRow[] = []): WireRow {
  const tag = nextTag(rows);
  const last = rows.at(-1);
  // Nouveau fil : copie décalée de 1 m du dernier, pour qu'il soit visible tout de suite
  if (last) return { ...last, tag, x1: shifted(last.x1, 1), x2: shifted(last.x2, 1) };
  return { tag, x1: 0, y1: -5, z1: 10, x2: 0, y2: 5, z2: 10, radius: 0.001, segments: 21 };
}

export const centerSegment = (segments: number) => Math.ceil(segments / 2);

/** Nombre total de segments portant ce tag (numérotés de 1 à ce total). */
export function tagSegments(rows: WireRow[], tag: number): number {
  return rows.reduce((s, r) => s + (r.tag === tag && finite(r.segments) ? r.segments : 0), 0);
}

export function feedSegment(rows: WireRow[], feed: Feed): number {
  return feed.segment ?? centerSegment(Math.max(1, tagSegments(rows, feed.tag)));
}

/** Ligne du tableau et rang (0 = premier segment de la ligne) du segment alimenté. */
export function feedLocation(rows: WireRow[], feed: Feed): { row: number; index: number } | null {
  let remaining = feedSegment(rows, feed);
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    if (r.tag !== feed.tag || !finite(r.segments)) continue;
    if (remaining <= r.segments) return { row: i, index: remaining - 1 };
    remaining -= r.segments;
  }
  return null;
}

export const rowHasFormula = (r: WireRow) => [...COORDS, 'radius' as const].some((k) => isFormula(r[k]));

/** Première erreur de saisie de la ligne, ou null. Les formules sont jugées par onec (/validate). */
export function rowError(r: WireRow): string | null {
  if (!finite(r.tag) || !Number.isInteger(r.tag) || r.tag < 1) return 'tag : entier ≥ 1';
  const coords = COORDS.map((k) => r[k]);
  if (!coords.every((c) => finite(c) || (isFormula(c) && c !== ''))) return 'coordonnée manquante';
  if (r.radius == null || (finite(r.radius) && r.radius <= 0)) return 'rayon doit être > 0';
  if (!finite(r.segments) || !Number.isInteger(r.segments) || r.segments < 1)
    return 'segments : entier ≥ 1';
  if (!rowHasFormula(r) && wireLength(r) === 0) return 'fil de longueur nulle';
  return null;
}

/** Longueur d'une ligne en nombres (modèle résolu) ; NaN si elle contient une formule. */
export function wireLength(r: WireRow): number {
  if (rowHasFormula(r)) return NaN;
  return Math.hypot(num(r.x2) - num(r.x1), num(r.y2) - num(r.y1), num(r.z2) - num(r.z1));
}

export const rowStart = (r: WireRow): Vec3 => [num(r.x1), num(r.y1), num(r.z1)];
export const rowEnd = (r: WireRow): Vec3 => [num(r.x2), num(r.y2), num(r.z2)];

/** Lignes en nombres à partir des fils renvoyés par /validate (même ordre) ; null si absent. */
export function resolvedRows(
  rows: WireRow[],
  wires: { start: Vec3; end: Vec3; radius: number }[],
): WireRow[] | null {
  if (wires.length !== rows.length) return null;
  return rows.map((r, i) => {
    const [x1, y1, z1] = wires[i].start;
    const [x2, y2, z2] = wires[i].end;
    return { ...r, x1, y1, z1, x2, y2, z2, radius: wires[i].radius };
  });
}

export const hasFormulas = (m: EditorModel) => m.symbols.length > 0 || m.rows.some(rowHasFormula);

/** Erreurs bloquantes de tout le modèle (vide = on peut simuler). */
export function modelErrors(m: EditorModel): string[] {
  const { rows, feed, ground, sweep, patternMhz } = m;
  const errors: string[] = [];
  m.symbols.forEach((s, i) => {
    if (!s.name.trim()) errors.push(`symbole ${i + 1} : nom manquant`);
    else if (!s.formula.trim()) errors.push(`symbole ${s.name} : valeur ou formule manquante`);
  });
  if (!rows.length) errors.push('aucun fil');
  rows.forEach((r, i) => {
    const e = rowError(r);
    if (e) errors.push(`ligne ${i + 1} : ${e}`);
  });
  const total = rows.reduce((s, r) => s + (r.segments ?? 0), 0);
  if (total > MAX_SEGMENTS) errors.push(`${total} segments au total (maximum ${MAX_SEGMENTS})`);
  const n = tagSegments(rows, feed.tag);
  if (!n) errors.push(`aucun fil de tag ${feed.tag} pour l'alimentation`);
  else {
    const s = feedSegment(rows, feed);
    if (!Number.isInteger(s) || s < 1 || s > n)
      errors.push(`segment alimenté hors limites (1 à ${n} pour le tag ${feed.tag})`);
  }
  if (ground.kind === 'real') {
    if (!finite(ground.epsilon_r) || ground.epsilon_r < 1) errors.push('sol : εr ≥ 1');
    if (!finite(ground.conductivity) || ground.conductivity < 0) errors.push('sol : σ ≥ 0');
  }
  if (!(sweep.start_mhz > 0)) errors.push('balayage : fréquence de début > 0');
  if (!(sweep.stop_mhz >= sweep.start_mhz)) errors.push('balayage : fin ≥ début');
  if (!(Number.isInteger(sweep.count) && sweep.count >= 1 && sweep.count <= 201))
    errors.push('balayage : 1 à 201 points');
  else if (sweep.count > 1 && sweep.stop_mhz === sweep.start_mhz)
    errors.push('balayage : début et fin identiques, mettre 1 point');
  if (!(patternMhz > 0)) errors.push('fréquence du diagramme > 0');
  return errors;
}

function groundIn(g: GroundState): GroundIn {
  if (g.kind !== 'real') return { kind: g.kind };
  return {
    kind: 'real',
    epsilon_r: g.epsilon_r ?? 13,
    conductivity: g.conductivity ?? 0.005,
    exact: g.exact,
  };
}

/** Géométrie envoyée à l'API. */
export function toGeometry(m: EditorModel): GeometryIn {
  const { rows, feed } = m;
  return {
    wires: rows.map((r) => ({
      tag: r.tag ?? 1,
      segments: r.segments ?? 1,
      start: [r.x1 ?? 0, r.y1 ?? 0, r.z1 ?? 0] as [Value, Value, Value],
      end: [r.x2 ?? 0, r.y2 ?? 0, r.z2 ?? 0] as [Value, Value, Value],
      radius: r.radius ?? 0,
    })),
    symbols: m.symbols.map((s) => ({ name: s.name.trim(), formula: s.formula.trim() })),
    excitations: [
      {
        tag: feed.tag,
        segment: feedSegment(rows, feed),
        kind: feed.kind,
        voltage_re: feed.voltage_re,
        voltage_im: feed.voltage_im,
      },
    ],
    ground: groundIn(m.ground),
    extra_cards: m.extra.map((c) => c.text),
  };
}

// Mise en forme de la saisie (pas = étendue / intervalles), pas un calcul d'antenne
export const toModelIn = (m: EditorModel): ModelIn => {
  const { start_mhz, stop_mhz, count } = m.sweep;
  const step_mhz = count > 1 ? (stop_mhz - start_mhz) / (count - 1) : 0;
  return { ...toGeometry(m), sweep: { start_mhz, step_mhz, count } };
};

/** Modèle de l'API → éditeur (modèles pré-remplis et fichiers importés). */
function fromModelIn(model: ModelIn, patternMhz: number, extra: ExtraCard[]): EditorModel {
  const rows = model.wires.map(rowFromWire);
  const ex = model.excitations[0];
  const tag = ex?.tag ?? rows[0]?.tag ?? 1;
  const n = tagSegments(rows, tag);
  return {
    rows,
    feed: {
      tag,
      segment: ex && ex.segment !== centerSegment(n) ? ex.segment : null,
      kind: ex?.kind ?? 0,
      voltage_re: ex?.voltage_re ?? 1,
      voltage_im: ex?.voltage_im ?? 0,
    },
    ground: {
      kind: model.ground.kind,
      epsilon_r: model.ground.epsilon_r ?? 13,
      conductivity: model.ground.conductivity ?? 0.005,
      exact: model.ground.exact ?? true,
    },
    sweep: {
      start_mhz: model.sweep.start_mhz,
      stop_mhz: +(model.sweep.start_mhz + model.sweep.step_mhz * (model.sweep.count - 1)).toFixed(6),
      count: model.sweep.count,
    },
    patternMhz,
    extra,
    symbols: (model.symbols ?? []).map((s) => ({ ...s })),
  };
}

export const fromPreset = (p: Preset) => fromModelIn(p.model, p.design_mhz, []);
export const fromImport = (r: ImportOut) => fromModelIn(r.model, r.frequency_mhz, r.extra);
