<script>
  // Intro screen shown when starting a new campaign, before character creation.
  import { t } from './i18n.svelte.js'

  let { oncontinue, onback } = $props()

  const steps = $derived(
    [1, 2, 3, 4].map((k) => ({
      tag: t(`onboarding.step${k}_tag`),
      title: t(`onboarding.step${k}_title`),
      body: t(`onboarding.step${k}_body`),
    }))
  )

  let i = $state(0)
  const last = $derived(i === steps.length - 1)

  function next() {
    if (last) oncontinue()
    else i += 1
  }
  function prev() {
    if (i === 0) onback?.()
    else i -= 1
  }
</script>

<main>
  <header>
    <p class="kicker">{t('onboarding.kicker')}</p>
    <h1>{steps[i].tag}</h1>
  </header>

  <section class="panel">
    <div class="step">
      <h2>{steps[i].title}</h2>
      <p class="body">{steps[i].body}</p>
    </div>

    <div class="dots">
      {#each steps as _, k}
        <span class="dot" class:on={k === i}></span>
      {/each}
    </div>

    <div class="nav">
      <button class="ghost" onclick={prev}>{i === 0 ? t('common.cancel') : t('common.back')}</button>
      <button class="primary" onclick={next}>{last ? t('onboarding.create_character') : t('onboarding.continue')}</button>
    </div>
  </section>
</main>

<style>
  .step {
    min-height: 8rem;
  }
  .body {
    color: var(--ink-body);
    font-size: 0.92rem;
    line-height: 1.7;
    margin: 0.7rem 0 0;
  }
  .dots {
    display: flex;
    gap: 0.45rem;
    justify-content: center;
    margin: 1.25rem 0;
  }
  .dots .dot {
    width: 6px;
    height: 6px;
    border-radius: 99px;
    background: var(--line-strong);
    transition: width 0.2s ease, background 0.2s ease;
  }
  .dots .dot.on {
    width: 18px;
    background: var(--accent);
  }
  .nav {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
  }
  .primary {
    padding: 0.5rem 1rem;
  }
</style>
