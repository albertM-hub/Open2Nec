<script lang="ts">
  import { onMount } from 'svelte';
  import {
    ApiError,
    exportFile,
    validate,
    type Issue,
    fetchPresets,
    importFile,
    pattern,
    simulate,
    type GroundKind,
    type PatternOut,
    type Preset,
    type Direction,
    type SimulationOut,
  } from './api/client';
  import PolarChart from './charts/PolarChart.svelte';
  import SmithChart from './charts/SmithChart.svelte';
  import SweepCharts from './charts/SweepCharts.svelte';
  import ExtraCards from './editor/ExtraCards.svelte';
  import ModelChecks from './editor/ModelChecks.svelte';
  import OptimizerPanel from './editor/OptimizerPanel.svelte';
  import SymbolTable from './editor/SymbolTable.svelte';
  import WireTable from './editor/WireTable.svelte';
  import {
    defaultGround,
    fromImport,
    fromPreset,
    hasFormulas,
    modelErrors,
    resolvedRows,
    rowMarks,
    newRow,
    toGeometry,
    toModelIn,
    type EditorModel,
    type WireRow,
  } from './state/model';
  import GeometryView from './viewer3d/GeometryView.svelte';
  import { theme } from './state/theme.svelte';

  const THEME_LABEL = { auto: 'Auto (système)', light: 'Clair', dark: 'Sombre' } as const;

  const MAX_FILE_BYTES = 1_000_000; // même limite que l'API

  // --- Modèle en cours d'édition -------------------------------------------------------
  let presets = $state<Preset[]>([]);
  let m = $state<EditorModel>({
    rows: [newRow()],
    feed: { tag: 1, segment: null, kind: 0, voltage_re: 1, voltage_im: 0 },
    ground: defaultGround(),
    sweep: { start_mhz: 13.9, stop_mhz: 14.5, count: 13 },
    patternMhz: 14.2,
    extra: [],
    symbols: [],
  });
  // D'où vient le modèle : modèle pré-rempli ou fichier ouvert (avec son compte rendu)
  type Source =
    | { kind: 'preset'; id: string }
    | { kind: 'file'; name: string; dropped: string[]; notes: string[] }
    | { kind: 'none' };
  let source = $state<Source>({ kind: 'none' });
  let fitKey = $state(0);
  let fitPending = false;

  // --- Résultats -----------------------------------------------------------------------
  interface Failure {
    message: string;
    engine: boolean;
  }
  let sweepResult = $state<SimulationOut | null>(null);
  let patternResult = $state<PatternOut | null>(null);
  let sweepError = $state<Failure | null>(null);
  let patternError = $state<Failure | null>(null);
  let groundAtRun = $state<GroundKind>('real');
  let z0 = $state(50); // impédance de référence du ROS : changer relance seulement le balayage
  let lastDirection = $state<Direction | null>(null);
  let hoverIndex = $state<number | null>(null);
  let sweepLoading = $state(false);
  let runKey = $state(''); // modèle effectivement simulé, pour signaler des résultats périmés
  let loading = $state(false);
  let fileBusy = $state(false);
  let fileError = $state<string | null>(null);
  let presetsError = $state<string | null>(null);
  let dragging = $state(false);
  let fileInput: HTMLInputElement;

  function setModel(next: EditorModel, src: Source) {
    m = next;
    source = src;
    sweepResult = patternResult = null;
    sweepError = patternError = null;
    runKey = '';
    fileError = null;
    resolved = null;
    symbolValues = {};
    previewValues = null;
    fitKey += 1;
    // modèle en formules : la vue 3D se recadrera quand onec aura calculé la géométrie
    fitPending = hasFormulas(next);
  }

  function loadPreset(p: Preset) {
    setModel(fromPreset(p), { kind: 'preset', id: p.id });
    z0 = p.z0; // impédance de référence proposée avec le modèle (120 Ω pour la quad)
  }

  onMount(async () => {
    try {
      presets = await fetchPresets();
      if (presets.length) loadPreset(presets[0]);
    } catch (e) {
      presetsError = e instanceof Error ? e.message : String(e);
    }
  });

  // --- Fichiers ------------------------------------------------------------------------
  async function openFile(file: File | undefined) {
    if (!file) return;
    fileError = null;
    if (file.size > MAX_FILE_BYTES) {
      fileError = `${file.name} : fichier trop gros (maximum ${MAX_FILE_BYTES / 1000} ko)`;
      return;
    }
    fileBusy = true;
    try {
      const r = await importFile(file.name, await file.text());
      setModel(fromImport(r), { kind: 'file', name: file.name, dropped: r.dropped, notes: r.notes });
    } catch (e) {
      fileError = `${file.name} : ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      fileBusy = false;
      if (fileInput) fileInput.value = ''; // permet de rouvrir le même fichier
    }
  }

  async function saveFile() {
    fileError = null;
    try {
      const text = await exportFile(toModelIn($state.snapshot(m)));
      const base =
        source.kind === 'file'
          ? source.name.replace(/\.[^.]*$/, '')
          : source.kind === 'preset'
            ? `open2nec-${source.id}`
            : 'open2nec';
      const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
      const a = Object.assign(document.createElement('a'), { href: url, download: `${base}.nec` });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      fileError = `Enregistrement impossible : ${e instanceof Error ? e.message : String(e)}`;
    }
  }

  // --- Simulation ----------------------------------------------------------------------
  let errors = $derived(modelErrors(m));

  // --- Contrôle du modèle (core, via /validate), en direct pendant la saisie ----------------
  let issues = $state<Issue[]>([]);
  let checking = $state(false);
  let checkUnavailable = $state<string | null>(null);
  let focusRows = $state<number[]>([]);
  let focusSymbols = $state<number[]>([]);
  let marks = $derived(rowMarks(issues));
  let symbolMarks = $derived(rowMarks(issues, 'symbols'));
  // Formules calculées par onec : valeurs des symboles et fils en nombres (dernier calcul réussi)
  let symbolValues = $state<Record<string, number>>({});
  let resolved = $state<WireRow[] | null>(null);
  // Pendant l'optimisation : géométrie du meilleur essai, pour la vue 3D
  let previewValues = $state<Record<string, number> | null>(null);
  let preview = $state<WireRow[] | null>(null);
  let viewRows = $derived(
    preview ?? (hasFormulas(m) ? (resolved ?? []) : m.rows),
  );
  let blocking = $derived(issues.some((i) => i.severity === 'error'));
  let checkTimer: ReturnType<typeof setTimeout> | undefined;
  let checkSeq = 0;

  $effect(() => {
    const snap = $state.snapshot(m) as EditorModel;
    clearTimeout(checkTimer);
    // Saisie incomplète : les erreurs de saisie s'affichent déjà sous le formulaire
    if (modelErrors(snap).length) {
      issues = [];
      checking = false;
      return;
    }
    checking = true;
    const seq = ++checkSeq;
    checkTimer = setTimeout(async () => {
      try {
        const maxMhz = Math.max(snap.sweep.stop_mhz, snap.patternMhz);
        const out = await validate(toGeometry(snap), maxMhz);
        if (seq !== checkSeq) return; // une saisie plus récente a déjà relancé le contrôle
        issues = out.issues;
        symbolValues = out.symbol_values;
        // erreur de formule : on garde la dernière géométrie calculée plutôt qu'une vue vide
        const rows = resolvedRows(snap.rows, out.wires);
        if (rows || !hasFormulas(snap)) resolved = rows;
        if (rows && fitPending) {
          fitPending = false;
          fitKey += 1;
        }
        checkUnavailable = null;
      } catch (e) {
        if (seq !== checkSeq) return;
        issues = [];
        checkUnavailable = e instanceof Error ? e.message : String(e);
      } finally {
        if (seq === checkSeq) checking = false;
      }
    }, 300);
  });
  // Meilleur essai de l'optimiseur → géométrie calculée par onec (au plus 2 fois par seconde)
  let previewTimer: ReturnType<typeof setTimeout> | undefined;
  let previewBusy = false;
  $effect(() => {
    const values = previewValues;
    if (!values) {
      preview = null;
      return;
    }
    if (previewTimer || previewBusy) return; // le prochain tour prendra la valeur la plus récente
    previewTimer = setTimeout(async () => {
      previewTimer = undefined;
      const latest = previewValues;
      if (!latest) return;
      previewBusy = true;
      try {
        const snap = withValues($state.snapshot(m) as EditorModel, latest);
        const out = await validate(toGeometry(snap), Math.max(snap.sweep.stop_mhz, snap.patternMhz));
        if (previewValues) preview = resolvedRows(snap.rows, out.wires) ?? preview;
      } catch {
        // aperçu seulement : une erreur passagère ne doit rien casser
      } finally {
        previewBusy = false;
      }
    }, 500);
  });

  /** Copie du modèle où les symboles nommés valent ces nombres. */
  function withValues(model: EditorModel, values: Record<string, number>): EditorModel {
    const fmt = (v: number) => String(+v.toPrecision(7));
    return {
      ...model,
      symbols: model.symbols.map((s) =>
        s.name.trim() in values ? { ...s, formula: fmt(values[s.name.trim()]) } : s,
      ),
    };
  }

  function applyValues(values: Record<string, number>) {
    m = withValues($state.snapshot(m) as EditorModel, values);
  }

  const inputKey = () => JSON.stringify(m);
  let stale = $derived(runKey !== '' && runKey !== inputKey());

  const failure = (e: unknown): Failure =>
    e instanceof ApiError
      ? { message: e.message, engine: e.engine }
      : { message: e instanceof Error ? e.message : String(e), engine: false };

  /** Balayage seul (relancé quand Z0 change), avec gain suivi dans `direction`. */
  async function runSweep(snap: EditorModel, direction: Direction | null) {
    sweepLoading = true;
    try {
      sweepResult = await simulate({ ...toModelIn(snap), z0, direction });
      sweepError = null;
    } catch (e) {
      sweepResult = null;
      sweepError = failure(e);
    } finally {
      sweepLoading = false;
      hoverIndex = null;
    }
  }

  async function run() {
    if (errors.length) return;
    loading = true;
    const snap = $state.snapshot(m) as EditorModel;
    const key = inputKey();
    // Diagramme d'abord : sa direction de gain maximal sert au balayage (gain et AV/AR).
    // L'échec de l'un n'empêche pas l'autre.
    try {
      patternResult = await pattern(toGeometry(snap), snap.patternMhz);
      patternError = null;
    } catch (e) {
      patternResult = null;
      patternError = failure(e);
    }
    const s = patternResult?.summary;
    lastDirection = s ? { theta: s.max_theta, phi: s.max_phi } : null;
    await runSweep(snap, lastDirection);
    groundAtRun = snap.ground.kind;
    runKey = key;
    loading = false;
  }

  // Z0 modifié après un calcul : on relance le balayage seul (le diagramme n'en dépend pas)
  let z0Timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const value = z0;
    if (!runKey || stale || !(value > 0) || value === sweepResult?.summary.z0) return;
    clearTimeout(z0Timer);
    z0Timer = setTimeout(() => runSweep($state.snapshot(m) as EditorModel, lastDirection), 400);
  });

  let busy = $derived(loading || sweepLoading);
  // Balayage long : sol réel exact (Sommerfeld) recalculé à chaque fréquence par onec
  let slowHint = $derived(
    busy && m.ground.kind === 'real' && m.ground.exact && m.sweep.count > 30,
  );

  let warnings = $derived([
    ...new Set([...(sweepResult?.warnings ?? []), ...(patternResult?.warnings ?? [])]),
  ]);
  let failures = $derived([sweepError, patternError].filter((f): f is Failure => f !== null));
  // Même message pour les deux appels (ex. excitation invalide) : on ne l'affiche qu'une fois
  let failureMessages = $derived([...new Set(failures.map((f) => f.message))]);
  let engineDown = $derived(failures.some((f) => f.engine));

  let sweepSummary = $derived(sweepResult?.summary ?? null);
  const mhz = (f: number) => f.toFixed(3);

  let summary = $derived(patternResult?.summary ?? null);
  let feedAtPattern = $derived(patternResult?.feedpoints[0] ?? null);
  // ROS à la fréquence du diagramme, sur le Z0 choisi : repris du balayage (calculé par le
  // core) s'il contient cette fréquence ; sinon celui sur 50 Ω renvoyé avec le diagramme
  let swrAtPattern = $derived.by(() => {
    const f = patternResult?.frequency_mhz;
    const p = sweepResult?.points.find((q) => f != null && Math.abs(q.frequency_mhz - f) < 1e-6);
    if (p && sweepResult) return { z0: sweepResult.summary.z0, swr: p.swr };
    return feedAtPattern ? { z0: 50, swr: feedAtPattern.swr_50 } : null;
  });
  const signed = (x: number) => (x >= 0 ? `+${x.toFixed(1)}` : x.toFixed(1));
  let presetDesc = $derived.by(() => {
    const s = source;
    return s.kind === 'preset' ? presets.find((p) => p.id === s.id)?.description : undefined;
  });
</script>

<svelte:window
  ondragover={(e) => {
    if (e.dataTransfer?.types.includes('Files')) {
      e.preventDefault();
      dragging = true;
    }
  }}
  ondragleave={(e) => {
    if (!e.relatedTarget) dragging = false;
  }}
  ondrop={(e) => {
    e.preventDefault();
    dragging = false;
    openFile(e.dataTransfer?.files[0]);
  }}
/>

{#if dragging}<div class="dropzone">Déposer le fichier .nec pour l'ouvrir</div>{/if}

<main>
  <header>
    <div>
      <h1>Open2Nec</h1>
      <p class="sub">Simulation d'antennes NEC-2</p>
    </div>
    <button
      type="button"
      class="theme"
      onclick={() => theme.cycle()}
      title="Changer de thème : Auto (réglage du système) → Clair → Sombre"
      aria-label={`Thème : ${THEME_LABEL[theme.choice]}, cliquer pour changer`}
    >
      Thème : {THEME_LABEL[theme.choice]}
    </button>
  </header>

  <div class="layout">
    <section class="editor">
      <div class="row">
        <label>
          Modèle
          <select
            value={source.kind === 'preset' ? source.id : ''}
            onchange={(e) => {
              const p = presets.find((x) => x.id === e.currentTarget.value);
              if (p) loadPreset(p);
            }}
          >
            {#if source.kind !== 'preset'}
              <option value="">{source.kind === 'file' ? `— ${source.name} —` : '— personnalisé —'}</option>
            {/if}
            {#each presets as p}<option value={p.id}>{p.name}</option>{/each}
          </select>
        </label>
        <button type="button" onclick={() => fileInput.click()} disabled={fileBusy}>
          {fileBusy ? 'Lecture…' : 'Ouvrir un fichier…'}
        </button>
        <button type="button" onclick={saveFile} disabled={errors.length > 0}>Enregistrer en .nec</button>
        <input
          bind:this={fileInput}
          type="file"
          accept=".nec,.NEC"
          hidden
          onchange={(e) => openFile(e.currentTarget.files?.[0])}
        />
      </div>
      {#if presetDesc}<p class="hint desc">{presetDesc}</p>{/if}
      {#if presetsError}<p class="error">Modèles indisponibles : {presetsError}</p>{/if}
      {#if fileError}<p class="error">{fileError}</p>{/if}

      {#if source.kind === 'file'}
        <div class="banner">
          <b>{source.name}</b> ouvert : {m.rows.length} fil{m.rows.length > 1 ? 's' : ''},
          {m.extra.length} carte{m.extra.length > 1 ? 's' : ''} conservée{m.extra.length > 1 ? 's' : ''}.
          {#each source.notes as n}<div>• {n}</div>{/each}
          {#if source.dropped.length}<div>• écarté (affichage seulement) : {source.dropped.join(', ')}</div>{/if}
        </div>
      {:else}
        <p class="hint">Astuce : glisser un fichier .nec (4NEC2) sur la page pour l'ouvrir.</p>
      {/if}

      <h2>Symboles</h2>
      <SymbolTable bind:symbols={m.symbols} values={symbolValues} marks={symbolMarks} focus={focusSymbols} />

      <h2>Fils</h2>
      <WireTable
        bind:rows={m.rows}
        bind:feed={m.feed}
        marks={marks}
        focus={focusRows}
        resolved={hasFormulas(m) ? resolved : null}
      />
      <ExtraCards cards={m.extra} />
      <ModelChecks
        {issues}
        pending={checking}
        unavailable={checkUnavailable}
        onfocus={(r, s) => {
          focusRows = r;
          focusSymbols = s;
        }}
      />

      <h2>Sol et fréquences</h2>
      <form
        class="row"
        onsubmit={(e) => {
          e.preventDefault();
          run();
        }}
      >
        <label>Sol
          <select bind:value={m.ground.kind}>
            <option value="free">Espace libre</option>
            <option value="perfect">Parfait</option>
            <option value="real">Réel</option>
          </select>
        </label>
        {#if m.ground.kind === 'real'}
          <label>εr <input type="number" step="1" min="1" bind:value={m.ground.epsilon_r} /></label>
          <label>σ (S/m) <input type="number" step="0.001" min="0" bind:value={m.ground.conductivity} /></label>
          <label class="check" title="Sommerfeld-Norton (GN 2), recommandé ; sinon approximation par coefficient de réflexion (GN 0)">
            <input type="checkbox" bind:checked={m.ground.exact} /> calcul exact
          </label>
        {/if}
        <div class="break"></div>
        <label>Balayage de (MHz) <input type="number" step="0.05" bind:value={m.sweep.start_mhz} /></label>
        <label>à (MHz) <input type="number" step="0.05" bind:value={m.sweep.stop_mhz} /></label>
        <label>Points <input type="number" min="1" max="201" bind:value={m.sweep.count} /></label>
        <label title="impédance de référence du ROS ; la modifier relance le balayage">Z0 (Ω)
          <input type="number" min="1" step="1" list="z0-values" bind:value={z0} />
          <datalist id="z0-values"><option value="50"></option><option value="75"></option><option value="300"></option><option value="450"></option></datalist>
        </label>
        <label>Diagramme à (MHz) <input type="number" step="0.05" bind:value={m.patternMhz} /></label>
        <button disabled={busy || errors.length > 0 || blocking}>{busy ? 'Calcul…' : 'Simuler'}</button>
      </form>
      {#if errors.length}
        <ul class="errors">{#each errors as e}<li>{e}</li>{/each}</ul>
      {/if}

      {#key source}
        <!-- recréé à chaque modèle chargé : bande et variables repartent de ce modèle -->
        <OptimizerPanel
          model={() => $state.snapshot(m) as EditorModel}
          {z0}
          direction={lastDirection}
          ground={m.ground.kind}
          blocked={errors.length > 0 || blocking}
          onpreview={(v) => (previewValues = v)}
          onapply={applyValues}
        />
      {/key}
    </section>

    <section class="results">
      <GeometryView rows={viewRows} feed={m.feed} ground={m.ground.kind} {fitKey} {marks} focus={focusRows} />
      {#if preview}<p class="hint">Vue 3D : meilleur essai de l'optimiseur.</p>{/if}

      {#if engineDown}
        <p class="error">Moteur de calcul indisponible : {failureMessages.join(' ; ')}</p>
      {:else}
        {#each failureMessages as msg}<p class="error">{msg}</p>{/each}
      {/if}
      {#each warnings as w}<p class="warn">⚠ {w}</p>{/each}
      {#if stale}<p class="hint">Le modèle a changé depuis le dernier calcul : relancer « Simuler ».</p>{/if}
      {#if slowHint}<p class="hint">Sol réel exact : calcul plus long (recalculé à chaque fréquence). Décocher « calcul exact » pour un aperçu rapide.</p>{/if}

      <div class:dim={stale}>
        {#if patternResult}
          <h2>Diagramme à {patternResult.frequency_mhz} MHz</h2>
          {#if summary}
            <p class="figures">
              <span><b>{summary.max_gain_db.toFixed(2)}</b> dBi</span>
              <span>départ <b>{summary.takeoff_deg.toFixed(0)}°</b></span>
              <span>azimut du max <b>{summary.max_phi.toFixed(0)}°</b></span>
              <span>AV/AR <b>{summary.front_to_back_db == null ? '—' : summary.front_to_back_db.toFixed(1) + ' dB'}</b></span>
              {#if feedAtPattern}
                <span>Z <b>{feedAtPattern.r.toFixed(1)} {signed(feedAtPattern.x)}j Ω</b></span>
                {#if swrAtPattern}
                  <span>ROS <b>{swrAtPattern.swr?.toFixed(2) ?? '∞'}</b> ({swrAtPattern.z0} Ω)</span>
                {/if}
              {/if}
            </p>
            <div class="polars">
              <PolarChart
                kind="azimuth"
                title={`Azimut, à ${summary.takeoff_deg.toFixed(0)}° d'élévation (vue de dessus, +X en haut)`}
                points={summary.azimuth_cut}
                gmax={summary.max_gain_db}
                marker={summary.max_phi}
              />
              <PolarChart
                kind="elevation"
                title={`Élévation, vers ${summary.max_phi.toFixed(0)}° d'azimut (avant à droite)`}
                points={summary.elevation_cut}
                gmax={summary.max_gain_db}
                marker={summary.takeoff_deg}
                hemisphere={groundAtRun !== 'free'}
              />
            </div>
          {:else}
            <p class="warn">Aucun rayonnement calculé à cette fréquence.</p>
          {/if}
        {/if}

      </div>
    </section>
  </div>

  <section class="sweep-section" class:dim={stale}>
    {#if sweepResult && sweepSummary}
      <h2>Balayage{sweepLoading ? ' (calcul…)' : ''}</h2>
      <p class="figures">
        {#if sweepSummary.min_swr != null && sweepSummary.min_swr_mhz != null}
          <span>ROS mini <b>{sweepSummary.min_swr.toFixed(2)}</b> à <b>{mhz(sweepSummary.min_swr_mhz)}</b> MHz</span>
        {/if}
        <span>résonance
          <b>{sweepSummary.resonances.length ? sweepSummary.resonances.map(mhz).join(' ; ') + ' MHz' : 'hors balayage'}</b></span>
        {#each [2, 1.5] as t}
          {@const b = sweepSummary.bands.find((x) => x.threshold === t)}
          <span>bande ROS {t} :
            {#if b}
              <b>{b.low_open ? '< ' : ''}{mhz(b.low_mhz)} → {b.high_open ? '> ' : ''}{mhz(b.high_mhz)}</b>
              ({b.low_open || b.high_open ? 'au moins ' : ''}{b.width_khz.toFixed(0)} kHz)
            {:else}<b>aucune</b>{/if}
          </span>
        {/each}
      </p>
      <div class="sweep">
        <div class="curves">
          <SweepCharts
            points={sweepResult.points}
            summary={sweepSummary}
            onhover={(i) => (hoverIndex = i)}
          />
        </div>
        <SmithChart
          points={sweepResult.points}
          z0={sweepSummary.z0}
          hover={hoverIndex}
          onhover={(i) => (hoverIndex = i)}
        />
      </div>
      <details>
        <summary>Tableau des valeurs ({sweepResult.points.length} fréquences)</summary>
        <table>
          <thead>
            <tr><th>f (MHz)</th><th>R (Ω)</th><th>X (Ω)</th><th>ROS</th><th>Gain (dBi)</th><th>AV/AR (dB)</th></tr>
          </thead>
          <tbody>
            {#each sweepResult.points as p, i}
              <tr class:hl={i === hoverIndex}>
                <td>{p.frequency_mhz.toFixed(3)}</td>
                <td>{p.r.toFixed(1)}</td>
                <td>{p.x.toFixed(1)}</td>
                <td>{p.swr?.toFixed(2) ?? '∞'}</td>
                <td>{p.gain_db?.toFixed(2) ?? '—'}</td>
                <td>{p.front_to_back_db?.toFixed(1) ?? '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </details>
    {/if}
  </section>
</main>

<style>
  main { max-width: 1400px; margin: 0 auto; padding: 20px 16px; }
  header { margin-bottom: 12px; display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  .theme { font-size: 12px; padding: 5px 12px; white-space: nowrap; }
  h1 { margin: 0; }
  .sub { opacity: 0.7; margin-top: 4px; }
  .layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 24px; }
  @media (min-width: 1100px) {
    .layout { grid-template-columns: minmax(0, 56fr) minmax(0, 44fr); }
  }
  section { min-width: 0; }
  .editor h2 { margin-top: 18px; }
  .row { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
  .row input:not([type='checkbox']) { width: 90px; }
  .break { flex-basis: 100%; height: 0; }
  .check { flex-direction: row; align-items: center; gap: 6px; padding-bottom: 8px; }
  .desc { margin: 6px 0 0; }
  .hint { font-size: 12px; opacity: 0.65; }
  .banner { margin-top: 10px; padding: 8px 10px; font-size: 12px; line-height: 1.5; background: var(--banner); border-left: 3px solid var(--accent); border-radius: 4px; }
  .errors { color: var(--error); font-size: 12px; margin: 8px 0 0; padding-left: 18px; }
  .results h2 { margin-top: 16px; }
  .figures { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; margin: 0 0 8px; }
  .figures b { color: var(--text-strong); font-variant-numeric: tabular-nums; }
  .polars { display: flex; flex-wrap: wrap; gap: 16px; }
  .sweep-section { margin-top: 8px; }
  .sweep-section h2 { margin-top: 16px; }
  .sweep { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
  .curves { flex: 1 1 420px; min-width: 0; }
  details { margin-top: 12px; font-size: 12px; }
  details summary { cursor: pointer; opacity: 0.85; }
  tr.hl td { background: color-mix(in srgb, var(--warn) 15%, transparent); }
  .dim { opacity: 0.5; }
  table { border-collapse: collapse; margin-top: 12px; width: 100%; font-variant-numeric: tabular-nums; }
  th, td { padding: 4px 10px; text-align: right; border-bottom: 1px solid var(--border-soft); }
  .error { color: var(--error); }
  .warn { color: var(--warn-text); }
  .dropzone { position: fixed; inset: 0; z-index: 10; display: grid; place-items: center; font-size: 20px; background: color-mix(in srgb, var(--bg) 85%, transparent); border: 3px dashed var(--accent); pointer-events: none; }
</style>
