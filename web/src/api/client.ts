// Types alignés à la main sur api/app/schemas.py.
// À terme : les générer depuis l'OpenAPI de FastAPI.

export type Vec3 = [number, number, number];
export type GroundKind = 'free' | 'perfect' | 'real';

/** Case d'un fil : un nombre, ou une formule 4NEC2 (« -L/2 ») calculée par onec. */
export type Value = number | string;
export type Point = [Value, Value, Value];

export interface Wire {
  tag: number;
  segments: number;
  start: Point;
  end: Point;
  radius: Value;
}

/** Symbole 4NEC2 (carte SY) : nom = formule. */
export interface SymbolIn {
  name: string;
  formula: string;
}

export interface Excitation {
  tag: number;
  segment: number;
  voltage_re?: number;
  voltage_im?: number;
  kind?: 0 | 5; // EX 0 (courant) ou EX 5 (conservé d'un fichier importé)
}

export interface GroundIn {
  kind: GroundKind;
  epsilon_r?: number;
  conductivity?: number; // S/m
  exact?: boolean; // sol réel : Sommerfeld (GN 2) ou approché (GN 0)
}

export interface GeometryIn {
  wires: Wire[];
  symbols?: SymbolIn[];
  excitations: Excitation[];
  ground: GroundIn;
  extra_cards?: string[]; // cartes conservées d'un fichier importé (LD, TL, NT…)
}

export interface SweepIn {
  start_mhz: number;
  step_mhz: number;
  count: number;
}

export interface Direction {
  theta: number; // degrés NEC depuis le zénith
  phi: number; // degrés depuis +X
}

export interface ModelIn extends GeometryIn {
  sweep: SweepIn;
  pattern?: { n_theta: number; n_phi: number; d_theta: number; d_phi: number } | null;
  z0?: number; // impédance de référence du ROS (Ω), 50 par défaut
  direction?: Direction | null; // gain avant/arrière suivi pendant le balayage
}

export interface FeedpointOut {
  tag: number;
  segment: number;
  r: number;
  x: number;
  swr_50: number | null;
}

export interface FrequencyOut {
  frequency_mhz: number;
  feedpoints: FeedpointOut[];
  max_gain_db: number | null;
  pattern: { theta: number; phi: number; gain_db: number }[];
}

export interface SweepPoint {
  frequency_mhz: number;
  r: number;
  x: number;
  swr: number | null; // par rapport à z0 ; null si infini
  gamma_re: number;
  gamma_im: number;
  gain_db: number | null;
  gain_back_db: number | null;
  front_to_back_db: number | null;
}

export interface Band {
  threshold: number;
  low_mhz: number;
  high_mhz: number;
  low_open: boolean;
  high_open: boolean;
  width_khz: number;
}

export interface SweepSummary {
  z0: number;
  min_swr: number | null;
  min_swr_mhz: number | null;
  resonances: number[];
  bands: Band[];
}

export interface SimulationOut {
  frequencies: FrequencyOut[];
  points: SweepPoint[];
  summary: SweepSummary;
  warnings: string[];
}

export interface CutPoint {
  angle: number; // degrés
  gain_db: number; // dBi ; -999.99 = aucun rayonnement
}

export interface PatternSummary {
  max_gain_db: number;
  max_phi: number;
  max_theta: number;
  takeoff_deg: number;
  front_to_back_db: number | null;
  azimuth_cut: CutPoint[];
  elevation_cut: CutPoint[];
}

export interface PatternOut {
  frequency_mhz: number;
  feedpoints: FeedpointOut[];
  summary: PatternSummary | null;
  warnings: string[];
}

export interface ExtraCard {
  text: string;
  description: string;
}

export interface ImportOut {
  model: ModelIn;
  frequency_mhz: number;
  extra: ExtraCard[];
  dropped: string[];
  notes: string[];
}

export interface Preset {
  id: string;
  name: string;
  description: string;
  design_mhz: number;
  z0: number; // impédance de référence du ROS proposée pour ce modèle (Ω)
  model: ModelIn;
}

