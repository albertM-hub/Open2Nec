<script lang="ts">
  // Cartes NEC conservées d'un fichier importé : lecture seule, renvoyées telles quelles à onec.
  import type { ExtraCard } from '../api/client';

  let { cards }: { cards: ExtraCard[] } = $props();
  let open = $state(true);
</script>

{#if cards.length}
  <details bind:open>
    <summary>Cartes conservées ({cards.length}) — lecture seule, transmises telles quelles au calcul</summary>
    <ul>
      {#each cards as c}
        <li>
          <span class="desc">{c.description}</span>
          <code>{c.text}</code>
        </li>
      {/each}
    </ul>
  </details>
{/if}

<style>
  details { margin-top: 12px; font-size: 12px; }
  summary { cursor: pointer; opacity: 0.85; }
  ul { list-style: none; padding: 0; margin: 6px 0 0; max-height: 200px; overflow: auto; }
  li { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 2px 12px; padding: 3px 0; border-bottom: 1px solid var(--border-soft); }
  code { opacity: 0.55; font-size: 11px; }
</style>
