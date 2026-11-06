<script lang="ts">
  // Vue 3D de la géométrie (Three.js). Repère NEC : Z vers le haut, sol dans le plan z = 0.
  // Rendu à la demande (pas de boucle d'animation) : on ne redessine que si quelque chose change.
  import { onMount } from 'svelte';
  import * as THREE from 'three';
  import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
  import type { GroundKind } from '../api/client';
  import {
    feedLocation,
    rowEnd,
    rowError,
    rowStart,
    type Feed,
    type RowMark,
    type WireRow,
  } from '../state/model';
  import { colorHex, theme } from '../state/theme.svelte';

  let {
    rows,
    feed,
    ground,
    fitKey = 0,
    marks = {},
    focus = [],
  }: {
    rows: WireRow[];
    feed: Feed;
    ground: GroundKind;
    fitKey?: number;
    marks?: Record<number, RowMark>; // contrôle du modèle : fils colorés selon la gravité
    focus?: number[]; // fils de la remarque survolée
  } = $props();

  let container: HTMLDivElement;
  let renderer: THREE.WebGLRenderer | undefined;
  let camera: THREE.PerspectiveCamera;
  let controls: OrbitControls;
  const scene = new THREE.Scene();
  const dynamic = new THREE.Group(); // tout ce qui dépend du modèle, reconstruit à chaque changement
  scene.add(dynamic);

  // Couleurs du thème courant (Three.js ne lit pas les variables CSS) : relues à chaque rebuild
  const palette = () => ({
    wire: colorHex('wire'),
    node: colorHex('node'),
    feed: colorHex('warn'),
    grid: colorHex('grid3d'),
    gridCenter: colorHex('grid3d-center'),
    error: colorHex('error'),
    warning: colorHex('warn'),
    focus: colorHex('focus'),
    canvas: colorHex('canvas'),
  });
  let COLORS = palette();

  function wireColor(i: number): number {
    if (focus.includes(i)) return COLORS.focus;
    const sev = marks[i]?.severity;
    return sev === 'error' ? COLORS.error : sev === 'warning' ? COLORS.warning : COLORS.wire;
  }

  function render() {
    if (renderer) renderer.render(scene, camera);
  }

  /** Lignes utilisables (les lignes en erreur sont ignorées plutôt que de casser la vue). */
  function validRows() {
    return rows.map((r, i) => ({ r, i })).filter(({ r }) => !rowError(r));
  }

  function bounds(): THREE.Box3 {
    const box = new THREE.Box3();
    for (const { r } of validRows()) {
      box.expandByPoint(new THREE.Vector3(...rowStart(r)));
      box.expandByPoint(new THREE.Vector3(...rowEnd(r)));
    }
    if (box.isEmpty()) box.set(new THREE.Vector3(-5, -5, 0), new THREE.Vector3(5, 5, 10));
    if (ground !== 'free') box.expandByPoint(new THREE.Vector3(box.min.x, box.min.y, 0));
    return box;
  }

  function clearDynamic() {
    for (const obj of [...dynamic.children]) {
      dynamic.remove(obj);
      obj.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose();
        const mat = m.material as THREE.Material | THREE.Material[] | undefined;
        (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((x) => x.dispose());
      });
    }
  }

  function rebuild() {
    COLORS = palette();
    renderer?.setClearColor(COLORS.canvas);
    clearDynamic();
    const valid = validRows();
    const box = bounds();
    const size = Math.max(box.getSize(new THREE.Vector3()).length(), 1);

    // Fils et limites de segments
    const lines = new Map<number, number[]>(); // couleur → segments de fils
    const nodes: number[] = [];
    for (const { r, i } of valid) {
      const a = rowStart(r);
      const b = rowEnd(r);
      const color = wireColor(i);
      if (!lines.has(color)) lines.set(color, []);
      lines.get(color)!.push(...a, ...b);
      const n = r.segments ?? 1;
      for (let k = 0; k <= n; k++) {
        const t = k / n;
        nodes.push(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t);
      }
    }
    for (const [color, positions] of lines) {
      const lineGeo = new THREE.BufferGeometry();
      lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      dynamic.add(new THREE.LineSegments(lineGeo, new THREE.LineBasicMaterial({ color })));
    }
    const nodeGeo = new THREE.BufferGeometry();
    nodeGeo.setAttribute('position', new THREE.Float32BufferAttribute(nodes, 3));
    dynamic.add(
      new THREE.Points(nodeGeo, new THREE.PointsMaterial({ color: COLORS.node, size: 3, sizeAttenuation: false })),
    );

    // Point d'alimentation : centre du segment alimenté (numérotation NEC par tag)
    const loc = feedLocation(rows, feed);
    const fed = loc ? rows[loc.row] : undefined;
    if (loc && fed && !rowError(fed)) {
      const n = fed.segments ?? 1;
      const a = rowStart(fed);
      const b = rowEnd(fed);
      const t = (loc.index + 0.5) / n;
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(size * 0.012, 16, 12),
        new THREE.MeshBasicMaterial({ color: COLORS.feed }),
      );
      marker.position.set(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t);
      dynamic.add(marker);
    }

    // Sol : grille dans le plan z = 0 (GridHelper est dans XZ : on le couche)
    if (ground !== 'free') {
      const center = box.getCenter(new THREE.Vector3());
      const extent = Math.ceil(Math.max(box.max.x - box.min.x, box.max.y - box.min.y, 10) * 1.6);
      const grid = new THREE.GridHelper(extent, Math.min(extent, 40), COLORS.gridCenter, COLORS.grid);
      grid.rotation.x = Math.PI / 2;
      grid.position.set(center.x, center.y, 0);
      dynamic.add(grid);
    }

    // Axes à l'origine : X rouge, Y vert, Z bleu
    dynamic.add(new THREE.AxesHelper(size * 0.15));
    render();
  }

  export function fit() {
    if (!renderer) return;
    const box = bounds();
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(box.getBoundingSphere(new THREE.Sphere()).radius, 1);
    const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.05;
    // vue de trois quarts, depuis l'avant-droite et un peu au-dessus
    const dir = new THREE.Vector3(1, -1.3, 0.7).normalize();
    camera.position.copy(center).addScaledVector(dir, dist);
    camera.near = dist / 100;
    camera.far = dist * 100;
    camera.updateProjectionMatrix();
    controls.target.copy(center);
    controls.update();
    render();
  }

  onMount(() => {
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setClearColor(COLORS.canvas);
    container.appendChild(renderer.domElement);

    camera = new THREE.PerspectiveCamera(40, 1, 0.1, 1000);
    camera.up.set(0, 0, 1);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.addEventListener('change', render);

    const resize = () => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (!w || !h || !renderer) return;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      render();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();
    rebuild();
    fit();

    return () => {
      observer.disconnect();
      controls.dispose();
      clearDynamic();
      renderer?.dispose();
      renderer?.domElement.remove();
      renderer = undefined;
    };
  });

  // Reconstruit la scène dès que le modèle change (lecture profonde des lignes)
  $effect(() => {
    JSON.stringify(rows);
    JSON.stringify(marks);
    JSON.stringify(focus);
    void feed.tag;
    void feed.segment;
    void ground;
    void theme.version; // changement de thème : nouvelles couleurs
    if (renderer) rebuild();
  });

  // Recadre quand on charge un autre modèle
  $effect(() => {
    void fitKey;
    if (renderer) fit();
  });
</script>

<div class="view" bind:this={container}>
  <div class="overlay">
    <span><i class="x"></i>X</span><span><i class="y"></i>Y</span><span><i class="z"></i>Z</span>
    <span><i class="f"></i>alimentation</span>
    <button type="button" onclick={fit}>Recadrer</button>
  </div>
</div>

<style>
  .view { position: relative; width: 100%; height: 340px; border-radius: 6px; overflow: hidden; border: 1px solid var(--border); }
  .view :global(canvas) { display: block; }
  .overlay { position: absolute; top: 6px; left: 8px; right: 8px; display: flex; gap: 12px; align-items: center; font-size: 11px; opacity: 0.85; pointer-events: none; }
  .overlay button { margin-left: auto; pointer-events: auto; padding: 3px 10px; font-size: 11px; }
  i { display: inline-block; width: 10px; height: 3px; margin-right: 4px; vertical-align: middle; }
  .x { background: #ff4040; } .y { background: #40ff40; } .z { background: #4080ff; }
  .f { background: var(--warn); height: 8px; width: 8px; border-radius: 50%; }
</style>
