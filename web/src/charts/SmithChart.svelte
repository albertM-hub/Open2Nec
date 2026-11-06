<script lang="ts">
  // Abaque de Smith (SVG) : trajectoire du coefficient de réflexion Γ fourni par l'API pour Z0.
  // Les cercles de la grille sont du dessin (géométrie de l'abaque), pas un calcul d'antenne.
  import type { SweepPoint } from '../api/client';

  let {
    points,
    z0,
    hover = null,
    onhover,
  }: {
    points: SweepPoint[];
    z0: number;
    hover?: number | null;
    onhover?: (index: number | null) => void;
  } = $props();

  const R_CIRCLES = [0.2, 0.5, 1, 2, 5]; // résistance normalisée r = R / Z0
  const X_ARCS = [0.2, 0.5, 1, 2, 5]; // réactance normalisée x = X / Z0
  const SWR_CIRCLES = [2, 1.5];

  // Repère SVG : Γ = 1 à droite, partie imaginaire vers le haut (y inversé)
  const px = (re: number) => re * 100;
  const py = (im: number) => -im * 100;

  let path = $derived(
    points.map((p, i) => `${i ? 'L' : 'M'}${px(p.gamma_re).toFixed(2)},${py(p.gamma_im).toFixed(2)}`).join(' '),
  );
  let current = $derived(hover != null ? points[hover] : null);
  const first = $derived(points[0]);
  const last = $derived(points.at(-1));

  function nearest(e: PointerEvent) {
    const svg = e.currentTarget as SVGSVGElement;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM()?.inverse());
    let best = -1;
    let dmin = 12; // tolérance en unités SVG
    points.forEach((q, i) => {
      const d = Math.hypot(px(q.gamma_re) - p.x, py(q.gamma_im) - p.y);
      if (d < dmin) {
        dmin = d;
        best = i;
      }
    });
    onhover?.(best >= 0 ? best : null);
  }

  const swrRadius = (s: number) => ((s - 1) / (s + 1)) * 100;
  const signed = (x: number) => (x >= 0 ? `+ j${x.toFixed(1)}` : `− j${(-x).toFixed(1)}`);
</script>

<figure>
  <figcaption>Abaque de Smith (normalisée à {z0} Ω)</figcaption>
  <svg
    viewBox="-112 -112 224 224"
    role="img"
    aria-label="Abaque de Smith"
    onpointermove={nearest}
    onpointerleave={() => onhover?.(null)}
  >
    <defs><clipPath id="smith-clip"><circle r="100" /></clipPath></defs>
    <g clip-path="url(#smith-clip)" class="grid">
      {#each R_CIRCLES as r}
        <circle cx={px(r / (1 + r))} cy="0" r={100 / (1 + r)} />
      {/each}
      {#each X_ARCS as x}
        <circle cx="100" cy={py(1 / x)} r={100 / x} />
        <circle cx="100" cy={py(-1 / x)} r={100 / x} />
      {/each}
      <line x1="-100" y1="0" x2="100" y2="0" />
    </g>
    <circle r="100" class="outer" />
    {#each SWR_CIRCLES as s}
      <circle r={swrRadius(s)} class="swr" />
      <text x="2" y={-swrRadius(s) - 2} class="label swrlabel">ROS {s}</text>
    {/each}
    {#each R_CIRCLES as r}
      <text x={px((r - 1) / (r + 1)) + 1} y="-2" class="label">{r}</text>
    {/each}
    <path d={path} class="trace" />
    {#if first}<circle cx={px(first.gamma_re)} cy={py(first.gamma_im)} r="2.5" class="start" />{/if}
    {#if last}<circle cx={px(last.gamma_re)} cy={py(last.gamma_im)} r="2.5" class="end" />{/if}
    {#if current}
      <circle cx={px(current.gamma_re)} cy={py(current.gamma_im)} r="4" class="hover" />
    {/if}
  </svg>
  <p class="readout">
    {#if current}
      {current.frequency_mhz.toFixed(3)} MHz : Z = {current.r.toFixed(1)} {signed(current.x)} Ω,
      ROS {current.swr?.toFixed(2) ?? '∞'}
    {:else if first && last}
      <span class="dot start"></span>{first.frequency_mhz.toFixed(3)} MHz →
      <span class="dot end"></span>{last.frequency_mhz.toFixed(3)} MHz ; survoler pour lire
    {/if}
  </p>
</figure>

<style>
  figure { margin: 0; max-width: 340px; flex: 1 1 260px; }
  figcaption { font-size: 12px; opacity: 0.85; margin-bottom: 4px; }
  svg { width: 100%; display: block; touch-action: none; }
  .grid circle, .grid line { fill: none; stroke: currentColor; stroke-opacity: 0.14; stroke-width: 0.6; }
  .outer { fill: none; stroke: currentColor; stroke-opacity: 0.4; stroke-width: 0.8; }
  .swr { fill: color-mix(in srgb, var(--ok) 6%, transparent); stroke: var(--ok); stroke-opacity: 0.6; stroke-dasharray: 3 3; stroke-width: 0.7; }
  .label { font-size: 6px; fill: currentColor; opacity: 0.5; }
  .swrlabel { fill: var(--ok); opacity: 0.8; }
  .trace { fill: none; stroke: var(--accent); stroke-width: 1.6; stroke-linejoin: round; }
  .start { fill: var(--ok); }
  .end { fill: var(--series-2); }
  .hover { fill: var(--warn); stroke: var(--bg); stroke-width: 1; }
  .readout { font-size: 11px; opacity: 0.8; margin: 4px 0 0; min-height: 1.4em; font-variant-numeric: tabular-nums; }
  .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin: 0 3px; }
  .dot.start { background: var(--ok); }
  .dot.end { background: var(--series-2); }
</style>
