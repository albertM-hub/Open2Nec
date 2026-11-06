<script lang="ts">
  // Case de fil : nombre ou formule. Le texte tapé est gardé tel quel pendant la saisie
  // (« 1. » ne doit pas devenir « 1 » sous les doigts) ; la valeur est mise à jour à chaque frappe.
  import { cellText, isFormula, parseCell, type Cell } from '../state/model';

  let { value = $bindable(), label }: { value: Cell; label: string } = $props();

  let focused = $state(false);
  let text = $state('');
  $effect(() => {
    if (!focused) text = cellText(value); // modèle changé ailleurs (import, Appliquer…)
  });
</script>

<input
  type="text"
  class:formula={isFormula(value)}
  bind:value={text}
  oninput={() => (value = parseCell(text))}
  onfocus={() => (focused = true)}
  onblur={() => {
    focused = false;
    text = cellText(value);
  }}
  spellcheck="false"
  autocomplete="off"
  aria-label={label}
/>

<style>
  input { width: 60px; padding: 3px 3px; font-size: 11px; font-variant-numeric: tabular-nums; }
  input.formula { color: var(--formula); font-family: ui-monospace, monospace; }
</style>
