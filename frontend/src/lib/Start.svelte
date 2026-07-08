<script>
  import { onMount } from 'svelte'
  import { getHealth, listCampaigns, deleteCampaign } from './api.js'
  import { t } from './i18n.svelte.js'

  // Title screen. Continue lists saves; Novo Jogo runs onboarding then creation.
  let { onopen, onsettings, ontutorial, oncredits, onreconnect } = $props()

  let health = $state(null)
  let campaigns = $state([])
  let loading = $state(true)
  let error = $state(null)
  let confirmDeleteId = $state(null)
  let deleting = $state(false)

  async function refresh() {
    loading = true
    error = null
    try {
      health = await getHealth()
      campaigns = await listCampaigns()
    } catch (e) {
      error = String(e)
    } finally {
      loading = false
    }
  }

  function novaCampanha() {
    // Campaign is seeded only once the sheet is confirmed; here we just navigate.
    error = null
    onopen(null, true)
  }

  async function confirmarApagar(id) {
    deleting = true
    try {
      await deleteCampaign(id)
      campaigns = campaigns.filter((c) => c.id !== id)
      confirmDeleteId = null
    } catch (e) {
      error = String(e)
    } finally {
      deleting = false
    }
  }

  const proxyOk = $derived(health?.proxy?.reachable)
  const authPresent = $derived(health?.proxy?.auth_present)
  const dbOk = $derived(health?.db?.ok)

  onMount(refresh)
</script>

<div class="titlebg"></div>
<div class="scrim"></div>

