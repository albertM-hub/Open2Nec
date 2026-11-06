<script lang="ts">
  // Optimiseur : fait varier des symboles (ceux qui valent un nombre) pour minimiser un score
  // pondéré, calculé par le core (ROS, gain, AV/AR, tous en dB). Suivi en direct par SSE.
  // Rien n'est calculé ici : on prépare la demande, on trace ce que renvoie l'API.
  import { onDestroy } from 'svelte';
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import {
    followOptimize,
    startOptimize,
    stopOptimize,
    type Direction,
    type GroundKind,
    type OptimizeStatus,
    type TrialOut,
  } from '../api/client';
  import { formulaNumber, toGeometry, type EditorModel } from '../state/model';
  import { alpha, color, theme } from '../state/theme.svelte';

  let {
    model,
    z0,
    direction = null,
    ground = 'free',
    blocked = false,
    onpreview,
    onapply,
  }: {
    model: () => EditorModel; // instantané du modèle au lancement
    z0: number;
    direction?: Direction | null; // direction du maximum du dernier diagramme, s'il existe
    ground?: GroundKind;
    blocked?: boolean; // erreurs dans le modèle : lancement impossible
    onpreview?: (values: Record<string, number> | null) => void; // meilleur essai, pour la 3D
    onapply?: (values: Record<string, number>) => void;
  } = $props();

  const PENALTY = 1000; // score d'un essai refusé (core)

  // --- Réglages --------------------------------------------------------------------------
  interface VarSetting {
    on: boolean;
    low: number;
    high: number;
    value: number; // valeur du symbole quand les bornes ont été posées
  }
  let settings = $state<Record<string, VarSetting>>({});
  let bandLow = $state(0);
  let bandHigh = $state(0);
  let nPoints = $state(3);
  let wSwr = $state(100);
  let wGain = $state(0);
  let wFb = $state(0);
  let fbCap = $state(30);
  let theta = $state(90);
  let phi = $state(0);
  let maxEvaluations = $state(300);
  let initialized = false;

  // Symboles qui valent un nombre : seuls candidats
  let candidates = $derived(
    model()
      .symbols.map((s) => ({ name: s.name.trim(), value: formulaNumber(s.formula) }))
      .filter((c): c is { name: string; value: number } => c.name !== '' && c.value !== null),
  );

  $effect(() => {
    // Bornes par défaut : ±20 % de la valeur (±1 si elle est nulle). Posées pour un symbole
    // nouveau, ou dont la valeur a changé et sort des bornes (Appliquer, saisie dans le tableau
    // des symboles) ; jamais pendant qu'on tape une borne (« 15 » passe par « 1 »).
    for (const c of candidates) {
      const cur = settings[c.name];
      if (cur && (cur.value === c.value || (cur.low <= c.value && c.value <= cur.high))) {
        if (cur.value !== c.value) cur.value = c.value;
        continue;
      }
      const d = c.value === 0 ? 1 : Math.abs(c.value) * 0.2;
      settings[c.name] = {
        on: cur?.on ?? false,
        low: +(c.value - d).toPrecision(6),
        high: +(c.value + d).toPrecision(6),
        value: c.value,
      };
    }
    if (!initialized) {
      const m = model();
      bandLow = m.sweep.start_mhz;
      bandHigh = m.sweep.stop_mhz;
      initialized = true;
    }
  });

  $effect(() => {
    if (direction) {
      theta = +direction.theta.toFixed(1);
      phi = +direction.phi.toFixed(1);
    } else {
      // Sans diagramme : horizon en espace libre ; au-dessus du sol, 30° d'élévation (à
      // l'horizon, une antenne au-dessus du sol ne rayonne pas)
      theta = ground === 'free' ? 90 : 60;
    }
  });

  let chosen = $derived(candidates.filter((c) => settings[c.name]?.on));
  let needDirection = $derived(wGain > 0 || wFb > 0);
  let setupError = $derived.by(() => {
    if (!candidates.length)
      return 'Aucun symbole numérique : en créer (« L = 10 ») et les citer dans les fils.';
    if (!chosen.length) return 'Cocher au moins une variable.';
    for (const c of chosen) {
      const s = settings[c.name];
      if (!(s.low < s.high)) return `${c.name} : borne basse < borne haute.`;
      if (c.value < s.low || c.value > s.high) return `${c.name} : la valeur ${c.value} est hors des bornes.`;
    }
    if (!(bandLow > 0 && bandHigh >= bandLow)) return 'Bande : fréquences invalides.';
    if (wSwr + wGain + wFb <= 0) return 'Mettre au moins un poids non nul.';
    return null;
  });

  // --- Suivi ----------------------------------------------------------------------------
  let jobId = $state<string | null>(null);
  let running = $state(false);
  let status = $state<OptimizeStatus | null>(null);
  let start = $state<TrialOut | null>(null);
  let best = $state<TrialOut | null>(null);
  let count = $state(0);
  let rejected = $state(0);
  let lastError = $state<string | null>(null);
  let failure = $state<string | null>(null);
  let startedAt = 0;
  let elapsed = $state(0);
  let undo = $state<Record<string, string> | null>(null); // formules d'avant « Appliquer »
  let applied = $state(false);
  let close: (() => void) | null = null;

  // Courbe : score de chaque essai (points) et meilleur score (trait)
  let chartEl = $state<HTMLDivElement>();
  let chart: uPlot | null = null;
  const xs: number[] = [];
  const ys: (number | null)[] = [];
  const bs: number[] = [];
  let frame = 0;

  function draw() {
    frame = 0;
    if (!chartEl) return;
    if (!chart) {
      chart = new uPlot(
        {
          width: Math.max(chartEl.clientWidth, 300),
          height: 160,
          scales: { x: { time: false } },
          legend: { live: true },
          axes: [
            { stroke: color('muted'), grid: { stroke: color('border') }, ticks: { stroke: color('border') } },
            { stroke: color('muted'), grid: { stroke: color('border') }, ticks: { stroke: color('border') }, label: 'score', size: 52 },
          ],
          series: [
            { label: 'essai' },
            { label: 'score', stroke: color('accent'), width: 0, points: { show: true, size: 6, width: 1, stroke: color('accent'), fill: alpha('accent', 0.55) } },
            { label: 'meilleur', stroke: color('ok'), width: 2, points: { show: false } },
          ],
        },
        [xs, ys, bs],
        chartEl,
      );
    } else chart.setData([xs, ys, bs]);
  }

  function resetChart() {
    xs.length = ys.length = bs.length = 0;
    chart?.destroy();
    chart = null;
  }

  function ontrial(t: TrialOut, b: TrialOut) {
    if (t.n === 0) start = t;
    best = b;
    count = t.n + 1;
    elapsed = (performance.now() - startedAt) / 1000;
    if (t.error) {
      rejected += 1;
      lastError = t.error;
    }
    xs.push(t.n);
    ys.push(t.score >= PENALTY ? null : t.score); // essai refusé : hors courbe, compté à part
    bs.push(b.score);
    onpreview?.(b.values);
    if (!frame) frame = requestAnimationFrame(draw);
  }

  async function launch() {
    if (setupError || blocked) return;
    failure = null;
    status = null;
    start = best = null;
    count = rejected = 0;
    lastError = null;
    applied = false;
    undo = null;
    resetChart();
    const m = model();
    try {
      const { id } = await startOptimize({
        ...toGeometry(m),
        variables: chosen.map((c) => ({ name: c.name, low: settings[c.name].low, high: settings[c.name].high })),
        objective: {
          band_low_mhz: bandLow,
          band_high_mhz: bandHigh,
          n_points: nPoints,
          z0,
          direction: needDirection ? { theta, phi } : null,
          w_swr: wSwr,
          w_gain: wGain,
          w_fb: wFb,
          fb_cap_db: fbCap,
        },
        max_evaluations: maxEvaluations,
      });
      jobId = id;
      running = true;
      startedAt = performance.now();
      close = followOptimize(
        id,
        ontrial,
        (s) => {
          status = s;
          running = false;
          if (s.best) best = s.best;
          if (s.state === 'failed') failure = s.error;
        },
        (msg) => {
          running = false;
          failure = msg;
        },
      );
    } catch (e) {
      failure = e instanceof Error ? e.message : String(e);
    }
  }

  async function stop() {
    if (jobId) await stopOptimize(jobId).catch(() => {});
  }

  function apply() {
    if (!best) return;
    const m = model();
    undo = Object.fromEntries(m.symbols.filter((s) => s.name.trim() in best!.values).map((s) => [s.name.trim(), s.formula]));
    onapply?.(best.values);
    applied = true;
    onpreview?.(null);
  }

  function revert() {
    if (!undo) return;
    onapply?.(Object.fromEntries(Object.entries(undo).map(([k, f]) => [k, Number(f)])));
    undo = null;
    applied = false;
  }

  function discard() {
    onpreview?.(null);
    status = null;
    start = best = null;
    resetChart();
  }

  // Changement de thème : la courbe est recréée avec les nouvelles couleurs
  $effect(() => {
    void theme.version;
    if (chart) {
      chart.destroy();
      chart = null;
      draw();
    }
  });

  onDestroy(() => {
    // autre modèle chargé pendant la recherche : on l'arrête (elle ne s'appliquerait plus)
    if (running && jobId) stopOptimize(jobId).catch(() => {});
    close?.();
    chart?.destroy();
  });

  const REASONS = {
    converged: 'recherche terminée (convergence)',
    max_evaluations: 'limite de calculs atteinte',
    stopped: 'arrêtée à la demande',
  } as const;
  const f2 = (v: number | null | undefined, d = 2) => (v == null ? '—' : v.toFixed(d));
  const swr = (v: number | null | undefined) => (v == null ? '∞' : v.toFixed(2));
  const val = (v: number | undefined) => (v == null ? '—' : String(+v.toPrecision(6)));
  let perTrial = $derived(count ? elapsed / count : 0);
