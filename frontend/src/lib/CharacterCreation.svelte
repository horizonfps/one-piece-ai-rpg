<script>
  import { onMount } from 'svelte'
  import { getCatalog, rollTraits, createCharacter, createCampaign, deleteCampaign } from './api.js'
  import { t, has } from './i18n.svelte.js'

  // onstart(campaignId) enters the game after the sheet is confirmed.
  let { campaignId, onstart, onback } = $props()

  let catalog = $state(null) // {traits, classes, fruits, tiers}
  let loading = $state(true)
  let error = $state(null)

  let mode = $state('setup') // 'setup' | 'review'
  let submitting = $state(false)
  let serverErrors = $state([])

  // sheet fields
  let name = $state('')
  let gender = $state('')
  let appearance = $state('')
  let weapon = $state('')
  let dream = $state('')
  let classId = $state('')
  let subFocus = $state('')
  let tier = $state('') // NORMAL | SKILLED | STRONG
  let fruitId = $state('') // '' = no fruit
  let hand = $state([]) // rolled traits (full objects)
  let addPick = $state('') // add-trait select

  const STYLE_FIGHTER = 'lutador-de-estilo'
  const FRUIT_USER = 'fruit-user'
  // Sub-focus goes into the sheet as free text in the UI language.
  const SUB_FOCI = ['legs', 'aquatic', 'speed']
  const rarityLabel = (r) => (has(`rarity.${r}`) ? t(`rarity.${r}`) : r)

  const selectedClass = $derived(catalog?.classes.find((c) => c.id === classId) || null)
  const isFruitUser = $derived(classId === FRUIT_USER)
  const isStyleFighter = $derived(classId === STYLE_FIGHTER)
  const hasGenio = $derived(hand.some((t) => t.stacking_exclusion === 'genio_haki'))
  const handIds = $derived(new Set(hand.map((t) => t.id)))
  // addable traits: not in hand and don't introduce a second Genio (backend revalidates anyway)
  const addable = $derived(
    (catalog?.traits || []).filter(
      (t) => !handIds.has(t.id) && !(hasGenio && t.stacking_exclusion === 'genio_haki')
    )
  )
  // Flat A-Z list. The catalog tier is internal curation and hidden from the player.
  const fruitsSorted = $derived(
    [...(catalog?.fruits || [])].sort((a, b) => a.name_jp.localeCompare(b.name_jp, 'pt'))
  )
  const selectedFruit = $derived(catalog?.fruits.find((f) => f.id === fruitId) || null)

  const fruitMissing = $derived(isFruitUser && !fruitId)
  const canReview = $derived(
    !!name.trim() && !!tier && !!classId && !fruitMissing
  )

  async function load() {
    loading = true
    error = null
    try {
      catalog = await getCatalog()
      hand = await rollTraits()
    } catch (e) {
      error = String(e)
    } finally {
      loading = false
    }
  }

  async function reroll() {
    try {
      hand = await rollTraits()
    } catch (e) {
      error = String(e)
    }
  }

  function removeTrait(id) {
    hand = hand.filter((t) => t.id !== id)
  }

  function addTrait() {
    if (!addPick) return
    const t = catalog.traits.find((x) => x.id === addPick)
    if (t && !handIds.has(t.id)) hand = [...hand, t]
    addPick = ''
  }

  function buildSheet() {
    return {
      name: name.trim(),
      gender: gender.trim(),
      appearance: appearance.trim(),
      weapon: weapon.trim(),
      tier_alvo: tier,
      class_id: classId,
      sub_focus: isStyleFighter && subFocus ? t(`creation.subfocus.${subFocus}`) : null,
      trait_ids: hand.map((t) => t.id),
      devil_fruit_id: fruitId || null,
      dream: dream.trim(),
    }
  }

  async function confirm() {
    submitting = true
    serverErrors = []
    // Campaign is seeded here, on sheet acceptance, to avoid an orphan save if the player
    // backs out earlier. A dev deep-link already carries an id, so reuse that campaign.
    let cid = campaignId
    let createdHere = false
    try {
      if (!cid) {
        const c = await createCampaign(name.trim())
        cid = c.campaign_id
        createdHere = true
      }
      await createCharacter(cid, buildSheet())
      onstart(cid)
    } catch (e) {
      // If we seeded the campaign just now and the sheet failed, undo it to avoid an orphan save.
      if (createdHere && cid) {
        try {
          await deleteCampaign(cid)
        } catch {
          /* best-effort cleanup of the partial save */
        }
      }
      serverErrors = [String(e?.message || e)]
      mode = 'setup'
    } finally {
      submitting = false
    }
  }

  onMount(load)