<main class="title">
  <header class="hero">
    <img class="logo" src="/title-screen/logo.jpg" alt="ONE PIECE" />
    <p class="kicker">{t('start.kicker')}</p>
  </header>

  {#if health && (!proxyOk || !authPresent)}
    <!-- Actionable banner when auth/proxy is down; reopens the repair wizard. -->
    <div class="banner">
      <span>{t('start.disconnected')}</span>
      <button class="ghost" onclick={onreconnect}>{t('start.reconnect')}</button>
    </div>
  {/if}

  <section class="panel glass">
    {#if error}<p class="line down">{error}</p>{/if}

    <div class="actions">
        <button class="primary big" onclick={novaCampanha} disabled={!dbOk}>
          {t('start.new_game')}
        </button>
        <button class="big" onclick={onsettings}>{t('start.settings')}</button>
        <button class="big" onclick={ontutorial} data-testid="tutorial">{t('start.tutorial')}</button>
        <button class="big" onclick={oncredits}>{t('start.credits')}</button>
      </div>

      <div class="campaigns">
        <h3>{t('start.continue')}</h3>
        {#if loading}
          <p class="hint">{t('common.loading')}</p>
        {:else if campaigns.length === 0}
          <p class="hint">{t('start.no_campaigns')}</p>
        {:else}
          <ul class="camp-list">
            {#each campaigns as c (c.id)}
              <li>
                {#if confirmDeleteId === c.id}
                  <div class="confirm">
                    <span>{t('start.delete_confirm', { name: c.name })}</span>
                    <button class="danger" onclick={() => confirmarApagar(c.id)} disabled={deleting}>
                      {deleting ? '…' : t('start.delete')}
                    </button>
                    <button class="ghost" onclick={() => (confirmDeleteId = null)}>{t('common.cancel')}</button>
                  </div>
                {:else}
                  <button class="camp" onclick={() => onopen(c.id)}>
                    <span class="camp-line">
                      <span class="camp-name">{c.name}</span>
                      <span class="camp-lang">{c.language === 'en' ? 'EN' : 'PT-BR'}</span>
                    </span>
                    <span class="camp-arc">{c.current_arc ?? ''}</span>
                  </button>
                  <button class="x ghost" title={t('start.delete_title')} onclick={() => (confirmDeleteId = c.id)}>✕</button>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </div>
  </section>
</main>

<style>
  /* Fixed full-viewport background art behind the centered content. */
  /* z-index 0 (not negative): the opaque body background would paint over negative layers. */
  .titlebg {
    position: fixed;
    inset: 0;
    background: url('/title-screen/background.png') center/cover no-repeat;
    z-index: 0;
  }
  /* Minimal scrim: elliptical shadow behind the central panel. */
  .scrim {
    position: fixed;
    inset: 0;
    background: radial-gradient(720px 560px at 50% 58%, rgba(0, 0, 0, 0.55) 0%, transparent 72%);
    z-index: 0;
  }
  main.title {
    position: relative;
    z-index: 1;
  }
  /* Light theme inverts the monochrome art. */
  :global(:root[data-theme='light']) .titlebg {
    filter: invert(1);
    opacity: 0.92;
  }
  :global(:root[data-theme='light']) .scrim {
    background: radial-gradient(720px 560px at 50% 58%, rgba(255, 255, 255, 0.6) 0%, transparent 72%);
  }

  .hero {
    text-align: center;
    margin-bottom: 1.6rem;
  }
  .logo {
    width: min(380px, 72%);
    height: auto;
    mix-blend-mode: screen;
    filter: drop-shadow(0 8px 32px rgba(0, 0, 0, 0.8));
  }
  /* Light theme inverts the logo and multiplies its white backing into the page. */
  :global(:root[data-theme='light']) .logo {
    mix-blend-mode: multiply;
    filter: invert(1);
  }
  .hero .kicker {
    margin-top: 0.6rem;
  }

  .glass {
    background: color-mix(in srgb, var(--bg-raised) 78%, transparent);
    backdrop-filter: blur(14px) saturate(1.1);
    box-shadow: var(--shadow-3);
  }

  .actions {
    display: flex;
    justify-content: center;
    gap: 0.75rem;
    margin-bottom: 0.5rem;
  }
  .big {
    padding: 0.55rem 1.5rem;
    font-size: 0.86rem;
  }

  .campaigns {
    margin-top: 1.4rem;
    border-top: 1px solid var(--line);
    padding-top: 1rem;
  }
  .camp-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.35rem;
  }
  .camp-list li {
    display: flex;
    gap: 0.3rem;
    align-items: stretch;
  }
  .camp {
    flex: 1;
    min-width: 0;
    text-align: left;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.15rem;
    padding: 0.55rem 0.8rem;
    font-size: 0.88rem;
    color: var(--ink);
    background: transparent;
    border-color: transparent;
  }
  .camp:hover:not(:disabled) {
    background: var(--bg-hover);
    border-color: var(--line);
  }
  .camp-line {
    display: flex;
    align-items: baseline;
    gap: 0.45rem;
    min-width: 0;
  }
  .camp-name {
    font-weight: 550;
    letter-spacing: -0.01em;
  }
  .camp-lang {
    flex: none;
    font-size: 0.58rem;
    font-weight: 550;
    letter-spacing: 0.08em;
    color: var(--ink-dim);
    border: 1px solid var(--line-strong);
    border-radius: 4px;
    padding: 0.06rem 0.3rem;
  }
  .camp-arc {
    font-size: 0.72rem;
    color: var(--ink-dim);
  }
  .x {
    padding: 0 0.55rem;
    font-size: 0.78rem;
  }
  .x:hover:not(:disabled) {
    color: var(--down);
    background: var(--down-soft);
  }
  .confirm {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.45rem 0.7rem;
    border: 1px solid var(--down);
    border-radius: var(--radius-sm);
    background: var(--down-soft);
    font-size: 0.82rem;
    color: var(--ink);
  }
  .confirm span {
    flex: 1;
  }

  /* Reconnect banner shown when auth/proxy is down. */
  .banner {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 0.8rem;
    margin: 0 auto 0.8rem;
    padding: 0.45rem 0.9rem;
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--warn) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--warn) 35%, transparent);
    color: var(--warn);
    font-size: 0.8rem;
    width: fit-content;
  }
</style>
