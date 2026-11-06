<script lang="ts">
  // Symboles 4NEC2 (cartes SY) : nom = nombre ou formule. Les valeurs affichées sont celles
  // calculées par onec (via /validate) ; rien n'est évalué dans le navigateur.
  import type { RowMark, SymbolRow } from '../state/model';

  let {
    symbols = $bindable(),
    values = {},
    marks = {},
    focus = [],
  }: {
    symbols: SymbolRow[];
    values?: Record<string, number>;
    marks?: Record<number, RowMark>;
    focus?: number[];
  } = $props();

  function add() {
    const used = new Set(symbols.map((s) => s.name.toLowerCase()));
    let k = 1;
    while (used.has(`s${k}`)) k++;
    symbols.push({ name: `s${k}`, formula: '1' });
  }

  const shown = (v: number | undefined) => (v === undefined ? '…' : String(+v.toPrecision(6)));
</script>

{#if symbols.length}
  <div class="scroll">
    <table>
      <thead>
        <tr><th>#</th><th>nom</th><th>formule</th><th>valeur</th><th></th></tr>
      </thead>
      <tbody>
        {#each symbols as sym, i (i)}
          {@const mark = marks[i]}
          <tr class={mark ? `sev-${mark.severity}` : ''} class:focus={focus.includes(i)} title={mark?.text ?? ''}>
            <td class="num">{i + 1}</td>
            <td><input class="name" bind:value={sym.name} spellcheck="false" autocomplete="off" aria-label={`nom du symbole ${i + 1}`} /></td>
            <td><input class="formula" bind:value={sym.formula} spellcheck="false" autocomplete="off" aria-label={`formule du symbole ${sym.name}`} /></td>
            <td class="num">{shown(values[sym.name.trim()])}</td>
            <td><button type="button" class="del" onclick={() => symbols.splice(i, 1)} aria-label={`supprimer le symbole ${sym.name}`}>✕</button></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}
<div class="below">
  <button type="button" onclick={add}>+ symbole</button>
  <span class="hint">
    Symbole = nombre (« 12 ») ou formule (« 142.5/f »), cité dans les cases des fils. Fonctions
    d'onec : sin, cos, tan en degrés, sqr, sqrt, pow, abs, log, exp… Un symbole doit être défini
    avant d'être utilisé.
  </span>
</div>

<style>
  .scroll { overflow: auto; max-height: 220px; }
  table { border-collapse: collapse; font-size: 11px; }
  thead th { position: sticky; top: 0; background: var(--bg); z-index: 1; font-weight: 500; opacity: 0.7; padding: 2px 3px; }
  td { padding: 1px 1px; }
  td.num { text-align: right; opacity: 0.8; padding: 0 6px; font-variant-numeric: tabular-nums; }
  input { padding: 3px 4px; font-size: 11px; font-family: ui-monospace, monospace; }
  input.name { width: 70px; }
  input.formula { width: 170px; color: var(--formula); }
  tr.sev-error td:first-child { box-shadow: inset 3px 0 var(--error); }
  tr.sev-error input { border-color: color-mix(in srgb, var(--error) 60%, transparent); }
  tr.sev-warning td:first-child { box-shadow: inset 3px 0 var(--warn); }
  tr.focus td { background: color-mix(in srgb, var(--accent) 18%, transparent); }
  .del { background: transparent; color: inherit; opacity: 0.6; padding: 2px 6px; }
  .del:hover { opacity: 1; color: var(--error); }
  .below { display: flex; gap: 12px; align-items: center; margin-top: 6px; }
  .below button { white-space: nowrap; flex: none; }
  .hint { font-size: 11px; opacity: 0.6; }
</style>