</script>

<main>
  <header>
    <p class="kicker">One Piece RPG</p>
    <h1>{t('creation.title')}</h1>
    <p class="sub">{t('creation.sub')}</p>
  </header>

  <section class="panel">
    {#if loading}
      <p class="hint">{t('creation.loading_catalogs')}</p>
    {:else if error}
      <p class="line down">{error}</p>
      <button onclick={load}>{t('creation.retry')}</button>
    {:else if mode === 'setup'}
      <div class="panel-head">
        <h2>{t('creation.sheet_title')}</h2>
        {#if onback}<button class="ghost" onclick={onback}>{t('common.back')}</button>{/if}
      </div>

      {#if serverErrors.length}
        <p class="line down" data-testid="server-error">{serverErrors.join(' · ')}</p>
      {/if}

      <!-- identity -->
      <div class="field">
        <label for="f-name">{t('creation.name')}</label>
        <input id="f-name" data-testid="name" bind:value={name} />
      </div>
      <div class="field">
        <label for="f-gender">{t('creation.gender')}</label>
        <input id="f-gender" data-testid="gender" bind:value={gender} placeholder={t('creation.gender_ph')} />
      </div>
      <div class="field">
        <label for="f-appearance">{t('creation.appearance')}</label>
        <textarea id="f-appearance" data-testid="appearance" rows="3" bind:value={appearance} placeholder={t('creation.appearance_ph')}></textarea>
      </div>

      <!-- class -->
      <div class="field">
        <label for="f-class">{t('creation.class')}</label>
        <select id="f-class" data-testid="class" bind:value={classId}>
          <option value="" disabled>{t('creation.class_ph')}</option>
          {#each catalog.classes as c (c.id)}
            <option value={c.id}>{c.name} · {c.archetype}</option>
          {/each}
        </select>
      </div>
      {#if selectedClass}
        <p class="hint desc">{selectedClass.description}</p>
      {/if}
      {#if isStyleFighter}
        <div class="field">
          <label for="f-sub">{t('creation.subfocus')}</label>
          <select id="f-sub" data-testid="subfocus" bind:value={subFocus}>
            <option value="">{t('creation.subfocus_ph')}</option>
            {#each SUB_FOCI as s}<option value={s}>{t(`creation.subfocus.${s}`)}</option>{/each}
          </select>
        </div>
      {/if}

      <!-- weapon -->
      <div class="field">
        <label for="f-weapon">{t('creation.weapon')}</label>
        <input id="f-weapon" data-testid="weapon" bind:value={weapon} placeholder={t('creation.weapon_ph')} />
      </div>

      <!-- target tier -->
      <div class="field">
        <span class="lbl">{t('creation.tier')}</span>
        <div class="tiers" data-testid="tiers">
          {#each catalog.tiers as tr}
            <button
              type="button"
              class="chip"
              class:active={tier === tr}
              data-testid={`tier-${tr}`}
              onclick={() => (tier = tr)}>{tr}</button
            >
          {/each}
        </div>
        <p class="hint">{t('creation.tier_hint')}</p>
      </div>

      <!-- traits -->
      <div class="field">
        <span class="lbl">{t('creation.traits')} <span class="muted">({hand.length})</span></span>
        <div class="traits" data-testid="traits">
          {#each hand as tr (tr.id)}
            <div class="trait">
              <div class="trait-head">
                <span class="dot" class:neg={tr.polarity === 'negative'} title={tr.polarity === 'positive' ? t('creation.positive') : t('creation.negative')}></span>
                <span class="trait-name">{tr.name}</span>
                <span class="trait-meta">{rarityLabel(tr.rarity)}</span>
                <button class="x ghost" data-testid={`remove-${tr.id}`} onclick={() => removeTrait(tr.id)} title={t('common.remove')}>×</button>
              </div>
              <p class="trait-desc">{tr.description}</p>
            </div>
          {/each}
          {#if hand.length === 0}<p class="hint">{t('creation.no_traits')}</p>{/if}
        </div>
        <div class="trait-actions">
          <button data-testid="reroll" onclick={reroll}>{t('creation.reroll')}</button>
          <select data-testid="add-trait" bind:value={addPick} onchange={addTrait}>
            <option value="">{t('creation.add_trait')}</option>
            {#each addable as tr (tr.id)}
              <option value={tr.id}>{tr.name} ({tr.polarity === 'positive' ? '+' : '−'}/{rarityLabel(tr.rarity)})</option>
            {/each}
          </select>
        </div>
      </div>

      <!-- fruit -->
      <div class="field">
        <label for="f-fruit">{t('creation.fruit')}</label>
        <select id="f-fruit" data-testid="fruit" bind:value={fruitId}>
          <option value="">{t('creation.no_fruit')}</option>
          {#each fruitsSorted as f (f.id)}
            <option value={f.id}>{f.name_jp} — {f.name_pt} ({f.type})</option>
          {/each}
        </select>
        {#if selectedFruit}
          <p class="hint desc">{t('creation.fruit_owner', { owner: selectedFruit.canon_owner, type: selectedFruit.type })}</p>
        {/if}
        {#if fruitMissing}
          <p class="line down" data-testid="fruit-warning">{t('creation.fruit_required')}</p>
        {/if}
      </div>

      <!-- dream -->
      <div class="field">
        <label for="f-dream">{t('creation.dream')}</label>
        <textarea id="f-dream" data-testid="dream" rows="2" bind:value={dream} placeholder={t('creation.dream_ph')}></textarea>
      </div>

      <!-- locks -->
      <div class="locks">
        <span>{t('creation.lock_age')} <b>17</b></span><span>{t('creation.lock_race')} <b>{t('creation.lock_human')}</b></span>
        <span>{t('creation.lock_bounty')} <b>0</b></span><span>{t('creation.lock_family')} <b>{t('creation.lock_unknown')}</b></span>
      </div>

      <button class="primary" data-testid="to-review" disabled={!canReview} onclick={() => (mode = 'review')}>
        {t('creation.to_review')}
      </button>
    {:else}
      <!-- REVIEW -->
      <div class="panel-head">
        <h2>{t('creation.review')}</h2>
        <button class="ghost" data-testid="edit" onclick={() => (mode = 'setup')}>{t('creation.back_edit')}</button>
      </div>

      {#if serverErrors.length}
        <p class="line down" data-testid="server-error">{serverErrors.join(' · ')}</p>
      {/if}

      <dl class="review" data-testid="review">
        <div><dt>{t('creation.name')}</dt><dd>{name}</dd></div>
        {#if gender}<div><dt>{t('creation.gender')}</dt><dd>{gender}</dd></div>{/if}
        {#if appearance}<div><dt>{t('creation.appearance')}</dt><dd>{appearance}</dd></div>{/if}
        <div><dt>{t('creation.class')}</dt><dd>{selectedClass?.name}{isStyleFighter && subFocus ? `: ${t(`creation.subfocus.${subFocus}`)}` : ''}</dd></div>
        {#if weapon}<div><dt>{t('creation.weapon')}</dt><dd>{weapon}</dd></div>{/if}
        <div><dt>{t('creation.review_tier')}</dt><dd>{tier}</dd></div>
        <div><dt>{t('creation.fruit')}</dt><dd>{selectedFruit ? `${selectedFruit.name_jp} (${selectedFruit.name_pt})` : t('creation.no_fruit')}</dd></div>
        <div><dt>{t('creation.traits')}</dt><dd>{hand.map((tr) => tr.name).join(', ') || '—'}</dd></div>
        {#if dream}<div><dt>{t('creation.dream')}</dt><dd>{dream}</dd></div>{/if}
        <div><dt>{t('creation.review_fixed')}</dt><dd>{t('creation.review_fixed_value')}</dd></div>
      </dl>

      <button class="primary" data-testid="confirm" disabled={submitting} onclick={confirm}>
        {submitting ? t('creation.confirming') : t('creation.confirm')}
      </button>
    {/if}
  </section>
</main>

<style>
  .field {
    margin-bottom: 1.05rem;
    display: grid;
    gap: 0.4rem;
  }
  label,
  .lbl {
    font-size: 0.7rem;
    font-weight: 550;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--ink-dim);
  }
  .muted {
    color: var(--ink-dim);
    letter-spacing: 0;
    font-weight: 400;
  }
  input,
  select,
  textarea {
    width: 100%;
  }
  textarea {
    resize: vertical;
  }
  .desc {
    margin: -0.5rem 0 1rem;
    font-size: 0.78rem;
  }
  .tiers {
    display: flex;
    gap: 0.4rem;
  }
  .chip {
    flex: 1;
    font-size: 0.76rem;
  }
  .chip.active {
    color: var(--accent-hi);
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .traits {
    display: grid;
    gap: 0.5rem;
  }
  .trait {
    background: var(--bg-elevated);
    border: 1px solid var(--line);
    border-radius: var(--radius-sm);
    padding: 0.55rem 0.7rem;
    transition: border-color 0.12s ease;
  }
  .trait:hover {
    border-color: var(--line-strong);
  }
  .trait-head {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  /* Polarity shown as a desaturated status dot. */
  .dot {
    flex: none;
    width: 6px;
    height: 6px;
    border-radius: 99px;
    background: color-mix(in srgb, var(--ok) 70%, var(--ink-dim));
  }
  .dot.neg {
    background: color-mix(in srgb, var(--down) 70%, var(--ink-dim));
  }
  .trait-name {
    font-weight: 550;
    font-size: 0.86rem;
    color: var(--ink);
    letter-spacing: -0.01em;
  }
  .trait-meta {
    font-family: var(--mono);
    font-size: 0.66rem;
    color: var(--ink-dim);
  }
  .x {
    margin-left: auto;
    padding: 0.05rem 0.4rem;
    font-size: 0.85rem;
    line-height: 1;
  }
  .x:hover:not(:disabled) {
    color: var(--down);
    background: var(--down-soft);
  }
  .trait-desc {
    margin: 0.3rem 0 0;
    font-size: 0.8rem;
    line-height: 1.5;
    color: var(--ink-dim);
  }
  .trait-actions {
    margin-top: 0.6rem;
    display: flex;
    gap: 0.5rem;
  }
  .trait-actions select {
    flex: 1;
  }
  .locks {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1rem;
    font-size: 0.74rem;
    color: var(--ink-dim);
    border-top: 1px solid var(--line);
    padding-top: 0.9rem;
    margin: 0.4rem 0 1.2rem;
  }
  .locks b {
    color: var(--ink);
    font-weight: 550;
  }
  .review dd {
    color: var(--ink);
    font-weight: 500;
  }
  .primary {
    display: block;
    margin-top: 1rem;
    margin-left: auto;
    padding: 0.55rem 1.25rem;
    font-size: 0.84rem;
  }
</style>
