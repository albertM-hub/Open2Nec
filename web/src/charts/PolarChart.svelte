<script lang="ts">
  // Diagramme polaire SVG d'une coupe de rayonnement, échelle en dB relative au gain max
  // (de -30 dB au centre jusqu'au maximum sur le cercle extérieur), comme 4NEC2.
  //  - azimut : 0° (axe +X) en haut, angles croissants vers la gauche (+Y), vue de dessus ;
  //  - élévation : horizon avant à droite, zénith en haut, horizon arrière à gauche.
  import type { CutPoint } from '../api/client';

  let {
    points,
    kind,
    title,
    gmax,
    marker,
    hemisphere = false,
  }: {
    points: CutPoint[];
    kind: 'azimuth' | 'elevation';
    title: string;
    gmax: number;
    marker: number; // angle du maximum, mis en évidence
    hemisphere?: boolean; // élévation au-dessus d'un sol : demi-cercle supérieur seulement
  } = $props();

  const RANGE_DB = 30;
  // Étiquettes dB le long d'un rayon oblique, entre deux rayons gradués, pour ne rien masquer
  const LABEL_ANGLE = { azimuth: 345, elevation: 75 } as const;
  const RINGS = [0, -3, -10, -20]; // dB sous le maximum
  const R = 110;
  const W = 260;
  const cx = W / 2;
  let H = $derived(hemisphere ? R + 40 : W);
  let cy = $derived(hemisphere ? R + 22 : W / 2);

  const radius = (g: number) => R * Math.min(1, Math.max(0, (g - (gmax - RANGE_DB)) / RANGE_DB));

  function xy(angle: number, r: number): [number, number] {
    const a = (angle * Math.PI) / 180;
    return kind === 'azimuth'
      ? [cx - r * Math.sin(a), cy - r * Math.cos(a)]
      : [cx + r * Math.cos(a), cy - r * Math.sin(a)];
  }

  let path = $derived.by(() => {
    if (!points.length) return '';
    const pts = points.map((p) => xy(p.angle, radius(p.gain_db)));
    const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    // demi-cercle : on referme par le centre ; cercle complet : on referme simplement
    return hemisphere ? `${d} L${cx},${cy} Z` : `${d} Z`;
  });

  let spokes = $derived(
    (hemisphere ? [0, 30, 60, 90, 120, 150, 180] : [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]).map(
      (a) => ({ a, end: xy(a, R), label: xy(a, R + 12) }),
    ),
  );

  let markerEnd = $derived(xy(marker, R));
  // Élévation : on affiche l'angle au-dessus de l'horizon, côté avant comme côté arrière
  // (120° → 60°, 300° → -60° en espace libre)
  function fmtAngle(a: number): string {
    if (kind === 'azimuth') return `${a}°`;
    const n = ((((a + 90) % 360) + 360) % 360) - 90; // ramené dans [-90°, 270°)
    return `${n > 90 ? 180 - n : n}°`;
  }
</script>

<figure>
  <figcaption>{title}</figcaption>
  <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
    {#each RINGS as ring}
      {@const r = radius(gmax + ring)}
      {#if hemisphere}
        <path d={`M${cx - r},${cy} A${r},${r} 0 0 1 ${cx + r},${cy}`} class="ring" />
      {:else}
        <circle {cx} {cy} {r} class="ring" />
      {/if}
      {@const at = xy(LABEL_ANGLE[kind], r)}
      <text x={at[0] + 2} y={at[1] - 2} class="ringlabel">{ring} dB</text>
    {/each}
    {#each spokes as s}
      <line x1={cx} y1={cy} x2={s.end[0]} y2={s.end[1]} class="spoke" />
      <text x={s.label[0]} y={s.label[1] + 3} text-anchor="middle" class="anglelabel">{fmtAngle(s.a)}</text>
    {/each}
    {#if hemisphere}<line x1={cx - R} y1={cy} x2={cx + R} y2={cy} class="horizon" />{/if}
    <path d={path} class="lobe" />
    <line x1={cx} y1={cy} x2={markerEnd[0]} y2={markerEnd[1]} class="marker" />
  </svg>
</figure>

<style>
  figure { margin: 0; flex: 1 1 240px; max-width: 340px; }
  figcaption { font-size: 12px; opacity: 0.8; margin-bottom: 4px; }
  svg { width: 100%; display: block; }
  .ring { fill: none; stroke: currentColor; opacity: 0.18; }
  .spoke { stroke: currentColor; opacity: 0.1; }
  .horizon { stroke: currentColor; opacity: 0.35; }
  .ringlabel { font-size: 8px; fill: currentColor; opacity: 0.5; }
  .anglelabel { font-size: 9px; fill: currentColor; opacity: 0.6; }
  .lobe { fill: color-mix(in srgb, var(--accent) 25%, transparent); stroke: var(--accent); stroke-width: 1.5; stroke-linejoin: round; }
  .marker { stroke: var(--warn); stroke-width: 1.2; stroke-dasharray: 3 3; }
</style>