/** Erreur d'API : `engine` distingue le moteur indisponible (503) d'une requête refusée. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
  get engine(): boolean {
    return this.status === 503;
  }
}

// FastAPI renvoie soit un texte (nos HTTPException), soit une liste d'erreurs Pydantic (422)
function errorMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (typeof d?.msg === 'string' ? d.msg.replace(/^Value error, /, '') : null))
      .filter((m): m is string => !!m);
    return msgs.length ? msgs.join(' ; ') : null;
  }
  return null;
}

async function request<T>(path: string, body?: unknown, as: 'json' | 'text' = 'json'): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError('serveur injoignable (API arrêtée ?)', 0);
  }
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new ApiError(errorMessage(payload?.detail) ?? `Erreur HTTP ${res.status}`, res.status);
  }
  return (as === 'text' ? res.text() : res.json()) as Promise<T>;
}

export const simulate = (model: ModelIn) => request<SimulationOut>('/simulate', model);
export const pattern = (geometry: GeometryIn, frequency_mhz: number) =>
  request<PatternOut>('/pattern', { ...geometry, frequency_mhz });
export const fetchPresets = () => request<Preset[]>('/presets');

export type Severity = 'error' | 'warning' | 'info';

export interface Issue {
  severity: Severity;
  code: string;
  message: string;
  wires: number[]; // lignes du tableau concernées (à partir de 0)
  symbols?: number[]; // lignes du tableau des symboles concernées
}

export interface ValidateOut {
  issues: Issue[];
  symbol_values: Record<string, number>; // valeurs calculées par onec
  wires: { start: Vec3; end: Vec3; radius: number }[]; // fils en nombres (vue 3D)
}

export const validate = (geometry: GeometryIn, max_frequency_mhz: number) =>
  request<ValidateOut>('/validate', { ...geometry, max_frequency_mhz });
export const importFile = (filename: string, content: string) =>
  request<ImportOut>('/import', { filename, content });
export const exportFile = (model: ModelIn) => request<string>('/export', model, 'text');

// --- Optimiseur (jalon 6) -------------------------------------------------------------------

export interface VariableIn {
  name: string;
  low: number;
  high: number;
}

export interface ObjectiveIn {
  band_low_mhz: number;
  band_high_mhz: number;
  n_points: number;
  z0: number;
  direction: Direction | null;
  w_swr: number; // poids en %
  w_gain: number;
  w_fb: number;
  fb_cap_db: number;
}

export interface OptimizeIn extends GeometryIn {
  variables: VariableIn[];
  objective: ObjectiveIn;
  max_evaluations: number;
}

export interface CriteriaOut {
  swr_max: number | null; // null = infini
  swr_loss_db: number;
  gain_db: number | null;
  fb_db: number | null;
}

export interface TrialOut {
  n: number; // 0 = modèle de départ
  values: Record<string, number>;
  score: number;
  criteria: CriteriaOut | null;
  error: string | null;
}

export interface OptimizeStatus {
  id: string;
  state: 'running' | 'done' | 'failed';
  reason: 'converged' | 'max_evaluations' | 'stopped' | null;
  error: string | null;
  evaluations: number;
  max_evaluations: number;
  start: TrialOut | null;
  best: TrialOut | null;
}

export const startOptimize = (body: OptimizeIn) => request<{ id: string }>('/optimize', body);
export const stopOptimize = (id: string) => request<OptimizeStatus>(`/optimize/${id}/stop`, {});

/**
 * Suit une recherche en SSE. EventSource se reconnecte seul après une coupure et renvoie
 * Last-Event-ID : l'API reprend au bon essai. Renvoie la fonction qui ferme le flux.
 */
export function followOptimize(
  id: string,
  ontrial: (trial: TrialOut, best: TrialOut) => void,
  ondone: (status: OptimizeStatus) => void,
  onerror: (message: string) => void,
): () => void {
  const es = new EventSource(`/api/optimize/${id}/events`);
  es.addEventListener('trial', (e) => {
    const d = JSON.parse((e as MessageEvent).data);
    ontrial(d.trial, d.best);
  });
  es.addEventListener('done', (e) => {
    es.close();
    ondone(JSON.parse((e as MessageEvent).data));
  });
  es.onerror = () => {
    // CLOSED : l'API a refusé le flux (recherche expirée, serveur arrêté) ; sinon reconnexion
    if (es.readyState === EventSource.CLOSED) onerror('suivi interrompu (API arrêtée ?)');
  };
  return () => es.close();
}
