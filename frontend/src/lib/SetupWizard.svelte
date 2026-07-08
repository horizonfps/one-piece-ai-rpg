<script>
  import { onDestroy, onMount } from 'svelte'
  import { connectClaude, getHealth, updateSettings } from './api.js'
  import { t } from './i18n.svelte.js'

  // Setup wizard. 'full' runs welcome/connect/theme; 'repair' runs connect only.
  // OAuth lives in CLIProxyAPI; here we open the URL and poll auth_present via health.
  let { mode = 'full', health: initialHealth = null, oncomplete } = $props()

  let step = $state(mode === 'repair' ? 'connect' : 'welcome')
  let health = $state(initialHealth)
  let waiting = $state(false)
  let error = $state(null)
  let theme = $state('dark')
  let pollTimer = null
  let pollDeadline = 0

  const connected = $derived(Boolean(health?.proxy?.reachable && health?.proxy?.auth_present))

  // Re-fetch health on mount; the prop may be stale. Auto-skip connect when ready.
  onMount(async () => {
    try {
      health = await getHealth()
    } catch {
      /* keep the prop value */
    }
    if (step === 'connect' && connected) next()
  })

  function next() {
    stopPolling()
    waiting = false
    error = null
    if (mode === 'repair') {
      oncomplete()
      return
    }
    if (step === 'welcome') step = connected ? 'theme' : 'connect'
    else if (step === 'connect') step = 'theme'
  }

  async function abrirNavegador() {
    error = null
    try {
      const d = await connectClaude()
      window.open(d.auth_url, '_blank')
      waiting = true
      pollDeadline = Date.now() + 5 * 60_000 // covers the proxy's OAuth session window
      pollTimer = setInterval(checar, 2000)
    } catch (e) {
      error = String(e)
    }
  }

  async function checar() {
    if (Date.now() > pollDeadline) {
      stopPolling()
      waiting = false
      error = t('wizard.auth_timeout')
      return
    }
    try {
      health = await getHealth()
      if (health?.proxy?.reachable && health?.proxy?.auth_present) next()
    } catch {
      /* retry next tick */
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }
  onDestroy(stopPolling)

  // Live preview: applies theme on click; persists only on finish.
  function escolherTema(t) {
    theme = t
    document.documentElement.dataset.theme = t === 'dark' ? '' : t
  }

  async function finalizar() {
    error = null
    try {
      await updateSettings({ theme, setup_completed: true })
      oncomplete()
    } catch (e) {
      error = String(e)
    }
  }
</script>

<div class="titlebg"></div>
<div class="scrim"></div>

<main class="wizard">
  <img class="logo" src="/title-screen/logo.jpg" alt="ONE PIECE" />

  <section class="panel glass">
    {#if error}<p class="line down">{error}</p>{/if}

    {#if step === 'welcome'}
      <p class="copy">{t('wizard.welcome_copy')}</p>
      <button class="primary" onclick={next}>{t('wizard.start')}</button>
    {:else if step === 'connect'}
      <h2>{t('wizard.connect_title')}</h2>
      <p class="copy">{t('wizard.connect_copy')}</p>
      <button class="primary" onclick={abrirNavegador} disabled={waiting}>
        {t('wizard.open_browser')}
      </button>
      {#if waiting}
        <p class="hint"><span class="spin"></span> {t('wizard.waiting')}</p>
      {/if}
    {:else if step === 'theme'}
      <h2>{t('wizard.theme_title')}</h2>
      <div class="themes">
        <button
          class="theme-card dark"
          class:selected={theme === 'dark'}
          onclick={() => escolherTema('dark')}
        >
          <span class="swatch"></span><span class="swatch short"></span>
          {t('wizard.theme_dark')}{theme === 'dark' ? ' ✓' : ''}
        </button>
        <button
          class="theme-card light"
          class:selected={theme === 'light'}
          onclick={() => escolherTema('light')}
        >
          <span class="swatch"></span><span class="swatch short"></span>
          {t('wizard.theme_light')}{theme === 'light' ? ' ✓' : ''}
        </button>
      </div>
      <button class="primary" onclick={finalizar}>{t('wizard.finish')}</button>
    {/if}

    {#if mode === 'full'}
      <div class="dots">
        <span class:on={step === 'welcome'}></span>
        <span class:on={step === 'connect'}></span>
        <span class:on={step === 'theme'}></span>
      </div>
    {/if}
  </section>
</main>

<style>
  /* Shared visual language with the title screen. */
  .titlebg {
    position: fixed;
    inset: 0;
    background: url('/title-screen/background.png') center/cover no-repeat;
    z-index: 0;
  }
  .scrim {
    position: fixed;
    inset: 0;
    background: radial-gradient(720px 560px at 50% 58%, rgba(0, 0, 0, 0.55) 0%, transparent 72%);
    z-index: 0;
  }
  :global(:root[data-theme='light']) .titlebg {
    filter: invert(1);
    opacity: 0.92;
  }
  :global(:root[data-theme='light']) .scrim {
    background: radial-gradient(720px 560px at 50% 58%, rgba(255, 255, 255, 0.6) 0%, transparent 72%);
  }
  main.wizard {
    position: relative;
    z-index: 1;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1.4rem;
  }
  .logo {
    width: min(320px, 64%);
    height: auto;
    mix-blend-mode: screen;
    filter: drop-shadow(0 8px 32px rgba(0, 0, 0, 0.8));
  }
  :global(:root[data-theme='light']) .logo {
    mix-blend-mode: multiply;
    filter: invert(1);
  }
  .glass {
    background: color-mix(in srgb, var(--bg-raised) 78%, transparent);
    backdrop-filter: blur(14px) saturate(1.1);
    box-shadow: var(--shadow-3);
  }
  .panel {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.9rem;
    padding: 1.4rem 1.8rem;
    border-radius: var(--radius);
    max-width: 420px;
    text-align: center;
  }
  h2 {
    font-size: 1rem;
    margin: 0;
  }
  .copy {
    font-size: 0.86rem;
    color: var(--ink-body);
    line-height: 1.65;
    margin: 0;
  }
  .hint {
    font-size: 0.78rem;
    color: var(--ink-dim);
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .down {
    color: var(--down);
    font-size: 0.8rem;
  }
  .spin {
    width: 11px;
    height: 11px;
    border: 2px solid var(--accent);
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .themes {
    display: flex;
    gap: 0.8rem;
  }
  .theme-card {
    width: 124px;
    height: 84px;
    border-radius: var(--radius);
    border: 1px solid var(--line-strong);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.3rem;
    font-size: 0.74rem;
    cursor: pointer;
  }
  .theme-card.selected {
    border: 2px solid var(--accent);
  }
  .theme-card.dark {
    background: #08090a;
    color: #f7f8f8;
  }
  .theme-card.dark .swatch {
    background: #16171a;
  }
  .theme-card.light {
    background: #fbfbfc;
    color: #16181d;
  }
  .theme-card.light .swatch {
    background: #f1f2f4;
  }
  .swatch {
    width: 64px;
    height: 6px;
    border-radius: 3px;
  }
  .swatch.short {
    width: 44px;
  }
  .dots {
    display: flex;
    gap: 0.45rem;
    margin-top: 0.2rem;
  }
  .dots span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--line-strong);
  }
  .dots span.on {
    background: var(--accent);
  }
</style>
