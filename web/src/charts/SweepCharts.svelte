<script lang="ts">
  // Courbes du balayage (uPlot, embarqué) : ROS, R et X, gain et AV/AR.
  // Curseur partagé, zoom synchronisé (tirer sur une plage ; double-clic pour revenir).
  // Aucune valeur n'est calculée ici : tout vient de l'API (core) ; on ne fait que tracer.
  import { onMount } from 'svelte';
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import type { SweepPoint, SweepSummary } from '../api/client';
  import { alpha, color, theme } from '../state/theme.svelte';

  let {
    points,
    summary,
    onhover,
  }: {
    points: SweepPoint[];
    summary: SweepSummary;
    onhover?: (index: number | null) => void;
  } = $props();

  const HEIGHT = 170;
  // Couleurs du thème courant : relues à chaque construction (le canevas ignore les variables CSS)
  const palette = () => ({
    axis: color('muted'),
    grid: color('border'),
    swr: color('accent'),
    r: color('ok'),
    x: color('series-2'),
    gain: color('accent'),
    fb: color('warn'),
    band2: alpha('ok', 0.1),
    band15: alpha('ok', 0.16),
    guide: alpha('text', 0.35),
  });
  let C = palette();

  let wrap: HTMLDivElement;
  let swrEl: HTMLDivElement;
  let rxEl: HTMLDivElement;
  let gainEl = $state<HTMLDivElement>(); // dans un {#if} : référence réactive
  let charts: uPlot[] = [];
  let syncing = false;
  const syncKey = `sweep-${Math.random().toString(36).slice(2)}`;

  let hasGain = $derived(points.some((p) => p.gain_db != null));

  // Points marqués seulement sur un balayage court (au-delà, la courbe suffit)
  const dots = () => ({ show: points.length <= 40 });

  const fmt = (digits: number, unit = '') => (_u: uPlot, v: number | null) =>
    v == null ? '—' : `${v.toFixed(digits)}${unit}`;

  function axes(yLabel: string, right?: uPlot.Axis): uPlot.Axis[] {
    const base = { stroke: C.axis, grid: { stroke: C.grid, width: 1 }, ticks: { stroke: C.grid, width: 1 } };
    // Axe de droite toujours présent (vide au besoin) : même largeur de tracé pour toutes les
    // courbes, donc des curseurs alignés verticalement
    const spacer: uPlot.Axis = {
      side: 1,
      size: 52,
      stroke: 'transparent',
      grid: { show: false },
      ticks: { show: false },
      values: () => [],
    };
    return [
      { ...base, values: (_u, ticks) => ticks.map((t) => t.toFixed(2)) },
      { ...base, label: yLabel, size: 52 },
      right ?? spacer,
    ];
  }

  function common(): Partial<uPlot.Options> & { width: number; height: number } {
    return {
      width: Math.max(wrap?.clientWidth ?? 600, 300),
      height: HEIGHT,
      cursor: { sync: { key: syncKey }, drag: { x: true, y: false } },
      scales: { x: { time: false } },
      legend: { live: true },
      hooks: {
        // zoom propagé aux autres courbes (le double-clic remet tout à l'échelle)
        setScale: [
          (u, key) => {
            if (key !== 'x' || syncing) return;
            syncing = true;
            const { min, max } = u.scales.x;
            for (const o of charts) if (o !== u && min != null && max != null) o.setScale('x', { min, max });
            syncing = false;
          },
        ],
        setCursor: [(u) => onhover?.(u.cursor.idx ?? null)],
      },
    };
  }

  /** Repères verticaux (résonances) et horizontaux, dessinés sous les courbes. */
  function guides(u: uPlot, vertical: number[], horizontal: number[], scale = 'y') {
    const ctx = u.ctx;
    const { left, top, width, height } = u.bbox;
    ctx.save();
    ctx.strokeStyle = C.guide;
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    for (const f of vertical) {
      const x = u.valToPos(f, 'x', true);
      if (x < left || x > left + width) continue;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke();
    }
    for (const v of horizontal) {
      const y = u.valToPos(v, scale, true);
      if (y < top || y > top + height) continue;
      ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + width, y); ctx.stroke();
    }
    ctx.restore();
  }

  function build() {
    for (const c of charts) c.destroy();
    charts = [];
    if (!points.length || !wrap) return;
    C = palette();

    const f = points.map((p) => p.frequency_mhz);
    const swr = points.map((p) => p.swr);
    const finite = swr.filter((s): s is number => s != null);
    const swrTop = Math.min(Math.max(3, Math.max(...finite, 1) * 1.05), 10);

    // 1. ROS : bandes 2 et 1,5 grisées, seuils en pointillé
    charts.push(
      new uPlot(
        {
          ...common(),
          title: `ROS (Z0 = ${summary.z0} Ω)`,
          scales: { x: { time: false }, y: { range: [1, swrTop] } },
          axes: axes('ROS'),
          series: [
            { label: 'f (MHz)', value: fmt(3) },
            { label: 'ROS', stroke: C.swr, width: 2, value: fmt(2), points: dots() },
          ],
          hooks: {
            ...common().hooks,
            drawAxes: [
              (u) => {
                const ctx = u.ctx;
                const { top, height } = u.bbox;
                for (const b of summary.bands) {
                  const x1 = u.valToPos(b.low_mhz, 'x', true);
                  const x2 = u.valToPos(b.high_mhz, 'x', true);
                  ctx.fillStyle = b.threshold === 2 ? C.band2 : C.band15;
                  ctx.fillRect(x1, top, x2 - x1, height);
                }
                guides(u, [], [2, 1.5]);
              },
            ],
          },
        },
        [f, swr],
        swrEl,
      ),
    );

    // 2. R et X : zéro de X et résonances repérés
    charts.push(
      new uPlot(
        {
          ...common(),
          title: 'Impédance',
          axes: axes('Ω'),
          series: [
            { label: 'f (MHz)', value: fmt(3) },
            { label: 'R (Ω)', stroke: C.r, width: 2, value: fmt(1), points: dots() },
            { label: 'X (Ω)', stroke: C.x, width: 2, value: fmt(1), points: dots() },
          ],
          hooks: { ...common().hooks, drawAxes: [(u) => guides(u, summary.resonances, [0])] },
        },
        [f, points.map((p) => p.r), points.map((p) => p.x)],
        rxEl,
      ),
    );

    // 3. Gain avant et AV/AR (si une direction a été suivie)
    if (hasGain && gainEl) {
      charts.push(
        new uPlot(
          {
            ...common(),
            title: 'Gain et rapport avant/arrière (direction du lobe à la fréquence du diagramme)',
            scales: { x: { time: false }, y: {}, fb: {} },
            axes: axes('dBi', {
              scale: 'fb',
              side: 1,
              label: 'AV/AR (dB)',
              size: 52,
              stroke: C.fb,
              grid: { show: false },
              ticks: { stroke: C.grid, width: 1 },
            }),
            series: [
              { label: 'f (MHz)', value: fmt(3) },
              { label: 'Gain (dBi)', stroke: C.gain, width: 2, value: fmt(2), points: dots() },
              { label: 'AV/AR (dB)', stroke: C.fb, width: 2, scale: 'fb', value: fmt(1), points: dots() },
            ],
          },
          [f, points.map((p) => p.gain_db), points.map((p) => p.front_to_back_db)],
          gainEl,
        ),
      );
    }
  }

  onMount(() => {
    const observer = new ResizeObserver(() => {
      const w = Math.max(wrap.clientWidth, 300);
      for (const c of charts) c.setSize({ width: w, height: HEIGHT });
    });
    observer.observe(wrap);
    return () => {
      observer.disconnect();
      for (const c of charts) c.destroy();
      charts = [];
    };
  });

  // Reconstruit les courbes à chaque nouveau résultat
  $effect(() => {
    void points;
    void summary;
    void hasGain;
    void theme.version; // changement de thème : on redessine
    build();
  });
</script>

<div class="charts" bind:this={wrap}>
  <div bind:this={swrEl}></div>
  <div bind:this={rxEl}></div>
  {#if hasGain}<div bind:this={gainEl}></div>{/if}
  <p class="hint">Tirer sur une plage pour zoomer, double-cliquer pour revenir.</p>
</div>

<style>
  .charts { width: 100%; }
  .charts :global(.u-title) { font-size: 12px; font-weight: 500; text-align: left; opacity: 0.85; }
  .charts :global(.u-legend) { font-size: 11px; color: inherit; text-align: left; }
  .charts :global(.u-legend .u-marker) { width: 10px; height: 3px; }
  .charts :global(.u-select) { background: color-mix(in srgb, var(--accent) 15%, transparent); }
  .charts :global(.uplot) { margin-bottom: 10px; }
  .hint { font-size: 11px; opacity: 0.6; margin: 0; }
</style>
