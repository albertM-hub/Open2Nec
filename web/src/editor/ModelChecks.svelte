<script lang="ts">
  // Remarques du contrôle du modèle (calculées par le core via /validate).
  // Survoler une remarque met en évidence les fils concernés (tableau et vue 3D).
  import type { Issue } from '../api/client';

  let {
    issues,
    pending = false,
    unavailable = null,
    onfocus,
  }: {
    issues: Issue[];
    pending?: boolean;
    unavailable?: string | null;
    onfocus?: (rows: number[], symbols: number[]) => void;
  } = $props();

  const ICON = { error: '✖', warning: '⚠', info: 'ℹ' } as const;
  const count = (s: Issue['severity']) => issues.filter((i) => i.severity === s).length;
  let counts = $derived({ error: count('error'), warning: count('warning'), info: count('info') });

  function rows(i: Issue): string {
    const list = (n: number[], one: string, many: string) =>
      n.length
        ? `${n.length > 1 ? many : one} ${n.slice(0, 6).map((w) => w + 1).join(', ')}${n.length > 6 ? '…' : ''}`
        : '';
    return [list(i.wires, 'ligne', 'lignes'), list(i.symbols ?? [], 'symbole', 'symboles')]
      .filter(Boolean)
      .join(' · ');
  }
</script>

<section class="checks" aria-live="polite">
  <h2>
    Contrôle du modèle
    {#if pending}<span class="state">vérification…</span>
    {:else if unavailable}<span class="state">indisponible</span>
    {:else if !issues.length}<span class="state ok">✓ aucune remarque</span>
    {:else}
      <span class="state">
        {#if counts.error}<span class="error">{counts.error} erreur{counts.error > 1 ? 's' : ''}</span>{/if}
        {#if counts.warning}<span class="warning">{counts.warning} avertissement{counts.warning > 1 ? 's' : ''}</span>{/if}
        {#if counts.info}<span class="info">{counts.info} conseil{counts.info > 1 ? 's' : ''}</span>{/if}
      </span>
    {/if}
  </h2>
  {#if unavailable}<p class="hint">{unavailable}</p>{/if}
  {#if issues.length}
    <ul>
      {#each issues as issue}
        <li
          class={issue.severity}
          onmouseenter={() => onfocus?.(issue.wires, issue.symbols ?? [])}
          onmouseleave={() => onfocus?.([], [])}
        >
          <span class="icon" aria-label={issue.severity}>{ICON[issue.severity]}</span>
          <span class="msg">{issue.message}</span>
          {#if rows(issue)}<span class="rows">{rows(issue)}</span>{/if}
        </li>
      {/each}
    </ul>
    {#if counts.error}<p class="hint">Les erreurs bloquent le calcul : les corriger pour pouvoir simuler.</p>{/if}
  {/if}
</section>

<style>
  .checks { margin-top: 16px; }
  h2 { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; }
  .state { font-size: 12px; font-weight: 400; display: inline-flex; gap: 10px; opacity: 0.9; }
  .ok { color: var(--ok); }
  ul { list-style: none; padding: 0; margin: 0; max-height: 260px; overflow: auto; font-size: 12px; }
  li { display: grid; grid-template-columns: 18px 1fr auto; gap: 6px; padding: 5px 6px; border-left: 3px solid transparent; border-radius: 3px; cursor: default; }
  li:hover { background: var(--hover); }
  li.error { border-left-color: var(--error); }
  li.warning { border-left-color: var(--warn); }
  li.info { border-left-color: var(--accent); }
  .icon { text-align: center; }
  li.error .icon, .error { color: var(--error); }
  li.warning .icon, .warning { color: var(--warn); }
  li.info .icon, .info { color: var(--accent); }
  .rows { opacity: 0.6; white-space: nowrap; font-size: 11px; }
  .hint { font-size: 11px; opacity: 0.65; margin: 6px 0 0; }
</style>
