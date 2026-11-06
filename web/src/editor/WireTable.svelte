<script lang="ts">
  import CellInput from './CellInput.svelte';
  import {
    centerSegment,
    COORDS,
    isFormula,
    newRow,
    rowError,
    tagSegments,
    wireLength,
    type Cell,
    type Feed,
    type RowMark,
    type WireRow,
  } from '../state/model';

  let {
    rows = $bindable(),
    feed = $bindable(),
    marks = {},
    focus = [],
    resolved = null,
  }: {
    rows: WireRow[];
    feed: Feed;
    marks?: Record<number, RowMark>;
    focus?: number[];
    resolved?: WireRow[] | null; // mêmes lignes en nombres (formules calculées par onec)
  } = $props();

  // Valeur calculée affichée sous une formule (6 chiffres significatifs, comme onec)
  const shown = (v: Cell | undefined) =>
    typeof v === 'number' ? String(+v.toPrecision(6)) : '…';

  function add() {
    rows.push(newRow(rows));
  }

  function remove(i: number) {
    rows.splice(i, 1);
    // plus aucun fil de ce tag : l'alimentation passe sur le premier fil
    if (!rows.some((r) => r.tag === feed.tag) && rows[0]?.tag != null)
      feed = { ...feed, tag: rows[0].tag, segment: null };
  }

  // Une seule pastille par tag : sur la première ligne qui le porte
  let firstOfTag = $derived(rows.map((r, i) => rows.findIndex((x) => x.tag === r.tag) === i));
  let fedSegments = $derived(tagSegments(rows, feed.tag));

  function lengthOf(i: number): string {
    const l = wireLength(resolved?.[i] ?? rows[i]);
    return Number.isFinite(l) ? l.toFixed(2) : '…';
  }
</script>

<div class="scroll">
  <table>
    <thead>
      <tr>
        <th title="ligne">#</th>
        <th title="numéro de fil NEC ; plusieurs lignes peuvent partager un tag">tag</th>
        <th title="fil alimenté">Alim.</th>
        <th>x1</th><th>y1</th><th>z1</th>
        <th>x2</th><th>y2</th><th>z2</th>
        <th>rayon</th>
        <th>seg.</th>
        <th>long.</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each rows as row, i (i)}
        {@const err = rowError(row)}
        {@const mark = marks[i]}
        <tr
          class:invalid={err}
          class:fed={row.tag === feed.tag}
          class:focus={focus.includes(i)}
          class={mark ? `sev-${mark.severity}` : ''}
          title={err ?? mark?.text ?? ''}
        >
          <td class="num">{i + 1}</td>
          <td><input type="number" step="1" min="1" class="seg" bind:value={row.tag} aria-label={`tag ligne ${i + 1}`} /></td>
          <td>
            {#if firstOfTag[i]}
              <input
                type="radio"
                name="feed"
                aria-label={`alimenter le fil de tag ${row.tag}`}
                checked={row.tag === feed.tag}
                onchange={() => {
                  if (row.tag != null) feed = { ...feed, tag: row.tag, segment: null };
                }}
              />
            {/if}
          </td>
          {#each [...COORDS, 'radius' as const] as c}
            <td>
              <CellInput bind:value={row[c]} label={`${c === 'radius' ? 'rayon' : c} ligne ${i + 1}`} />
              {#if isFormula(row[c])}<span class="val">= {shown(resolved?.[i]?.[c])}</span>{/if}
            </td>
          {/each}
          <td><input type="number" step="1" min="1" class="seg" bind:value={row.segments} aria-label={`segments ligne ${i + 1}`} /></td>
          <td class="num">{err ? '—' : lengthOf(i)}</td>
          <td>
            <button
              type="button"
              class="del"
              onclick={() => remove(i)}
              disabled={rows.length === 1}
              aria-label={`supprimer la ligne ${i + 1}`}>✕</button
            >
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<div class="below">
  <button type="button" onclick={add}>+ fil</button>
  <label class="inline">
    Segment alimenté (tag {feed.tag})
    <input
      type="number"
      min="1"
      max={fedSegments || undefined}
      step="1"
      class="seg"
      placeholder={fedSegments ? String(centerSegment(fedSegments)) : ''}
      value={feed.segment ?? ''}
      oninput={(e) => {
        const v = e.currentTarget.valueAsNumber;
        feed = { ...feed, segment: Number.isFinite(v) ? v : null };
      }}
    />
    <span class="hint">vide = centre{fedSegments ? ` (1 à ${fedSegments})` : ''}</span>
  </label>
  {#if feed.kind === 5 || feed.voltage_re !== 1 || feed.voltage_im !== 0}
    <span class="hint">source EX {feed.kind}, V = {feed.voltage_re} + j{feed.voltage_im} (reprise du fichier)</span>
  {/if}
</div>
<p class="hint">
  Cotes et rayon en mètres, ou formules à partir des symboles (« -L/2 », « h+0.5 ») ; la valeur
  calculée s'affiche dessous. Le sol est à z = 0 ; aucun fil ne doit y être posé à plat.
</p>

<style>
  .scroll { overflow: auto; max-height: 340px; }
  table { border-collapse: collapse; font-size: 11px; }
  thead th { position: sticky; top: 0; background: var(--bg); z-index: 1; }
  th { font-weight: 500; opacity: 0.7; padding: 2px 3px; text-align: center; }
  td { padding: 1px 1px; }
  td.num { text-align: right; opacity: 0.8; padding: 0 4px; font-variant-numeric: tabular-nums; }
  /* 5 décimales lisibles (cotes importées au 1/100 mm) ; flèches du champ masquées */
  input[type='number'] { width: 60px; padding: 3px 3px; font-size: 11px; font-variant-numeric: tabular-nums; -moz-appearance: textfield; appearance: textfield; }
  input[type='number']::-webkit-inner-spin-button { display: none; }
  input.seg { width: 36px; }
  td { vertical-align: top; }
  .val { display: block; font-size: 9.5px; opacity: 0.6; padding: 0 3px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  tr.fed td.num:first-child { color: var(--warn); opacity: 1; }
  tr.invalid :global(input) { border-color: var(--error); }
  tr.sev-error td:first-child { box-shadow: inset 3px 0 var(--error); }
  tr.sev-warning td:first-child { box-shadow: inset 3px 0 var(--warn); }
  tr.sev-info td:first-child { box-shadow: inset 3px 0 var(--accent); }
  tr.sev-error :global(input) { border-color: color-mix(in srgb, var(--error) 60%, transparent); }
  tr.focus td { background: color-mix(in srgb, var(--accent) 18%, transparent); }
  tr.invalid td.num:first-child { color: var(--error); }
  .del { background: transparent; color: inherit; opacity: 0.6; padding: 2px 6px; }
  .del:hover:not(:disabled) { opacity: 1; color: var(--error); }
  .below { display: flex; gap: 16px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
  .inline { flex-direction: row; align-items: center; gap: 6px; }
  .hint { font-size: 11px; opacity: 0.6; margin: 4px 0 0; }
</style>
