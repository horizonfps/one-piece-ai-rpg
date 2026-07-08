<script>
  import { t } from './i18n.svelte.js'

  let { onback } = $props()

  const links = [
    { label: 'X', value: '@horizonfps', href: 'https://x.com/horizonfps' },
    { label: 'GitHub', value: 'horizonfps', href: 'https://github.com/horizonfps' },
    { label: 'Discord', value: 'horizonvlr', copy: true },
  ]

  const wallets = [
    { name: 'Solana', qr: '/credits/qr-solana.svg', address: 'By2DkHSMvgnDUZrGWa95e8CZD7JvQgiXbPkvTwtZCW2x' },
    { name: 'Ethereum', qr: '/credits/qr-eth.svg', address: '0x5ba31e1c1Acaf8D4AB3B1f0A639e2A6f201fcaC2' },
    { name: 'Base', qr: '/credits/qr-base.svg', address: '0x5ba31e1c1Acaf8D4AB3B1f0A639e2A6f201fcaC2' },
    { name: 'Bitcoin', qr: '/credits/qr-btc.svg', address: 'bc1pre7qzeet3zzmm00y2aas7dlwf87hp8zzd52wmh4m569tjjt8ue9qq3nk2h' },
  ]

  let copied = $state(null)

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text)
      copied = text
      setTimeout(() => (copied = null), 1600)
    } catch {
      copied = null
    }
  }
</script>

<main>
  <header>
    <p class="kicker">One Piece RPG</p>
    <h1>{t('credits.title')}</h1>
  </header>

  <section class="panel">
    <div class="panel-head">
      <h2>horizon</h2>
      <button class="ghost" onclick={onback}>{t('common.back')}</button>
    </div>

    <ul class="links">
      {#each links as l (l.label)}
        <li>
          <span class="lbl">{l.label}</span>
          {#if l.href}
            <a href={l.href} target="_blank" rel="noopener noreferrer">{l.value}</a>
          {:else}
            <button class="plain" onclick={() => copy(l.value)} title={t('credits.copy')}>
              {copied === l.value ? t('credits.copied') : l.value}
            </button>
          {/if}
        </li>
      {/each}
    </ul>

    <div class="support">
      <h3>{t('credits.support')}</h3>
      <div class="wallets">
        {#each wallets as w (w.name)}
          <div class="wallet">
            <span class="coin">{w.name}</span>
            <img class="qr" src={w.qr} alt={t('credits.wallet_qr', { name: w.name })} />
            <button class="addr" onclick={() => copy(w.address)} title={t('credits.copy_address')}>
              {copied === w.address ? t('credits.copied') : w.address}
            </button>
          </div>
        {/each}
      </div>
    </div>

  </section>
</main>

<style>
  .links {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.4rem;
  }
  .links li {
    display: flex;
    align-items: baseline;
    gap: 0.8rem;
    font-size: 0.88rem;
  }
  .lbl {
    width: 4.5rem;
    color: var(--ink-dim);
    font-size: 0.76rem;
  }
  .links a {
    color: var(--accent);
    text-decoration: none;
  }
  .links a:hover {
    text-decoration: underline;
  }
  .plain {
    background: transparent;
    border: none;
    padding: 0;
    color: var(--ink);
    font-size: 0.88rem;
    cursor: pointer;
  }
  .plain:hover {
    color: var(--accent);
  }

  .support {
    margin-top: 1.4rem;
    border-top: 1px solid var(--line);
    padding-top: 1rem;
  }
  .support h3 {
    margin: 0 0 0.8rem;
  }
  .wallets {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 0.8rem;
  }
  .wallet {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    padding: 0.8rem;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--bg-raised);
  }
  .coin {
    font-weight: 550;
    font-size: 0.84rem;
  }
  /* White backing keeps the QR readable in dark theme. */
  .qr {
    width: 132px;
    height: 132px;
    border-radius: 6px;
    background: #fff;
  }
  .addr {
    width: 100%;
    background: transparent;
    border: none;
    padding: 0;
    color: var(--ink-dim);
    font-family: var(--mono, ui-monospace, monospace);
    font-size: 0.62rem;
    word-break: break-all;
    cursor: pointer;
    text-align: center;
  }
  .addr:hover {
    color: var(--accent);
  }

</style>