</script>

<section class="opt">
  <h2>Optimiseur</h2>

  {#if candidates.length}
    <table class="vars">
      <thead><tr><th></th><th>variable</th><th>valeur</th><th>min</th><th>max</th></tr></thead>
      <tbody>
        {#each candidates as c (c.name)}
          {#if settings[c.name]}
            <tr>
              <td><input type="checkbox" bind:checked={settings[c.name].on} disabled={running} aria-label={`faire varier ${c.name}`} /></td>
              <td class="mono">{c.name}</td>
              <td class="num">{val(c.value)}</td>
              <td><input type="number" step="any" bind:value={settings[c.name].low} disabled={running} aria-label={`minimum de ${c.name}`} /></td>
              <td><input type="number" step="any" bind:value={settings[c.name].high} disabled={running} aria-label={`maximum de ${c.name}`} /></td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
    {#if chosen.length > 8}<p class="warn">⚠ {chosen.length} variables : la recherche sera longue.</p>{/if}
  {/if}

  <div class="row">
    <label>Bande de (MHz) <input type="number" step="0.05" bind:value={bandLow} disabled={running} /></label>
    <label>à (MHz) <input type="number" step="0.05" bind:value={bandHigh} disabled={running} /></label>
    <label>Points <input type="number" min="1" max="21" bind:value={nPoints} disabled={running} /></label>
    <label title="impédance de référence du ROS : celle du balayage">Z0 (Ω) <input type="number" value={z0} disabled /></label>
  </div>
  <div class="row">
    <label title="perte de désadaptation au pire point de la bande">ROS (%) <input type="number" min="0" max="100" bind:value={wSwr} disabled={running} /></label>
    <label title="gain moyen sur la bande, dans la direction (θ, φ)">Gain (%) <input type="number" min="0" max="100" bind:value={wGain} disabled={running} /></label>
    <label title="AV/AR au pire point de la bande, plafonné">AV/AR (%) <input type="number" min="0" max="100" bind:value={wFb} disabled={running} /></label>
    {#if needDirection}
      <label title="degrés NEC depuis le zénith (90 = horizon) ; repris du dernier diagramme">θ (°) <input type="number" step="1" min="0" max="180" bind:value={theta} disabled={running} /></label>
      <label title="azimut depuis +X ; repris du dernier diagramme">φ (°) <input type="number" step="1" bind:value={phi} disabled={running} /></label>
      <label title="au-delà, l'AV/AR ne rapporte plus rien : évite de courir après un zéro très étroit">plafond AV/AR (dB) <input type="number" min="1" max="60" bind:value={fbCap} disabled={running} /></label>
    {/if}
    <label>Calculs max <input type="number" min="1" max="2000" step="50" bind:value={maxEvaluations} disabled={running} /></label>
  </div>

  <div class="row actions">
    {#if running}
      <button type="button" class="stop" onclick={stop}>Arrêter</button>
    {:else}
      <button onclick={launch} disabled={!!setupError || blocked}>Lancer l'optimisation</button>
    {/if}
    {#if setupError}<span class="hint">{setupError}</span>
    {:else if blocked}<span class="hint">Corriger d'abord les erreurs du modèle.</span>{/if}
  </div>
  {#if failure}<p class="error">{failure}</p>{/if}

  {#if running || status || start}
    <p class="figures">
      <span>{running ? 'en cours' : status?.reason ? REASONS[status.reason] : status?.state === 'failed' ? 'échec' : ''}</span>
      <span><b>{count}</b> / {status?.max_evaluations ?? maxEvaluations} calculs</span>
      <span><b>{elapsed.toFixed(1)}</b> s ({(perTrial * 1000).toFixed(0)} ms par calcul)</span>
      {#if rejected}<span class="warn" title={lastError ?? ''}>{rejected} essai{rejected > 1 ? 's' : ''} refusé{rejected > 1 ? 's' : ''}</span>{/if}
    </p>
    <div class="chart" bind:this={chartEl}></div>

    {#if start && best}
      <table class="result">
        <thead><tr><th></th><th>départ</th><th>meilleur</th></tr></thead>
        <tbody>
          {#each Object.keys(best.values) as k}
            <tr><td class="mono">{k}</td><td>{val(start.values[k])}</td><td><b>{val(best.values[k])}</b></td></tr>
          {/each}
          <tr class="sep"><td>ROS max</td><td>{swr(start.criteria?.swr_max)}</td><td><b>{swr(best.criteria?.swr_max)}</b></td></tr>
          {#if best.criteria?.gain_db != null || start.criteria?.gain_db != null}
            <tr><td>gain (dBi)</td><td>{f2(start.criteria?.gain_db)}</td><td><b>{f2(best.criteria?.gain_db)}</b></td></tr>
            <tr><td>AV/AR min (dB)</td><td>{f2(start.criteria?.fb_db, 1)}</td><td><b>{f2(best.criteria?.fb_db, 1)}</b></td></tr>
          {/if}
          <tr><td>score</td><td>{f2(start.score, 3)}</td><td><b>{f2(best.score, 3)}</b></td></tr>
        </tbody>
      </table>
      {#if !running}
        <div class="row actions">
          {#if !applied}
            <button type="button" class="apply" onclick={apply} disabled={best.n === 0}>Appliquer</button>
            <button type="button" onclick={discard}>Ignorer</button>
            {#if best.n === 0}<span class="hint">Aucun essai meilleur que le départ.</span>{/if}
          {:else}
            <span class="ok">✓ valeurs appliquées aux symboles</span>
            <button type="button" onclick={revert} disabled={!undo}>Annuler</button>
          {/if}
        </div>
      {:else}
        <p class="hint">La vue 3D montre le meilleur essai trouvé jusqu'ici.</p>
      {/if}
    {/if}
  {/if}
</section>

<style>
  .opt { margin-top: 18px; }
  .row { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; margin-top: 8px; }
  .row input { width: 80px; }
  .actions { align-items: center; }
  table { border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
  th { font-weight: 500; opacity: 0.7; padding: 2px 6px; }
  td { padding: 2px 6px; }
  .vars input[type='number'] { width: 80px; padding: 3px; font-size: 11px; }
  .num { text-align: right; }
  .mono { font-family: ui-monospace, monospace; color: var(--formula); }
  .result td:not(:first-child) { text-align: right; }
  .result b { color: var(--text-strong); }
  .result tr.sep td { border-top: 1px solid var(--border); }
  .chart { margin-top: 6px; min-height: 160px; }
  .figures { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; margin: 10px 0 0; }
  .figures b { color: var(--text-strong); }
  .stop { background: var(--danger); }
  .apply { background: var(--apply); }
  .hint { font-size: 11px; opacity: 0.65; }
  .warn { color: var(--warn-text); font-size: 12px; }
  .error { color: var(--error); }
  .ok { color: var(--ok); font-size: 12px; }
</style>
