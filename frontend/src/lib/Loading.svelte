<script>
  import { onMount } from 'svelte'
  import { getHealth, getSettings } from './api.js'
  import { t, setLocale } from './i18n.svelte.js'

  // Awaits health + settings, applies theme and UI locale, then hands off to App.
  let { ondone } = $props()

  let progress = $state(12)
  let slow = $state(false)

  onMount(async () => {
    const minDelay = new Promise((r) => setTimeout(r, 1200))
    const slowTimer = setTimeout(() => (slow = true), 5000)
    let health = null
    let settings = null
    while (!health || !settings) {
      try {
        ;[health, settings] = await Promise.all([getHealth(), getSettings()])
      } catch {
        slow = true
        await new Promise((r) => setTimeout(r, 1500))
      }
    }
    document.documentElement.dataset.theme = settings.theme === 'dark' ? '' : settings.theme
    setLocale(settings.language)
    progress = 70
    await minDelay
    clearTimeout(slowTimer)
    progress = 100
    // Let 100% paint one frame before switching phase.
    setTimeout(() => ondone({ health, settings }), 180)
  })
</script>

<div class="titlebg"></div>
<div class="scrim"></div>

<main class="loading">
  <img class="logo" src="/title-screen/logo.jpg" alt="ONE PIECE" />
  <div class="bar"><div class="fill" style="width: {progress}%"></div></div>
  <p class="hint">{t('loading.progress')}</p>
  {#if slow}<p class="hint dim">{t('loading.slow')}</p>{/if}
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
  main.loading {
    position: relative;
    z-index: 1;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1rem;
  }
  .logo {
    width: min(380px, 72%);
    height: auto;
    mix-blend-mode: screen;
    filter: drop-shadow(0 8px 32px rgba(0, 0, 0, 0.8));
  }
  :global(:root[data-theme='light']) .logo {
    mix-blend-mode: multiply;
    filter: invert(1);
  }
  .bar {
    width: min(240px, 60%);
    height: 3px;
    background: var(--line-strong);
    border-radius: 2px;
    overflow: hidden;
  }
  .fill {
    height: 100%;
    background: var(--accent);
    transition: width 0.4s ease;
  }
  .hint {
    font-size: 0.8rem;
    color: var(--ink-dim);
  }
  .dim {
    font-size: 0.72rem;
    opacity: 0.8;
  }
</style>
