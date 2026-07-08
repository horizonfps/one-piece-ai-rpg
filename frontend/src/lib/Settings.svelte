<script>
  import { onMount } from 'svelte'
  import { getSettings, updateSettings } from './api.js'
  import { t, setLocale } from './i18n.svelte.js'

  let { onback } = $props()

  let settings = $state(null)
  let loading = $state(true)
  let saving = $state(false)
  let error = $state(null)
  let savedFlash = $state(false)

  // Editable form fields mirroring settings; proxy_key stays blank when already set.
  let proxyUrl = $state('')
  let proxyKeyInput = $state('')
  let autoSpawn = $state(true)

  async function load() {
    loading = true
    error = null
    try {
      settings = await getSettings()
      proxyUrl = settings.proxy_url
      autoSpawn = settings.auto_spawn_proxy
    } catch (e) {
      error = String(e)
    } finally {
      loading = false
    }
  }

  // Theme applies live via data-theme on the root and persists.
  async function setTheme(theme) {
    document.documentElement.dataset.theme = theme === 'dark' ? '' : theme
    try {
      settings = await updateSettings({ theme })
    } catch (e) {
      error = String(e)
    }
  }

  // UI locale switches live; prose language applies to NEW campaigns only.
  async function setLanguage(language) {
    try {
      settings = await updateSettings({ language })
      setLocale(language)
    } catch (e) {
      error = String(e)
    }
  }

  async function saveProxy() {
    saving = true
    error = null
    try {
      const patch = { proxy_url: proxyUrl, auto_spawn_proxy: autoSpawn }
      if (proxyKeyInput.trim()) patch.proxy_key = proxyKeyInput.trim()
      settings = await updateSettings(patch)
      proxyKeyInput = ''
      proxyUrl = settings.proxy_url
      savedFlash = true
      setTimeout(() => (savedFlash = false), 1800)
    } catch (e) {
      error = String(e)
    } finally {
      saving = false
    }
  }

  onMount(load)
</script>

<main>
  <header>
    <p class="kicker">One Piece RPG</p>
    <h1>{t('settings.title')}</h1>
    <p class="sub">{t('settings.sub')}</p>
  </header>

  <section class="panel">
    <div class="panel-head">
      <h2>{t('settings.head')}</h2>
      <button class="ghost" onclick={onback}>{t('common.back')}</button>
    </div>

    {#if error}<p class="line down">{error}</p>{/if}

    {#if loading}
      <p class="hint">{t('common.loading')}</p>
    {:else if settings}
      <div class="row">
        <h3>{t('settings.theme')}</h3>
        <div class="seg">
          <button class:active={settings.theme === 'dark'} onclick={() => setTheme('dark')}>{t('settings.theme_dark')}</button>
          <button class:active={settings.theme === 'light'} onclick={() => setTheme('light')}>{t('settings.theme_light')}</button>
        </div>
      </div>

      <div class="row">
        <h3>{t('settings.language')}</h3>
        <div class="seg">
          <button class:active={settings.language === 'pt-br'} onclick={() => setLanguage('pt-br')}>Português (BR)</button>
          <button class:active={settings.language === 'en'} onclick={() => setLanguage('en')}>English</button>
        </div>
      </div>
      <p class="hint small">{t('settings.language_hint')}</p>

      <div class="row col">
        <h3>CLIProxyAPI</h3>
        <label class="fld">
          <span>Endpoint</span>
          <input type="text" bind:value={proxyUrl} placeholder="http://127.0.0.1:8318" />
        </label>
        <label class="fld">
          <span>API key</span>
          <input
            type="password"
            bind:value={proxyKeyInput}
            placeholder={settings.proxy_key_set ? settings.proxy_key_masked : 'onepiece-proxy-key'}
          />
        </label>
        <label class="chk">
          <input type="checkbox" bind:checked={autoSpawn} />
          <span>{t('settings.proxy_autospawn')}</span>
        </label>
        <button class="send" onclick={saveProxy} disabled={saving}>
          {saving ? t('common.saving') : savedFlash ? t('settings.saved') : t('common.save')}
        </button>
        <p class="hint small">{t('settings.proxy_hint')}</p>
      </div>
    {/if}
  </section>
</main>

<style>
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.95rem 0;
    border-bottom: 1px solid var(--line);
  }
  .row.col {
    flex-direction: column;
    align-items: stretch;
    gap: 0.75rem;
    border-bottom: none;
  }
  .row h3 {
    margin: 0;
  }

  .seg {
    display: flex;
    gap: 2px;
    background: var(--bg-elevated);
    border: 1px solid var(--line);
    border-radius: var(--radius-sm);
    padding: 2px;
  }
  .seg button {
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 0.3rem 0.75rem;
    font-size: 0.78rem;
    color: var(--ink-dim);
  }
  .seg button:hover:not(:disabled) {
    background: var(--bg-hover);
    color: var(--ink);
  }
  .seg button.active {
    background: var(--bg-raised);
    color: var(--ink);
    box-shadow: var(--shadow-1);
  }
  .seg button.active:disabled {
    opacity: 1;
  }

  .fld {
    display: grid;
    gap: 0.35rem;
  }
  .fld span {
    font-size: 0.7rem;
    font-weight: 550;
    color: var(--ink-dim);
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
  .fld input {
    width: 100%;
    font-family: var(--mono);
    font-size: 0.78rem;
  }
  .chk {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.84rem;
    color: var(--ink-body);
  }
  .chk input {
    accent-color: var(--accent);
  }
  .send {
    align-self: flex-start;
    padding: 0.48rem 1rem;
  }
  .hint.small {
    font-size: 0.74rem;
    margin: 0.3rem 0 0;
  }
</style>
