<script>
  import { onMount, onDestroy, tick } from 'svelte'
  import {
    getCampaign,
    turnSocketUrl,
    listDirectives,
    deactivateDirective,
    listCards,
    searchMemory,
    getWorld,
    listNews,
    getComms,
    getEconomy,
    addInventoryItem,
    editInventoryItem,
    deleteInventoryItem,
    getFleet,
    setJollyRoger,
    getFactions,
    getLegend,
    editLegend,
    deleteLegend,
    getThreads,
    createThread,
    editThread,
    deleteThread,
    getAlliances,
    getCrew,
    respondCrewOffer,
    getEnding,
    getPoneglyphs,
    rewindTurn,
    editCard,
    getCard,
    editPlayer,
    listTechniques,
    editTechnique,
    deleteTechnique,
    editBreakthrough,
    deleteBreakthrough,
    editFruitUsage,
    deleteFruitUsage,
    editCrystal,
    deleteCrystal,
    editTurnProse,
  } from './api.js'
  import Map from './Map.svelte'
  import { t, has, numberLocale } from './i18n.svelte.js'

  let { campaignId, onback } = $props()

  let meta = $state(null)
  let scene = $state(null)
  let presentNpcs = $state([])
  let clock = $state(null)
  // Unified chronological log: turn entries (DO) plus META responses.
  let entries = $state([])
  let crystals = $state([])
  let cards = $state([])
  let cardsLoaded = $state(false)
  let memTab = $state('crystals')
  let searchQuery = $state('')
  let searchResults = $state(null) // null = no active search
  let directives = $state([])
  let searchTimer = null

  let input = $state('')
  let actionType = $state('DO')
  let pending = $state(null)
  let busy = $state(false)
  // Prose fully streamed but post-turn (world bookkeeping) still running: let the player type and
  // queue the next action. The backend serializes turns, so a queued action can't start mid-bookkeeping.
  let proseDone = $state(false)
  let queued = $state(null)
  let connected = $state(false)
  let loadError = $state(null)
  let rerolling = $state(false)
  // Surfaced runtime error; campaign stays intact and the player retries or reformulates.
  let turnError = $state(null)
  let turnNotice = $state(null)

  // Unified HUD: single drawer with typed tabs; each tab loads its data on demand.
  const tabLabel = (id) => t(`hud.tab.${id}`)
  // Sidebar navigation: labeled groups of vertical items.
  const HUD_GROUPS = [
    { key: 'personagem', tabs: ['ficha', 'cartaz', 'tecnicas', 'combate', 'inventario'] },
    { key: 'bando', tabs: ['tripulacao', 'navio', 'aliancas'] },
    { key: 'mundo', tabs: ['reputacao', 'comunicacao', 'jornal', 'final'] },
    { key: 'registro', tabs: ['memoria', 'diretivas', 'fios'] },
  ]
  const brkLabel = (k) => (has(`brk.${k}`) ? t(`brk.${k}`) : k)
  let hudTab = $state(null)

  // Map: read-only full-screen overlay.
  let mapOpen = $state(false)
  let world = $state(null)
  let mapError = $state(null)

  // Per-surface data, fetched on tab open and refreshed when a turn moves it.
  let player = $state(null)
  let playerDraft = $state({})
  let savingPlayer = $state(false)
  let playerMsg = $state('')

  let techniques = $state([])
  let editingTechId = $state(null)
  let techDraft = $state({ name: '', description: '' })

  // Combat: player breakthroughs and fruit usage log, read plus inline edit.
  let editingBrkKind = $state(null)
  let brkDraft = $state({ description: '' })
  let editingFruitIdx = $state(null)
  let fruitDraft = $state({ usage_summary: '' })


  // Inline edit state for cards, crystals, and turn prose.
  let editingCardId = $state(null)
  let cardDraft = $state({})
  let editingCrystalId = $state(null)
  let crystalDraft = $state({})
  let editingTurnKey = $state(null)
  let proseDraft = $state('')
  let savingProse = $state(false)

  // News Coo: newspaper editions arrive in turn_complete.
  let newsEditions = $state([])
  let newsNemesis = $state(null)
  let newsUnread = $state(0)
  let newsToast = $state(null)
  let newsToastTimer = null

  // Communication: Den Den Mushi and Vivre Card.
  let comms = $state(null)
  let mushiToast = $state(null)
  let mushiToastTimer = null
  const vivreIcon = { white: '◻', burning: '🔥', errant: '〰', ashes: '·' }

  // Economy and inventory.
  let economy = $state(null)
  let bellyDraft = $state(0)
  let savingBelly = $state(false)
  // Inventory item inline add/edit.
  let editingItemId = $state(null)
  let itemDraft = $state({})
  let creatingItem = $state(false)

  // Ship and Jolly Roger.
  let fleet = $state(null)
  let jollyDraft = $state('')
  let jollySaving = $state(false)
  const HULLS = ['pristine', 'scarred', 'damaged', 'broken']
  const hullLabel = (h) => (has(`hull.${h}`) ? t(`hull.${h}`) : h)
  const hullHint = (h) => (has(`hullhint.${h}`) ? t(`hullhint.${h}`) : '')

  // Faction reputation.
  let factionsData = $state(null)
  const repBucketLabel = (b) => (has(`rep.${b}`) ? t(`rep.${b}`) : b)

  // Living legend: wanted posters of player and crewmates, read plus inline edit.
  let legendData = $state(null)
  let editingLegendId = $state(null)
  let legendDraft = $state({})
  const wantedLabel = (w) => (has(`wanted.${w}`) ? t(`wanted.${w}`) : w)
  const fmtBerries = (n) => `฿${Number(n || 0).toLocaleString(numberLocale())}`

  function startEditLegend(t) {
    editingLegendId = t.card_id
    legendDraft = {
      epithet: t.epithet ?? '',
      public_image: t.public_image ?? '',
      divergence_note: t.divergence_note ?? '',
      poster_note: t.poster_note ?? '',
      wanted_status: t.wanted_status ?? 'none',
    }
  }
  async function saveLegend() {
    try {
      await editLegend(campaignId, editingLegendId, legendDraft)
      legendData = await getLegend(campaignId)
      editingLegendId = null
    } catch (e) {
      loadError = String(e)
    }
  }
  async function removeLegend(t) {
    try {
      await deleteLegend(campaignId, t.card_id)
      legendData = await getLegend(campaignId)
    } catch (e) {
      loadError = String(e)
    }
  }
  const legendHasEntry = (t) =>
    Boolean(t.epithet || t.public_image || t.poster_note || t.divergence_note || t.wanted_status !== 'none')

  // Continuity threads (foreshadow pool), read plus inline edit and create.
  let threadsData = $state(null)
  let editingThreadId = $state(null)
  let threadDraft = $state({})
  let creatingThread = $state(false)
  const planterLabel = (p) => (has(`planter.${p}`) ? t(`planter.${p}`) : p)
  // Resolved threads stay stored as history; only open ones reach the Director/Narrator.
  const openThreads = $derived((threadsData?.threads ?? []).filter((t) => t.resolved_at_turn_index == null))
  const resolvedThreads = $derived((threadsData?.threads ?? []).filter((t) => t.resolved_at_turn_index != null))

  function startEditThread(t) {
    creatingThread = false
    editingThreadId = t.hook_id
    threadDraft = {
      description: t.description ?? '',
      theme_tag: t.theme_tag ?? '',
      where_hint: t.where_hint ?? '',
      source_island_name: t.source_island_name ?? '',
    }
  }
  function startCreateThread() {
    editingThreadId = null
    creatingThread = true
    threadDraft = { description: '', theme_tag: '', where_hint: '', source_island_name: '' }
  }
  async function saveThread() {
    try {
      if (creatingThread) await createThread(campaignId, threadDraft)
      else await editThread(campaignId, editingThreadId, threadDraft)
      threadsData = await getThreads(campaignId)
      editingThreadId = null
      creatingThread = false
    } catch (e) {
      loadError = String(e)
    }
  }
  async function removeThread(t) {
    try {
      await deleteThread(campaignId, t.hook_id)
      threadsData = await getThreads(campaignId)
    } catch (e) {
      loadError = String(e)
    }
  }

  // Inter-crew alliances.
  let alliancesData = $state(null)
  const formalityLabel = (f) => (has(`formality.${f}`) ? t(`formality.${f}`) : f)
  const hierarchyLabel = (h) => (has(`hierarchy.${h}`) ? t(`hierarchy.${h}`) : h)

  // Crew: roster, alignment, and pending NPC join offers.
  let crewData = $state(null)
  let crewOffer = $state(null)
  const dissatLabel = (d) => (has(`dissat.${d}`) ? t(`dissat.${d}`) : '')
  const bondLabel = (b) => (has(`bond.${b}`) ? t(`bond.${b}`) : t('bond.0'))

  // Endgame: the Director detects a reached ending and the cinematic plays on its own; the game stays open.
  let endingData = $state(null)
  let poneglyphData = $state(null)
  let endingToast = $state(null)
  let endingToastTimer = null
  let epilogue = $state(null)
  const endingLabel = (k) => (has(`ending.${k}`) ? t(`ending.${k}`) : k)

  // Edit mode: enum options for character sheet and cards.
  const TIERS = ['NORMAL', 'SKILLED', 'STRONG', 'ELITE', 'MONSTER', 'TITAN', 'WORLD', 'ABSURD']
  const KNOWLEDGE_TIERS = ['common', 'regional', 'specialized', 'esoteric', 'classified']
  const NARRATIVE_ARMORS = ['none', 'crew_armor', 'nemesis_armor', 'canon_top_armor']
  const EXPRESSIVENESS = ['alto', 'medio', 'contido']
  const HAKI_TYPES = ['KENBUNSHOKU', 'BUSOSHOKU', 'HAOSHOKU']
  const ALIGN_ANCHORS = [
    { v: -2, key: 'align.m2' },
    { v: -1, key: 'align.m1' },
    { v: -0.5, key: 'align.m05' },
    { v: 0, key: 'align.z' },
    { v: 0.5, key: 'align.p05' },
    { v: 1, key: 'align.p1' },
    { v: 2, key: 'align.p2' },
  ]
  function alignBucket(v) {
    const n = Number(v)
    return n >= 0.5 ? t('align.good') : n <= -0.5 ? t('align.evil') : t('align.neutral')
  }
  // Prepend a synthetic current option when the value is off-anchor so the select matches it.
  const alignOptions = $derived.by(() => {
    const base = ALIGN_ANCHORS.map((a) => ({ v: a.v, label: t(a.key) }))
    const v = Number(playerDraft.alignment_value)
    if (Number.isNaN(v) || ALIGN_ANCHORS.some((a) => a.v === v)) return base
    return [{ v, label: t('align.current', { v: v.toFixed(1) }) }, ...base]
  })

  // Devtools: per-turn trace of each LLM call.
  let devtoolsOpen = $state(false)
  let traces = $state([])
  let selectedTraceKey = $state(null)
  const currentTrace = $derived(
    traces.find((t) => t.key === selectedTraceKey) ?? traces[traces.length - 1] ?? null
  )

  let ws = null
  let wsClosing = false
  let wsRetries = 0
  let wsReconnectTimer = null
  let logEl
  let metaSeq = 0

  const phaseLabel = (p) => (has(`phase.${p}`) ? t(`phase.${p}`) : p)

  // Devtools/turn seal: joins the Auditor's reasoning for the tooltip.
  function auditTitle(a) {
    const parts = []
    if (a.reasoning_summary) parts.push(a.reasoning_summary)
    for (const c of a.applied ?? []) parts.push(`• ${c.rule_violated}: ${c.reasoning}`)
    return parts.join('\n')
  }

  const placeholder = $derived(
    !connected ? t('game.connecting') : actionType === 'META' ? t('game.ph_meta') : t('game.ph_do')
  )

  // Per-tab alert badge for unread news.
  function tabAlert(id) {
    if (id === 'jornal') return newsUnread
    return 0
  }
  const hudAlerts = $derived(newsUnread)

  async function load() {
    try {
      const d = await getCampaign(campaignId)
      meta = d.campaign
      scene = d.scene
      presentNpcs = d.present_npcs
      clock = d.clock
      crystals = d.crystals
      player = d.player
      entries = d.turns.map((t) => ({
        kind: 'turn',
        key: `t${t.turn_index}`,
        action: typeof t.player_input === 'object' ? t.player_input.raw : t.player_input,
        prose: t.narrator_prose,
      }))
      // Hydrate the devtools panel with persisted per-turn traces (survive reload).
      traces = d.turns
        .filter((t) => t.trace?.length)
        .map((t) => ({
          key: `t${t.turn_index}`,
          label: `turn ${t.turn_index}`,
          action: typeof t.player_input === 'object' ? t.player_input.raw : t.player_input,
          entries: t.trace,
        }))
      if (traces.length) selectedTraceKey = traces[traces.length - 1].key
      await scrollDown()
    } catch (e) {
      loadError = String(e)
    }
  }

  function connect() {
    if (wsClosing) return
    ws = new WebSocket(turnSocketUrl(campaignId))
    ws.onopen = () => {
      connected = true
      wsRetries = 0
    }
    ws.onclose = () => {
      connected = false
      if (wsClosing) return
      // uvicorn runs without --reload (manual restart) and network blips drop the socket; without a
      // reconnect the composer silently dies until a full page reload. Exponential backoff, capped.
      wsReconnectTimer = setTimeout(connect, Math.min(1000 * 2 ** wsRetries++, 15000))
    }
    ws.onerror = () => ws?.close()
    ws.onmessage = async (ev) => {
      const m = JSON.parse(ev.data)
      if (m.type === 'status') {
        if (!pending) {
          pending = { action: '', prose: '', phase: m.phase, meta: false }
          busy = true
        } else {
          pending.phase = m.phase
        }
        // FASE 32: the prose now arrives AFTER the post-turn + audit gate, so director_post is a
        // pre-prose phase. Unlock the composer once the prose is in (prose_delta) or at crystallizer.
        if (m.phase === 'crystallizer') proseDone = true
      } else if (m.type === 'prose_delta') {
        if (pending) {
          pending.prose += m.text
          proseDone = true
          await scrollDown()
        }
      } else if (m.type === 'turn_complete') {
        entries = [
          ...entries,
          { kind: 'turn', key: `t${m.turn_index}`, action: pending?.action ?? '', prose: m.prose, audit: m.audit },
        ]
        turnNotice = m.quota_interrupted ? t('game.quota_interrupted') : null
        captureTrace(`turn ${m.turn_index}`, pending?.action ?? '', m.trace)
        // Pair generated ids with new crystals so the inspector can edit or remove them.
        if (m.new_crystals?.length) {
          const ids = m.created_crystal_ids || []
          crystals = [...crystals, ...m.new_crystals.map((c, i) => ({ ...c, id: c.id ?? ids[i] }))]
        }
        if (m.clock) clock = m.clock
        if (m.scene) scene = m.scene
        if (m.present_npcs) presentNpcs = m.present_npcs
        if (m.current_arc != null && meta) meta = { ...meta, current_arc: m.current_arc }
        // Open inspectors go stale, so reload the active tab the turn touched.
        if (m.generated_npcs?.length) {
          cardsLoaded = false
          if (hudTab === 'memoria') loadCards()
        }
        if (m.news_coo?.markdown) onNewsArrival(m.news_coo)
        if (m.mushi_call) onMushiArrival(m.mushi_call)
        if (m.vivre_card_change && hudTab === 'comunicacao') loadTab('comunicacao')
        if (m.economy_changed && hudTab === 'inventario') loadTab('inventario')
        if (m.ship_changed && hudTab === 'navio') loadTab('navio')
        if (m.faction_changed && hudTab === 'reputacao') loadTab('reputacao')
        if (m.alliances_changed && hudTab === 'aliancas') loadTab('aliancas')
        // Threads move without a dedicated flag (plant on PRE, resolve on POST); cheap local read.
        if (hudTab === 'fios') loadTab('fios')
        if (m.crew_changed) {
          onCrewChange(m.post_turn?.crew)
          if (hudTab === 'tripulacao') loadTab('tripulacao')
        }
        if (m.ending_reached) {
          onEndingReached(m.ending_reached, m.epilogue)
          if (hudTab === 'final') loadTab('final')
        }
        if (m.poneglyph_revealed?.length || m.laugh_tale_revealed) onPoneglyphArrival(m)
        pending = null
        busy = false
        proseDone = false
        await scrollDown()
        flushQueued()
      } else if (m.type === 'meta_response') {
        captureTrace(`meta · ${m.kind}`, pending?.action ?? '', m.trace)
        if (m.kind === 'pergunta') {
          entries = [
            ...entries,
            { kind: 'meta_q', key: `m${++metaSeq}`, action: pending?.action ?? '', response_text: m.response_text },
          ]
        } else if (m.kind === 'lembre') {
          const txt = (m.directives_created ?? []).map((d) => d.text).join(' · ')
          entries = [
            ...entries,
            { kind: 'meta_note', key: `m${++metaSeq}`, action: pending?.action ?? '', text: txt },
          ]
        } else if (m.kind === 'esqueca') {
          directives = m.directives ?? []
          openHud('diretivas')
        }
        pending = null
        busy = false
        proseDone = false
        await scrollDown()
      } else if (m.type === 'quota_exceeded') {
        // Subscription window exhausted; nothing persisted, input is preserved for retry.
        onTurnFailure({ kind: 'quota', message: m.message, retryAfter: m.retry_after_seconds })
      } else if (m.type === 'model_refusal') {
        // Model refused this input; ask to reformulate.
        onTurnFailure({ kind: 'refusal', message: m.message })
      } else if (m.type === 'error') {
        onTurnFailure({ kind: 'generic', message: m.error })
      }
    }
  }

  // Handle a turn failure: clear pending state, return the action to the composer, show the banner.
  function onTurnFailure({ kind, message, retryAfter = null }) {
    const failedAction = pending?.action ?? ''
    if (failedAction && !input.trim()) input = failedAction
    pending = null
    busy = false
    proseDone = false
    queued = null
    turnError = { kind, message: message || '', retryAfter }
  }

  function dispatch(raw, type) {
    if (ws?.readyState !== WebSocket.OPEN) {
      if (raw && !input.trim()) input = raw
      turnError = { kind: 'offline', message: t('game.err_offline'), retryAfter: null }
      busy = false
      pending = null
      return
    }
    turnError = null
    const isMeta = type === 'META'
    pending = { action: raw, prose: '', phase: isMeta ? 'meta_router' : 'director', meta: isMeta }
    busy = true
    proseDone = false
    ws.send(JSON.stringify({ type, raw }))
  }

  // Fire the action queued during the previous turn's post-turn (the backend was busy until now).
  function flushQueued() {
    if (!queued) return
    const q = queued
    queued = null
    if (!connected) {
      if (!input.trim()) input = q.raw
      return
    }
    dispatch(q.raw, q.type)
  }

  function send() {
    const raw = input.trim()
    if (!raw || !connected) return
    // Prose is in but the post-turn is still running: queue this action instead of blocking; it
    // fires on turn_complete. Prose still streaming (busy && !proseDone) keeps the composer locked.
    if (busy) {
      if (!proseDone) return
      queued = { raw, type: actionType }
      input = ''
      return
    }
    dispatch(raw, actionType)
    input = ''
  }

  function onKey(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      send()
    }
  }

  // System commands: rewind/regenerate revert world state from the pre-turn snapshot, not just prose.
  // rerollNote is an optional one-shot OOC instruction for regenerate.
  let rerollNote = $state('')
  let rerollOpen = $state(false)
  const lastTurnKey = $derived.by(() => {
    for (let k = entries.length - 1; k >= 0; k--) {
      if (entries[k].kind === 'turn') return entries[k].key
    }
    return null
  })
  function lastTurnIdx() {
    for (let k = entries.length - 1; k >= 0; k--) {
      if (entries[k].kind === 'turn') return Number(entries[k].key.slice(1))
    }
    return -1
  }
  // Rewind reverts world state, so lazily-loaded HUD panels (cards, techniques, economy…) go
  // stale. load() refreshes the conversation surfaces; reload the open tab for the rest.
  async function refreshOpenTab() {
    cardsLoaded = false
    if (hudTab) await loadTab(hudTab)
  }
  // Rewind: undo the last turn and put its action back in the composer to edit.
  async function voltar() {
    if (busy || rerolling || pending) return
    const lastIdx = lastTurnIdx()
    if (lastIdx <= 1) return // opening turn has no action to restore
    if (!confirm(t('game.rewind_confirm'))) return
    rerolling = true
    try {
      const r = await rewindTurn(campaignId, lastIdx)
      await load()
      await refreshOpenTab()
      input = r.player_input?.raw ?? ''
      actionType = (r.player_input?.type ?? 'DO').toUpperCase() === 'META' ? 'META' : 'DO'
    } catch (e) {
      loadError = String(e)
    } finally {
      rerolling = false
    }
  }
  // Regenerate: rewind, then re-submit the same action through the full pipeline.
  async function regenerar() {
    if (busy || rerolling || pending || !connected) return
    const lastIdx = lastTurnIdx()
    if (lastIdx < 0) return
    rerolling = true
    try {
      const r = await rewindTurn(campaignId, lastIdx)
      await load()
      await refreshOpenTab()
      const a = r.player_input ?? {}
      if (ws?.readyState !== WebSocket.OPEN) {
        turnError = { kind: 'offline', message: t('game.err_offline_reroll'), retryAfter: null }
        return
      }
      turnError = null
      pending = { action: a.raw ?? '', prose: '', phase: 'director', meta: false }
      busy = true
      ws.send(
        JSON.stringify({
          type: a.type ?? 'DO',
          raw: a.raw ?? '',
          ooc_note: rerollNote.trim(),
        })
      )
      rerollNote = ''
      rerollOpen = false
      await scrollDown()
    } catch (e) {
      loadError = String(e)
    } finally {
      rerolling = false
    }
  }

  const hasTurns = $derived(entries.some((e) => e.kind === 'turn'))

  let traceSeq = 0
  function captureTrace(label, action, entries) {
    if (!entries?.length) return
    const key = `tr${++traceSeq}`
    traces = [...traces, { key, label, action, entries }]
    selectedTraceKey = key
  }

  function toggleDevtools() {
    devtoolsOpen = !devtoolsOpen
    if (devtoolsOpen) {
      hudTab = null
    }
  }

  async function openMap() {
    mapError = null
    try {
      // Fetch world and comms in parallel; the map needs vivre cards for the heading overlay.
      const [w, c] = await Promise.all([getWorld(campaignId), getComms(campaignId).catch(() => null)])
      world = w
      if (c) comms = c
      mapOpen = true
    } catch (e) {
      mapError = String(e)
    }
  }

  function fmtOutput(o) {
    if (o == null) return 'null'
    if (typeof o === 'string') return o
    try {
      return JSON.stringify(o, null, 2)
    } catch {
      return String(o)
    }
  }

  function kb(n) {
    if (!n) return '0'
    return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
  }

  function tokTotals(entries) {
    let inp = 0, out = 0, cacheRead = 0, cacheWrite = 0
    for (const e of entries ?? []) {
      const u = e.usage
      if (!u) continue
      inp += u.input || 0
      out += u.output || 0
      cacheRead += u.cache_read || 0
      cacheWrite += u.cache_creation || 0
    }
    return { inp, out, cacheRead, cacheWrite, total: inp + out }
  }

  async function openHud(tab) {
    hudTab = tab
    devtoolsOpen = false
    // clear in-progress edit state on tab switch
    editingCardId = null
    editingCrystalId = null
    editingTechId = null
    editingLegendId = null
    editingThreadId = null
    creatingThread = false
    editingItemId = null
    creatingItem = false
    await loadTab(tab)
  }

  function closeHud() {
    hudTab = null
  }

  async function loadTab(tab) {
    try {
      if (tab === 'ficha') {
        const d = await getCampaign(campaignId)
        player = d.player
        seedPlayerDraft()
      } else if (tab === 'memoria') {
        await refreshCrystals()
        await loadCards()
      } else if (tab === 'tecnicas') {
        techniques = await listTechniques(campaignId)
      } else if (tab === 'combate') {
        player = (await getCampaign(campaignId)).player
      } else if (tab === 'inventario') {
        economy = await getEconomy(campaignId)
        bellyDraft = economy?.belly ?? 0
      } else if (tab === 'navio') {
        fleet = await getFleet(campaignId)
        jollyDraft = fleet?.jolly_roger ?? ''
      } else if (tab === 'cartaz') {
        legendData = await getLegend(campaignId)
      } else if (tab === 'reputacao') {
        factionsData = await getFactions(campaignId)
      } else if (tab === 'aliancas') {
        alliancesData = await getAlliances(campaignId)
      } else if (tab === 'tripulacao') {
        crewData = await getCrew(campaignId)
      } else if (tab === 'comunicacao') {
        comms = await getComms(campaignId)
        mushiToast = null
      } else if (tab === 'diretivas') {
        directives = (await listDirectives(campaignId)).filter((d) => d.active)
      } else if (tab === 'fios') {
        threadsData = await getThreads(campaignId)
      } else if (tab === 'jornal') {
        newsUnread = 0
        newsToast = null
        const d = await listNews(campaignId)
        newsEditions = d.editions ?? newsEditions
        newsNemesis = d.nemesis ?? null
      } else if (tab === 'final') {
        endingToast = null
        endingData = await getEnding(campaignId)
        poneglyphData = await getPoneglyphs(campaignId)
      }
    } catch (e) {
      loadError = String(e)
    }
  }

  function seedPlayerDraft() {
    const cc = player?.character_creation ?? {}
    const snap = player?.player_snapshot ?? {}
    playerDraft = {
      name: cc.name ?? player?.name ?? '',
      dream: cc.dream ?? '',
      weapon: cc.weapon ?? '',
      gender: cc.gender ?? '',
      appearance: cc.appearance ?? '',
      tier: snap.tier ?? cc.tier_alvo ?? 'NORMAL',
      alignment_value: snap.alignment?.value ?? 0,
      belly: snap.belly ?? 0,
    }
    playerMsg = ''
  }

  async function savePlayer() {
    savingPlayer = true
    playerMsg = ''
    try {
      const patch = {
        name: playerDraft.name,
        dream: playerDraft.dream,
        weapon: playerDraft.weapon,
        gender: playerDraft.gender,
        appearance: playerDraft.appearance,
        tier: playerDraft.tier,
        alignment_value: Number(playerDraft.alignment_value),
        belly: Math.max(0, parseInt(playerDraft.belly, 10) || 0),
      }
      const r = await editPlayer(campaignId, patch)
      player = r.player
      playerMsg = t('ficha.saved')
    } catch (e) {
      playerMsg = t('common.error', { msg: e.message })
    } finally {
      savingPlayer = false
    }
  }

  function startEditTech(t) {
    editingTechId = t.id
    techDraft = { name: t.name ?? '', description: t.description ?? '' }
  }
  async function saveTech() {
    try {
      await editTechnique(campaignId, editingTechId, { name: techDraft.name, description: techDraft.description })
      techniques = await listTechniques(campaignId)
      editingTechId = null
    } catch (e) {
      loadError = String(e)
    }
  }
  async function removeTech(id) {
    try {
      await deleteTechnique(campaignId, id)
      techniques = techniques.filter((t) => t.id !== id)
    } catch (e) {
      loadError = String(e)
    }
  }

  function startEditBrk(b) {
    editingBrkKind = b.kind
    brkDraft = { description: b.description ?? '' }
  }
  async function saveBrk() {
    try {
      const r = await editBreakthrough(campaignId, editingBrkKind, { description: brkDraft.description })
      player = r.player
      editingBrkKind = null
    } catch (e) {
      loadError = String(e)
    }
  }
  async function removeBrk(kind) {
    try {
      const r = await deleteBreakthrough(campaignId, kind)
      player = r.player
    } catch (e) {
      loadError = String(e)
    }
  }
  function startEditFruit(i, e) {
    editingFruitIdx = i
    fruitDraft = { usage_summary: e.usage_summary ?? '' }
  }
  async function saveFruit() {
    try {
      const r = await editFruitUsage(campaignId, editingFruitIdx, { usage_summary: fruitDraft.usage_summary })
      player = r.player
      editingFruitIdx = null
    } catch (e) {
      loadError = String(e)
    }
  }
  async function removeFruit(i) {
    try {
      const r = await deleteFruitUsage(campaignId, i)
      player = r.player
    } catch (e) {
      loadError = String(e)
    }
  }

  async function refreshCrystals() {
    try {
      const d = await getCampaign(campaignId)
      crystals = d.crystals
    } catch {
      /* keep current */
    }
  }

  async function loadCards() {
    try {
      cards = await listCards(campaignId)
      cardsLoaded = true
    } catch {
      /* keep current */
    }
  }

  function onSearchInput() {
    clearTimeout(searchTimer)
    const q = searchQuery.trim()
    if (!q) {
      searchResults = null
      return
    }
    searchTimer = setTimeout(async () => {
      try {
        searchResults = await searchMemory(campaignId, q)
      } catch {
        searchResults = { cards: [], crystals: [] }
      }
    }, 250)
  }

  function startEditCrystal(c) {
    editingCrystalId = c.id
    crystalDraft = { fact: c.fact ?? '', category: c.category ?? '' }
  }
  async function saveCrystal() {
    try {
      await editCrystal(campaignId, editingCrystalId, { fact: crystalDraft.fact, category: crystalDraft.category })
      crystals = crystals.map((c) => (c.id === editingCrystalId ? { ...c, ...crystalDraft } : c))
      editingCrystalId = null
    } catch (e) {
      loadError = String(e)
    }
  }
  async function removeCrystal(id) {
    try {
      await deleteCrystal(campaignId, id)
      crystals = crystals.filter((c) => c.id !== id)
    } catch (e) {
      loadError = String(e)
    }
  }

  // The card list/search carry only the summary; hydrate the full body (backstory, age, identity)
  // from the card so the editor can change every field, not just the basics.
  async function startEditCard(c) {
    editingCardId = c.story_card_id
    const seed = (data = {}) => {
      const cs = data.current_state ?? {}
      const ap = data.appearance ?? {}
      const pe = data.personality ?? {}
      const hi = data.history ?? {}
      cardDraft = {
        kind: c.kind,
        name: data.name ?? c.name ?? '',
        summary: cs.summary_text ?? c.summary ?? '',
        status: data.status ?? c.status ?? '',
        tier: cs.tier ?? data.tier ?? c.tier ?? '',
        aliases: (data.aliases ?? c.aliases ?? []).join(', '),
        age: data.age_at_creation ?? '',
        race: data.race ?? '',
        klass: data.class ?? '',
        affiliation: data.affiliation ?? '',
        backstory: data.base_backstory ?? '',
        description: data.description ?? '',
        traits: (data.traits ?? []).join(', '),
        currentGoal: data.current_goal ?? '',
        longTermDream: data.long_term_dream ?? '',
        mood: data.mood ?? '',
        voiceNotes: (data.voice_notes ?? []).join(', '),
        devilFruit: data.devil_fruit ?? '',
        expressiveness: data.expressiveness ?? '',
        knowledgeClearance: data.knowledge_clearance ?? '',
        narrativeArmor: data.narrative_armor ?? '',
        alignment: data.alignment_baseline ?? '',
        haki: (data.haki_profile ?? []).join(', '),
        flags: (cs.flags ?? []).join(', '),
        appBuild: ap.build_and_age ?? '',
        appFace: ap.face_and_hair ?? '',
        appClothing: ap.clothing ?? '',
        appMark: ap.distinctive_mark ?? '',
        persDisp: pe.disposition ?? '',
        persShows: pe.shows_as ?? '',
        histOrigin: hi.origin ?? '',
        histEvent: hi.defining_event ?? '',
        histBond: hi.central_bond ?? '',
      }
    }
    seed()
    try {
      seed((await getCard(campaignId, c.story_card_id)).data)
    } catch (e) {
      loadError = String(e)
    }
  }
  async function saveCard() {
    try {
      const csv = (s) => (s ?? '').split(',').map((x) => x.trim()).filter(Boolean)
      const patch = {
        name: cardDraft.name,
        summary: cardDraft.summary,
        status: cardDraft.status,
        aliases: csv(cardDraft.aliases),
      }
      if (cardDraft.tier && TIERS.includes(cardDraft.tier)) patch.tier = cardDraft.tier
      if (cardDraft.kind === 'npc_agent') {
        patch.base_backstory = cardDraft.backstory
        patch.description = cardDraft.description
        patch.race = cardDraft.race
        patch.class = cardDraft.klass
        patch.affiliation = cardDraft.affiliation
        patch.current_goal = cardDraft.currentGoal
        patch.long_term_dream = cardDraft.longTermDream
        patch.mood = cardDraft.mood
        patch.devil_fruit = cardDraft.devilFruit
        patch.traits = csv(cardDraft.traits)
        patch.voice_notes = csv(cardDraft.voiceNotes)
        patch.flags = csv(cardDraft.flags)
        patch.haki_profile = csv(cardDraft.haki).map((h) => h.toUpperCase())
        patch.appearance = {
          build_and_age: cardDraft.appBuild,
          face_and_hair: cardDraft.appFace,
          clothing: cardDraft.appClothing,
          distinctive_mark: cardDraft.appMark,
        }
        patch.personality = { disposition: cardDraft.persDisp, shows_as: cardDraft.persShows }
        patch.history = {
          origin: cardDraft.histOrigin,
          defining_event: cardDraft.histEvent,
          central_bond: cardDraft.histBond,
        }
        if (EXPRESSIVENESS.includes(cardDraft.expressiveness)) patch.expressiveness = cardDraft.expressiveness
        if (KNOWLEDGE_TIERS.includes(cardDraft.knowledgeClearance)) patch.knowledge_clearance = cardDraft.knowledgeClearance
        if (NARRATIVE_ARMORS.includes(cardDraft.narrativeArmor)) patch.narrative_armor = cardDraft.narrativeArmor
        if (cardDraft.alignment !== '' && cardDraft.alignment != null) patch.alignment_baseline = Number(cardDraft.alignment)
        patch.age_at_creation =
          cardDraft.age === '' || cardDraft.age == null ? null : Number(cardDraft.age)
      }
      await editCard(campaignId, editingCardId, patch)
      cardsLoaded = false
      await loadCards()
      // Edited from the search results: refresh them too so the row reflects the save.
      if (searchResults && searchQuery.trim()) {
        try {
          searchResults = await searchMemory(campaignId, searchQuery.trim())
        } catch {
          /* keep current results */
        }
      }
      editingCardId = null
    } catch (e) {
      loadError = String(e)
    }
  }

  async function saveBelly() {
    savingBelly = true
    try {
      const r = await editPlayer(campaignId, { belly: Math.max(0, parseInt(bellyDraft, 10) || 0) })
      const snap = r.player?.player_snapshot ?? {}
      if (economy) economy = { ...economy, belly: snap.belly, belly_bucket: bucketOf(snap.belly) }
    } catch (e) {
      loadError = String(e)
    } finally {
      savingBelly = false
    }
  }
  // Client mirror of economy.belly_bucket for instant reflection; the server is authoritative.
  function bucketOf(b) {
    b = Math.max(0, b || 0)
    if (b < 50_000) return 'broke'
    if (b < 5_000_000) return 'surviving'
    if (b < 100_000_000) return 'wealthy'
    if (b < 1_000_000_000) return 'fortune'
    return 'treasure'
  }

  function startCreateItem() {
    editingItemId = null
    creatingItem = true
    itemDraft = { name: '', subtype: '', quantity: '', summary: '', origin_note: '' }
  }
  function startEditItem(it) {
    creatingItem = false
    editingItemId = it.item_card_id
    itemDraft = {
      name: it.name ?? '',
      subtype: it.subtype ?? '',
      quantity: it.quantity ?? '',
      summary: it.summary ?? '',
      origin_note: it.origin_note ?? '',
    }
  }
  async function saveItem() {
    if (!itemDraft.name?.trim()) return
    try {
      const body = {
        name: itemDraft.name.trim(),
        subtype: itemDraft.subtype ?? '',
        summary: itemDraft.summary ?? '',
        origin_note: itemDraft.origin_note ?? '',
        quantity:
          itemDraft.quantity === '' || itemDraft.quantity == null
            ? null
            : Math.max(0, parseInt(itemDraft.quantity, 10) || 0),
      }
      if (creatingItem) await addInventoryItem(campaignId, body)
      else await editInventoryItem(campaignId, editingItemId, body)
      economy = await getEconomy(campaignId)
      editingItemId = null
      creatingItem = false
    } catch (e) {
      loadError = String(e)
    }
  }
  async function removeItem(it) {
    try {
      await deleteInventoryItem(campaignId, it.item_card_id)
      economy = await getEconomy(campaignId)
    } catch (e) {
      loadError = String(e)
    }
  }

  async function saveJolly() {
    jollySaving = true
    try {
      const r = await setJollyRoger(campaignId, jollyDraft.trim())
      if (fleet) fleet = { ...fleet, jolly_roger: r.jolly_roger ?? '' }
      jollyDraft = r.jolly_roger ?? ''
    } catch {
      /* keep draft */
    } finally {
      jollySaving = false
    }
  }
  function startEditShip() {
    if (!fleet?.active) return
    editingCardId = fleet.active.ship_card_id
    cardDraft = {
      name: fleet.active.name ?? '',
      description: fleet.active.description ?? '',
      hull_condition: fleet.active.hull_condition ?? 'pristine',
    }
  }
  async function saveShip() {
    try {
      await editCard(campaignId, editingCardId, {
        name: cardDraft.name,
        description: cardDraft.description,
        hull_condition: cardDraft.hull_condition,
      })
      fleet = await getFleet(campaignId)
      editingCardId = null
    } catch (e) {
      loadError = String(e)
    }
  }

  function startEditProse(e) {
    editingTurnKey = e.key
    proseDraft = e.prose ?? ''
    rerollOpen = false
  }
  async function saveProse() {
    if (!editingTurnKey) return
    savingProse = true
    try {
      const ti = Number(editingTurnKey.slice(1))
      const r = await editTurnProse(campaignId, ti, proseDraft)
      entries = entries.map((e) => (e.key === editingTurnKey ? { ...e, prose: r.prose } : e))
      editingTurnKey = null
      await scrollDown()
    } catch (e) {
      loadError = String(e)
    } finally {
      savingProse = false
    }
  }

  async function removeDirective(id) {
    try {
      await deactivateDirective(campaignId, id)
      directives = directives.filter((d) => d.id !== id)
    } catch {
      /* no-op */
    }
  }

  function onNewsArrival(edition) {
    newsEditions = [...newsEditions, edition]
    newsUnread += 1
    newsToast = { headline: edition.headline, day: edition.scheduled_day }
    clearTimeout(newsToastTimer)
    newsToastTimer = setTimeout(() => (newsToast = null), 6000)
  }

  function parseNews(md) {
    const blocks = []
    for (const raw of (md ?? '').split(/\n/)) {
      const line = raw.trimEnd()
      if (!line.trim()) continue
      if (line.startsWith('### ')) blocks.push({ type: 'h3', spans: newsInline(line.slice(4)) })
      else if (line.startsWith('## ')) blocks.push({ type: 'h2', spans: newsInline(line.slice(3)) })
      else if (line.startsWith('# ')) blocks.push({ type: 'h1', spans: newsInline(line.slice(2)) })
      else if (line.startsWith('- ')) blocks.push({ type: 'li', spans: newsInline(line.slice(2)) })
      else if (/^_.*_$/.test(line.trim())) blocks.push({ type: 'cap', spans: newsInline(line.trim().replace(/^_|_$/g, '')) })
      else blocks.push({ type: 'p', spans: newsInline(line) })
    }
    return blocks
  }

  function newsInline(text) {
    const out = []
    const re = /\*\*([^*]+)\*\*|_([^_]+)_/g
    let last = 0
    let m
    while ((m = re.exec(text))) {
      if (m.index > last) out.push({ t: text.slice(last, m.index) })
      if (m[1] != null) out.push({ t: m[1], b: true })
      else out.push({ t: m[2], i: true })
      last = m.index + m[0].length
    }
    if (last < text.length) out.push({ t: text.slice(last) })
    return out
  }

  function playMushiBeep() {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext
      if (!Ctx) return
      const ctx = new Ctx()
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.setValueAtTime(640, ctx.currentTime)
      gain.gain.setValueAtTime(0.0001, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.1, ctx.currentTime + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.34)
      osc.connect(gain).connect(ctx.destination)
      osc.start()
      osc.stop(ctx.currentTime + 0.36)
      osc.onended = () => ctx.close()
    } catch {
      /* audio optional */
    }
  }

  function onMushiArrival(call) {
    playMushiBeep()
    mushiToast = { motive: call.caller_motive_hint || '', kind: call.mushi_kind || 'baby' }
    clearTimeout(mushiToastTimer)
    mushiToastTimer = setTimeout(() => (mushiToast = null), 7000)
  }

  // Toast when an NPC asks to join the crew; shows the most recent offer added this turn.
  function onCrewChange(crewReport) {
    const added = crewReport?.offers_added
    if (added && added.length) {
      crewOffer = added[added.length - 1]
    }
  }

  async function respondOffer(accept) {
    if (!crewOffer) return
    const npcId = crewOffer.id
    crewOffer = null
    try {
      await respondCrewOffer(campaignId, npcId, accept)
      if (hudTab === 'tripulacao') loadTab('tripulacao')
    } catch (e) {
      loadError = String(e)
    }
  }

  // The Director detected a reached ending this turn; the epilogue cinematic plays on its own.
  function onEndingReached(ending, epilogueProse) {
    if (epilogueProse) {
      epilogue = { kind: ending.kind, prose: epilogueProse, valence: ending.valence }
    } else {
      endingToast = { kind: ending.kind, valence: ending.valence }
      clearTimeout(endingToastTimer)
      endingToastTimer = setTimeout(() => (endingToast = null), 9000)
    }
  }

  function onPoneglyphArrival(m) {
    const headline = m.laugh_tale_revealed
      ? t('laughtale.revealed')
      : t('poneglyph.deciphered', { name: m.poneglyph_revealed?.[0]?.name || t('poneglyph.fallback') })
    newsToast = { headline, day: clock?.campaign_day ?? 0 }
    clearTimeout(newsToastTimer)
    newsToastTimer = setTimeout(() => (newsToast = null), 6000)
  }

  async function scrollDown() {
    await tick()
    if (logEl) logEl.scrollTop = logEl.scrollHeight
  }

  function tokenize(text) {
    const out = []
    const re = /@([\p{L}][\p{L}0-9_'’-]*(?: (?:[\p{Lu}]\.|[\p{Lu}][\p{L}0-9_'’-]*))*)/gu
    let last = 0
    let m
    while ((m = re.exec(text))) {
      if (m.index > last) out.push({ t: text.slice(last, m.index) })
      out.push({ npc: m[1] })
      last = m.index + m[0].length
    }
    if (last < text.length) out.push({ t: text.slice(last) })
    return out
  }

  function paragraphs(prose) {
    return prose.split(/\n{2,}/).flatMap((block) => block.split(/\n/)).filter((p) => p.trim())
  }

  function isDialogue(p) {
    return p.trimStart().startsWith('—')
  }

  onMount(async () => {
    await load()
    connect()
  })
  onDestroy(() => {
    wsClosing = true
    if (wsReconnectTimer) clearTimeout(wsReconnectTimer)
    ws?.close()
  })
</script>

<div class="game">
  <div class="topbar">
    <button class="ghost" onclick={onback}>{t('game.campaigns')}</button>
    <div class="title">
      <span class="cname">{meta?.name ?? '…'}</span>
      <span class="carc">{meta?.current_arc ?? ''}</span>
    </div>
    <div class="clockbox">
      {#if clock}
        <span title={t('game.player_age')}>⌖ {clock.current_player_age}a</span>
        <span title={t('game.campaign_day')}>{t('game.day', { n: clock.campaign_day })}</span>
      {/if}
      <button class="ghost" onclick={openMap} title={t('game.map_title')}>{t('game.map')}</button>
      <button
        class="ghost hud-menu"
        class:alert={hudAlerts > 0}
        class:on={hudTab != null}
        data-testid="hud-menu"
        onclick={() => (hudTab ? closeHud() : openHud('ficha'))}
        title={t('game.menu_title')}
      >
        {t('game.menu')}{hudAlerts > 0 ? ` ●${hudAlerts}` : ''}
      </button>
      <button class="ghost" class:on={devtoolsOpen} onclick={toggleDevtools} title={t('game.devtools_title')}>
        Devtools{traces.length ? ` (${traces.length})` : ''}
      </button>
    </div>
  </div>

  {#if scene}
    <div class="scenestrip">
      <span class="loc">{scene.location}</span>
      <span class="amb">{scene.ambient}</span>
      <span class="present">
        {#each presentNpcs as n (n.name)}
          <span class="chip" class:crew={n.affiliation === 'player_crew'}>{n.name}</span>
        {/each}
      </span>
    </div>
  {/if}

  <div class="log" bind:this={logEl}>
    <div class="column">
      {#if loadError}
        <p class="err">{loadError}</p>
      {/if}

      {#each entries as e (e.key)}
        {#if e.kind === 'turn'}
          <div class="turn">
            {#if e.action}
              <p class="action">› {e.action}</p>
            {/if}
            {#if e.audit && !e.audit.error && (e.audit.applied?.length || e.audit.prose_rewritten)}
              <p class="audit-seal" title={auditTitle(e.audit)} data-testid={`audit-seal-${e.key}`}>
                {t('game.audited')}{e.audit.applied?.length ? t(e.audit.applied.length === 1 ? 'game.audit_fix_one' : 'game.audit_fix_many', { n: e.audit.applied.length }) : ''}
              </p>
            {/if}
            {#if editingTurnKey === e.key}
              <div class="prose-edit" data-testid="prose-edit">
                <textarea bind:value={proseDraft} rows="8"></textarea>
                <div class="edit-actions">
                  <button class="send" onclick={saveProse} disabled={savingProse}>{savingProse ? t('common.saving') : t('game.save_prose')}</button>
                  <button class="ghost" onclick={() => (editingTurnKey = null)}>{t('common.cancel')}</button>
                </div>
              </div>
            {:else}
              {#each paragraphs(e.prose) as p}
                <p class="prose" class:dlg={isDialogue(p)}>
                  {#each tokenize(p) as tok}{#if tok.npc}<span class="npc">{tok.npc}</span>{:else}{tok.t}{/if}{/each}
                </p>
              {/each}
              {#if !pending}
                <!-- Turn commands: edit always, regenerate/rewind only on the last turn. -->
                <div class="turn-tools">
                  <button class="tool" onclick={() => startEditProse(e)} title={t('game.edit_prose')} data-testid={`edit-prose-${e.key}`}>✎</button>
                  {#if e.key === lastTurnKey}
                    <button
                      class="tool"
                      class:on={rerollOpen}
                      onclick={() => (rerollOpen = !rerollOpen)}
                      disabled={busy || rerolling}
                      title={t('game.regen_title')}
                      data-testid="regenerate-toggle">↻</button>
                    <!-- No rewind on the opening turn: no player action to restore. -->
                    {#if e.key !== 't1'}
                      <button
                        class="tool"
                        onclick={voltar}
                        disabled={busy || rerolling}
                        title={t('game.rewind_title')}
                        data-testid="rewind-turn">⤺</button>
                    {/if}
                  {/if}
                </div>
                {#if e.key === lastTurnKey && rerollOpen}
                  <div class="reroll-pop" data-testid="reroll-pop">
                    <textarea
                      rows="5"
                      bind:value={rerollNote}
                      disabled={busy || rerolling}
                      placeholder={t('game.reroll_ph')}
                      data-testid="reroll-note"
                    ></textarea>
                    <button class="send" onclick={regenerar} disabled={busy || rerolling} data-testid="regenerate-turn">
                      {rerolling ? t('game.regenerating') : t('game.regenerate')}
                    </button>
                  </div>
                {/if}
              {/if}
            {/if}
            <hr class="turnsep" />
          </div>
        {:else if e.kind === 'meta_q'}
          {#if e.action}
            <p class="action meta">⌥ {e.action}</p>
          {/if}
          <div class="ooc">
            {#each paragraphs(e.response_text) as p}
              <p>{p}</p>
            {/each}
          </div>
        {:else if e.kind === 'meta_note'}
          <p class="meta-note">{t('game.meta_note', { text: e.text })}</p>
        {/if}
      {/each}

      {#if pending}
        {#if pending.action}
          <p class="action" class:meta={pending.meta}>{pending.meta ? '⌥' : '›'} {pending.action}</p>
        {/if}
        {#if !pending.meta}
          {#each paragraphs(pending.prose) as p}
            <p class="prose" class:dlg={isDialogue(p)}>
              {#each tokenize(p) as tok}{#if tok.npc}<span class="npc">{tok.npc}</span>{:else}{tok.t}{/if}{/each}
            </p>
          {/each}
        {/if}
        <p class="phase">{phaseLabel(pending.phase)}<span class="caret"></span></p>
      {/if}
    </div>
  </div>

  {#if turnError}
    <div class="column turn-error" class:quota={turnError.kind === 'quota'} role="alert">
      <div class="turn-error-inner">
        <span class="te-icon">{turnError.kind === 'quota' ? '◷' : turnError.kind === 'refusal' ? '⊘' : '!'}</span>
        <div class="te-body">
          <strong>
            {#if turnError.kind === 'quota'}{t('game.err_quota_title')}
            {:else if turnError.kind === 'refusal'}{t('game.err_refusal_title')}
            {:else}{t('game.err_generic_title')}{/if}
          </strong>
          <span>
            {#if turnError.kind === 'quota'}
              {t('game.err_quota_body', { suffix: turnError.retryAfter ? t('game.err_quota_suffix', { min: Math.ceil(turnError.retryAfter / 60) }) : '' })}
            {:else if turnError.kind === 'refusal'}
              {t('game.err_refusal_body')}
            {:else}
              {turnError.message || t('game.err_generic_fallback')}{t('game.err_generic_tail')}
            {/if}
          </span>
        </div>
        <button class="ghost te-dismiss" onclick={() => (turnError = null)} title={t('game.dismiss')}>✕</button>
      </div>
    </div>
  {/if}

  {#if turnNotice}
    <div class="column turn-error" role="status">
      <div class="turn-error-inner">
        <span class="te-icon">◷</span>
        <div class="te-body"><span>{turnNotice}</span></div>
        <button class="ghost te-dismiss" onclick={() => (turnNotice = null)} title={t('game.dismiss')}>✕</button>
      </div>
    </div>
  {/if}

  <div class="composer">
    <div class="column composer-inner">
      <select bind:value={actionType} disabled={busy && !proseDone} title={t('game.action_type')}>
        <option value="DO">{t('game.do')}</option>
        <option value="META">{t('game.meta')}</option>
      </select>
      <textarea
        bind:value={input}
        onkeydown={onKey}
        {placeholder}
        disabled={(busy && !proseDone) || !connected}
        rows="2"
      ></textarea>
      <button class="send" onclick={send} disabled={(busy && !proseDone) || !connected || !input.trim()}>
        {!busy ? t('game.act') : !proseDone ? '…' : queued ? t('game.queued') : t('game.enqueue')}
      </button>
    </div>
  </div>

  <!-- Unified HUD: single drawer with typed tabs. -->
  {#if hudTab}
    <aside class="drawer hud" data-testid="hud">
      <nav class="hud-nav" data-testid="hud-tabs">
        {#each HUD_GROUPS as g (g.key)}
          <p class="hud-group">{t(`hud.group.${g.key}`)}</p>
          {#each g.tabs as id (id)}
            <button
              class="hud-tab"
              class:active={hudTab === id}
              class:alert={tabAlert(id) > 0}
              data-testid={`hud-tab-${id}`}
              onclick={() => openHud(id)}
            >
              <span class="hud-tab-label">{tabLabel(id)}</span>
              {#if tabAlert(id) > 0}<span class="hud-count">{tabAlert(id)}</span>{/if}
            </button>
          {/each}
        {/each}
      </nav>

      <section class="hud-main">
        <div class="hud-head">
          <h3>{tabLabel(hudTab)}</h3>
          <button class="ghost hud-close" onclick={closeHud} title={t('hud.close')} aria-label={t('hud.close')}>✕</button>
        </div>

        <div class="hud-body">
        {#if hudTab === 'ficha'}
          {#if !player}
            <p class="hint">{t('ficha.loading')}</p>
          {:else}
            <p class="hint">{t('ficha.hint')}</p>
            <div class="editform two-col" data-testid="ficha-form">
              <label class="span2">{t('ficha.name')} <input bind:value={playerDraft.name} data-testid="edit-name" /></label>
              <label class="span2">{t('ficha.appearance')} <textarea rows="3" bind:value={playerDraft.appearance} data-testid="edit-appearance"></textarea></label>
              <label class="span2">{t('ficha.dream')} <input bind:value={playerDraft.dream} /></label>
              <label>{t('ficha.weapon')} <input bind:value={playerDraft.weapon} /></label>
              <label>{t('ficha.gender')} <input bind:value={playerDraft.gender} /></label>
              <label>{t('ficha.tier')}
                <select bind:value={playerDraft.tier} data-testid="edit-tier">
                  {#each TIERS as tr}<option value={tr}>{tr}</option>{/each}
                </select>
              </label>
              <label>{t('ficha.alignment')}
                <select bind:value={playerDraft.alignment_value} data-testid="edit-alignment">
                  {#each alignOptions as a}<option value={a.v}>{a.label}</option>{/each}
                </select>
                <span class="dim">{t('ficha.bucket', { b: alignBucket(playerDraft.alignment_value) })}</span>
              </label>
              <div class="form-foot span2">
                <button class="send" onclick={savePlayer} disabled={savingPlayer} data-testid="save-ficha">
                  {savingPlayer ? t('common.saving') : t('ficha.save')}
                </button>
                {#if playerMsg}<span class="savemsg" data-testid="ficha-msg">{playerMsg}</span>{/if}
              </div>
            </div>
            <h4 class="comms-sub">{t('ficha.story_defined')}</h4>
            <ul class="props">
              <li><span class="pk">{t('ficha.class')}</span><span class="pv">{player.character_creation?.class_display ?? player.player_character?.class ?? '—'}</span></li>
              <li><span class="pk">{t('ficha.fruit')}</span><span class="pv">{player.player_character?.fruit ?? t('ficha.no_fruit')}</span></li>
              <li><span class="pk">{t('ficha.haki')}</span><span class="pv">{(player.player_snapshot?.haki ?? []).join(', ') || t('ficha.haki_dormant')}</span></li>
              <li><span class="pk">{t('ficha.bounty')}</span><span class="pv">{player.player_snapshot?.bounty?.current_amount ?? 0}</span></li>
            </ul>
          {/if}

        {:else if hudTab === 'memoria'}
          {#snippet cardEditFields(c)}
            <input class="editinput" bind:value={cardDraft.name} placeholder={t('card.name')} data-testid="card-name-input" />
            <input class="editinput" bind:value={cardDraft.aliases} placeholder={t('card.aliases')} />
            {#if c.kind === 'npc_agent'}
              <div class="edit-grid">
                <input class="editinput" type="number" min="0" bind:value={cardDraft.age} placeholder={t('card.age')} />
                <input class="editinput" bind:value={cardDraft.race} placeholder={t('card.race')} />
                <input class="editinput" bind:value={cardDraft.klass} placeholder={t('card.class')} />
              </div>
              <input class="editinput" bind:value={cardDraft.affiliation} placeholder={t('card.affiliation')} />
              <select class="editinput" bind:value={cardDraft.tier}>
                <option value="">{t('card.tier_unchanged')}</option>
                {#each TIERS as tr}<option value={tr}>{tr}</option>{/each}
              </select>
            {/if}
            <input class="editinput" bind:value={cardDraft.status} placeholder={t('card.status')} />
            <textarea class="editinput" rows="2" bind:value={cardDraft.summary} placeholder={t('card.summary')}></textarea>
            {#if c.kind === 'npc_agent'}
              <textarea class="editinput" rows="2" bind:value={cardDraft.description} placeholder={t('card.description')}></textarea>
              <textarea class="editinput" rows="4" bind:value={cardDraft.backstory} placeholder={t('card.backstory')}></textarea>
              <input class="editinput" bind:value={cardDraft.traits} placeholder={t('card.traits')} />
              <input class="editinput" bind:value={cardDraft.currentGoal} placeholder={t('card.current_goal')} />
              <input class="editinput" bind:value={cardDraft.longTermDream} placeholder={t('card.long_term_dream')} />
              <input class="editinput" bind:value={cardDraft.mood} placeholder={t('card.mood')} />
              <input class="editinput" bind:value={cardDraft.voiceNotes} placeholder={t('card.voice_notes')} />
              <textarea class="editinput" rows="2" bind:value={cardDraft.appBuild} placeholder={t('card.app_build')}></textarea>
              <textarea class="editinput" rows="2" bind:value={cardDraft.appFace} placeholder={t('card.app_face')}></textarea>
              <textarea class="editinput" rows="2" bind:value={cardDraft.appClothing} placeholder={t('card.app_clothing')}></textarea>
              <textarea class="editinput" rows="2" bind:value={cardDraft.appMark} placeholder={t('card.app_mark')}></textarea>
              <textarea class="editinput" rows="2" bind:value={cardDraft.persDisp} placeholder={t('card.pers_disp')}></textarea>
              <textarea class="editinput" rows="2" bind:value={cardDraft.persShows} placeholder={t('card.pers_shows')}></textarea>
              <textarea class="editinput" rows="2" bind:value={cardDraft.histOrigin} placeholder={t('card.hist_origin')}></textarea>
              <textarea class="editinput" rows="2" bind:value={cardDraft.histEvent} placeholder={t('card.hist_event')}></textarea>
              <textarea class="editinput" rows="2" bind:value={cardDraft.histBond} placeholder={t('card.hist_bond')}></textarea>
              <div class="edit-grid">
                <input class="editinput" bind:value={cardDraft.devilFruit} placeholder={t('card.devil_fruit')} />
                <input class="editinput" bind:value={cardDraft.haki} placeholder={t('card.haki')} />
              </div>
              <div class="edit-grid">
                <select class="editinput" bind:value={cardDraft.expressiveness}>
                  <option value="">{t('card.expressiveness')}</option>
                  {#each EXPRESSIVENESS as e}<option value={e}>{e}</option>{/each}
                </select>
              </div>
              <div class="edit-grid">
                <select class="editinput" bind:value={cardDraft.knowledgeClearance}>
                  <option value="">{t('card.knowledge')}</option>
                  {#each KNOWLEDGE_TIERS as k}<option value={k}>{k}</option>{/each}
                </select>
                <select class="editinput" bind:value={cardDraft.narrativeArmor}>
                  <option value="">{t('card.armor')}</option>
                  {#each NARRATIVE_ARMORS as a}<option value={a}>{a}</option>{/each}
                </select>
              </div>
              <input class="editinput" type="number" step="0.1" min="-2" max="2" bind:value={cardDraft.alignment} placeholder={t('card.alignment')} />
              <input class="editinput" bind:value={cardDraft.flags} placeholder={t('card.flags')} />
            {/if}
            <div class="edit-actions">
              <button class="send sm" onclick={saveCard} data-testid="card-save">{t('common.save')}</button>
              <button class="ghost sm" onclick={() => (editingCardId = null)}>{t('common.cancel')}</button>
            </div>
          {/snippet}
          <input
            class="search"
            type="search"
            bind:value={searchQuery}
            oninput={onSearchInput}
            placeholder={t('memoria.search_ph')}
          />
          {#if searchResults}
            {#if (searchResults.cards?.length ?? 0) === 0 && (searchResults.crystals?.length ?? 0) === 0}
              <p class="hint">{t('memoria.no_results', { q: searchQuery.trim() })}</p>
            {:else}
              {#if searchResults.cards?.length}
                <p class="grouplbl">{t('memoria.cards_n', { n: searchResults.cards.length })}</p>
                <ul class="cards">
                  {#each searchResults.cards as c (c.story_card_id)}
                    <li data-testid="card-row">
                      {#if editingCardId === c.story_card_id}
                        {@render cardEditFields(c)}
                      {:else}
                        <span class="cardline">
                          <span class="cname-c">{c.name || c.id}</span>
                          <span class="kind">
                            {c.kind}{c.subtype ? ` · ${c.subtype}` : ''}{c.tier ? ` · ${c.tier}` : ''}{c.status && c.status !== 'alive' ? ` · ${c.status}` : ''}
                          </span>
                        </span>
                        {#if c.aliases?.length}<span class="aliases">{c.aliases.join(' · ')}</span>{/if}
                        {#if c.summary}<span class="fact">{c.summary}</span>{/if}
                        <div class="row-actions">
                          {#if c.kind === 'player'}
                            <button class="ghost sm" onclick={() => openHud('ficha')} title={t('memoria.player_sheet_title')}>{t('memoria.player_sheet_btn')}</button>
                          {:else}
                            <button class="ghost sm" onclick={() => startEditCard(c)} title={t('common.edit')} data-testid="card-edit">{t('memoria.edit_btn')}</button>
                          {/if}
                        </div>
                      {/if}
                    </li>
                  {/each}
                </ul>
              {/if}
              {#if searchResults.crystals?.length}
                <p class="grouplbl">{t('memoria.crystals_n', { n: searchResults.crystals.length })}</p>
                <ul class="crystals">
                  {#each searchResults.crystals as c (c.id)}
                    <li><span class="cat">{c.category}</span><span class="fact">{c.fact}</span></li>
                  {/each}
                </ul>
              {/if}
            {/if}
          {:else}
            <div class="tabs">
              <button class="tab" class:active={memTab === 'crystals'} onclick={() => (memTab = 'crystals')}>
                {t('memoria.crystals_n', { n: crystals.length })}
              </button>
              <button class="tab" class:active={memTab === 'cards'} onclick={() => (memTab = 'cards')}>
                {t('memoria.cards_n', { n: cards.length })}
              </button>
            </div>

            {#if memTab === 'crystals'}
              {#if crystals.length === 0}
                <p class="hint">{t('memoria.none_crystallized')}</p>
              {:else}
                <ul class="crystals">
                  {#each crystals as c, i (c.id ?? i)}
                    <li data-testid="crystal-row">
                      {#if editingCrystalId === c.id}
                        <input class="editinput" bind:value={crystalDraft.category} placeholder={t('memoria.category')} />
                        <textarea class="editinput" rows="3" bind:value={crystalDraft.fact}></textarea>
                        <div class="edit-actions">
                          <button class="send sm" onclick={saveCrystal}>{t('common.save')}</button>
                          <button class="ghost sm" onclick={() => (editingCrystalId = null)}>{t('common.cancel')}</button>
                        </div>
                      {:else}
                        <span class="cat">{c.category}</span>
                        <span class="fact">{c.fact}</span>
                        {#if c.id}
                          <div class="row-actions">
                            <button class="ghost sm" onclick={() => startEditCrystal(c)} title={t('common.edit')}>✎</button>
                            <button class="ghost sm del" onclick={() => removeCrystal(c.id)} title={t('common.delete')}>✕</button>
                          </div>
                        {/if}
                      {/if}
                    </li>
                  {/each}
                </ul>
              {/if}
            {:else}
              {#if !cardsLoaded}
                <p class="hint">{t('memoria.loading_cards')}</p>
              {:else if cards.length === 0}
                <p class="hint">{t('memoria.no_cards')}</p>
              {:else}
                <ul class="cards">
                  {#each cards as c (c.story_card_id)}
                    <li data-testid="card-row">
                      {#if editingCardId === c.story_card_id}
                        {@render cardEditFields(c)}
                      {:else}
                        <span class="cardline">
                          <span class="cname-c">{c.name || c.id}</span>
                          <span class="kind">
                            {c.kind}{c.tier ? ` · ${c.tier}` : ''}{c.status && c.status !== 'alive' ? ` · ${c.status}` : ''}
                          </span>
                        </span>
                        {#if c.aliases?.length}<span class="aliases">{c.aliases.join(' · ')}</span>{/if}
                        {#if c.summary}<span class="fact">{c.summary}</span>{/if}
                        <div class="row-actions">
                          {#if c.kind === 'player'}
                            <button class="ghost sm" onclick={() => openHud('ficha')} title={t('memoria.player_sheet_title')}>{t('memoria.player_sheet_btn')}</button>
                          {:else}
                            <button class="ghost sm" onclick={() => startEditCard(c)} title={t('common.edit')} data-testid="card-edit">{t('memoria.edit_btn')}</button>
                          {/if}
                        </div>
                      {/if}
                    </li>
                  {/each}
                </ul>
              {/if}
            {/if}
          {/if}

        {:else if hudTab === 'tecnicas'}
          <p class="hint">{t('tecnicas.hint')}</p>
          {#if techniques.length === 0}
            <p class="hint">{t('tecnicas.empty')}</p>
          {:else}
            <ul class="cards">
              {#each techniques as tec (tec.id)}
                <li data-testid="tech-row">
                  {#if editingTechId === tec.id}
                    <input class="editinput" bind:value={techDraft.name} placeholder={t('tecnicas.name')} />
                    <textarea class="editinput" rows="2" bind:value={techDraft.description} placeholder={t('tecnicas.description')}></textarea>
                    <div class="edit-actions">
                      <button class="send sm" onclick={saveTech}>{t('common.save')}</button>
                      <button class="ghost sm" onclick={() => (editingTechId = null)}>{t('common.cancel')}</button>
                    </div>
                  {:else}
                    <span class="cardline">
                      <span class="cname-c">{tec.name}</span>
                      <span class="kind">{tec.owner_name}{tec.usage_count ? ` · ×${tec.usage_count}` : ''}</span>
                    </span>
                    {#if tec.description}<span class="fact">{tec.description}</span>{/if}
                    <div class="row-actions">
                      <button class="ghost sm" onclick={() => startEditTech(tec)} title={t('common.edit')}>✎</button>
                      <button class="ghost sm del" onclick={() => removeTech(tec.id)} title={t('common.remove')}>✕</button>
                    </div>
                  {/if}
                </li>
              {/each}
            </ul>
          {/if}

        {:else if hudTab === 'combate'}
          {#if !player}
            <p class="hint">{t('common.loading')}</p>
          {:else}
            <p class="hint">{t('combate.hint')}</p>
            <h4 class="comms-sub">{t('combate.breakthroughs')}</h4>
            {#if (player.player_snapshot?.breakthroughs ?? []).length === 0}
              <p class="hint">{t('combate.brk_empty')}</p>
            {:else}
              <ul class="cards">
                {#each player.player_snapshot.breakthroughs as b (b.kind)}
                  <li data-testid="brk-row">
                    {#if editingBrkKind === b.kind}
                      <textarea class="editinput" rows="3" bind:value={brkDraft.description} placeholder={t('combate.brk_desc_ph')}></textarea>
                      <div class="edit-actions">
                        <button class="send sm" onclick={saveBrk}>{t('common.save')}</button>
                        <button class="ghost sm" onclick={() => (editingBrkKind = null)}>{t('common.cancel')}</button>
                      </div>
                    {:else}
                      <span class="cardline">
                        <span class="cname-c">{brkLabel(b.kind)}</span>
                        {#if b.unlocked_at_turn_index != null}<span class="kind">{t('combate.turn_n', { n: b.unlocked_at_turn_index })}</span>{/if}
                      </span>
                      {#if b.description}<span class="fact">{b.description}</span>{/if}
                      <div class="row-actions">
                        <button class="ghost sm" onclick={() => startEditBrk(b)} title={t('common.edit')}>✎</button>
                        <button class="ghost sm del" onclick={() => removeBrk(b.kind)} title={t('common.remove')}>✕</button>
                      </div>
                    {/if}
                  </li>
                {/each}
              </ul>
            {/if}

            <h4 class="comms-sub">{t('combate.fruit_usage')}</h4>
            {#if (player.player_snapshot?.fruit_usage_log ?? []).length === 0}
              <p class="hint">{t('combate.fruit_empty')}</p>
            {:else}
              <ul class="cards">
                {#each player.player_snapshot.fruit_usage_log as e, i (i)}
                  <li data-testid="fruit-row">
                    {#if editingFruitIdx === i}
                      <textarea class="editinput" rows="2" bind:value={fruitDraft.usage_summary} placeholder={t('combate.usage_ph')}></textarea>
                      <div class="edit-actions">
                        <button class="send sm" onclick={saveFruit}>{t('common.save')}</button>
                        <button class="ghost sm" onclick={() => (editingFruitIdx = null)}>{t('common.cancel')}</button>
                      </div>
                    {:else}
                      <span class="cardline">
                        <span class="kind">{t('combate.turn_n', { n: e.turn_index })}{e.fruit_id ? ` · ${e.fruit_id}` : ''}</span>
                      </span>
                      {#if e.usage_summary}<span class="fact">{e.usage_summary}</span>{/if}
                      <div class="row-actions">
                        <button class="ghost sm" onclick={() => startEditFruit(i, e)} title={t('common.edit')}>✎</button>
                        <button class="ghost sm del" onclick={() => removeFruit(i)} title={t('common.remove')}>✕</button>
                      </div>
                    {/if}
                  </li>
                {/each}
              </ul>
            {/if}
          {/if}

        {:else if hudTab === 'inventario'}
          <h4 class="comms-sub">{t('inventario.belly')}</h4>
          <div class="editform inline">
            <label>{t('inventario.amount')} <input type="number" min="0" bind:value={bellyDraft} data-testid="belly-input" /></label>
            <button class="send sm" onclick={saveBelly} disabled={savingBelly} data-testid="belly-save">{savingBelly ? t('common.saving') : t('inventario.save_belly')}</button>
          </div>

          {#snippet itemEditFields()}
            <input class="editinput" bind:value={itemDraft.name} placeholder={t('inventario.name_ph')} data-testid="item-name-input" />
            <div class="edit-grid">
              <input class="editinput" bind:value={itemDraft.subtype} placeholder={t('inventario.subtype_ph')} />
              <input class="editinput" type="number" min="0" bind:value={itemDraft.quantity} placeholder={t('inventario.qty_ph')} />
            </div>
            <textarea class="editinput" rows="2" bind:value={itemDraft.summary} placeholder={t('inventario.summary_ph')}></textarea>
            <input class="editinput" bind:value={itemDraft.origin_note} placeholder={t('inventario.origin_ph')} />
            <div class="edit-actions">
              <button class="send sm" onclick={saveItem} disabled={!itemDraft.name?.trim()} data-testid="item-save">{t('common.save')}</button>
              <button class="ghost sm" onclick={() => { creatingItem = false; editingItemId = null }}>{t('common.cancel')}</button>
            </div>
          {/snippet}

          <h4 class="comms-sub">{t('inventario.title')}</h4>
          {#if !creatingItem && editingItemId == null}
            <div class="edit-actions">
              <button class="ghost sm" onclick={startCreateItem} data-testid="item-new">{t('inventario.new')}</button>
            </div>
          {/if}
          {#if creatingItem}
            <div class="editform" data-testid="item-new-row">
              {@render itemEditFields()}
            </div>
          {/if}
          {#if !economy || economy.inventory.length === 0}
            {#if !creatingItem}<p class="hint">{t('inventario.empty')}</p>{/if}
          {:else}
            <ul class="commslist invlist">
              {#each economy.inventory as it (it.item_card_id)}
                <li data-testid="inv-row">
                  {#if editingItemId === it.item_card_id}
                    {@render itemEditFields()}
                  {:else}
                    <span class="cname">{it.name || it.item_card_id}</span>
                    {#if it.quantity != null}<span class="qty">×{it.quantity}</span>{/if}
                    {#if it.subtype}<span class="dim">{it.subtype}</span>{/if}
                    {#if it.summary}<span class="origin">{it.summary}</span>{/if}
                    {#if it.origin_note}<span class="aliases">{it.origin_note}</span>{/if}
                    <div class="row-actions">
                      <button class="ghost sm" onclick={() => startEditItem(it)} title={t('common.edit')} data-testid="item-edit">✎</button>
                      <button class="ghost sm del" onclick={() => removeItem(it)} title={t('common.remove')}>✕</button>
                    </div>
                  {/if}
                </li>
              {/each}
            </ul>
          {/if}

        {:else if hudTab === 'navio'}
          <h4 class="comms-sub">{t('navio.active')}</h4>
          {#if !fleet?.active}
            <p class="hint">{t('navio.none')}</p>
          {:else if editingCardId === fleet.active.ship_card_id}
            <div class="editform">
              <label>{t('navio.name')} <input bind:value={cardDraft.name} /></label>
              <label>{t('navio.description')} <textarea rows="3" bind:value={cardDraft.description}></textarea></label>
              <label>{t('navio.hull')}
                <select bind:value={cardDraft.hull_condition}>
                  {#each HULLS as h}<option value={h}>{hullLabel(h)}</option>{/each}
                </select>
              </label>
              <div class="edit-actions">
                <button class="send sm" onclick={saveShip}>{t('navio.save')}</button>
                <button class="ghost sm" onclick={() => (editingCardId = null)}>{t('common.cancel')}</button>
              </div>
            </div>
          {:else}
            <div class={`ship hull-${fleet.active.hull_condition || 'pristine'}`}>
              <div class="ship-line">
                <span class="cname">{fleet.active.name || t('navio.unnamed')}</span>
                {#if fleet.active.subtype}<span class="dim">{fleet.active.subtype}</span>{/if}
              </div>
              <span class="hull-bucket">{t('navio.hull_x', { x: hullLabel(fleet.active.hull_condition ?? '…') })}</span>
              <span class="dim">{hullHint(fleet.active.hull_condition)}</span>
              {#if fleet.active.description}<p class="origin">{fleet.active.description}</p>{/if}
              <button class="ghost sm" onclick={startEditShip} title={t('navio.edit')}>{t('navio.edit')}</button>
            </div>
          {/if}

          {#if fleet?.reserve?.length}
            <h4 class="comms-sub">{t('navio.reserve', { n: fleet.reserve.length })}</h4>
            <ul class="commslist invlist">
              {#each fleet.reserve as s (s.ship_card_id)}
                <li>
                  <span class="cname">{s.name || s.ship_card_id}</span>
                  {#if s.subtype}<span class="dim">{s.subtype}</span>{/if}
                  <span class="origin">{t('navio.hull_x', { x: hullLabel(s.hull_condition ?? '') })}</span>
                </li>
              {/each}
            </ul>
          {/if}

          <h4 class="comms-sub">{t('navio.jolly')}</h4>
          {#if fleet?.jolly_roger}
            <p class="origin">{fleet.jolly_roger}</p>
          {:else}
            <p class="hint">{t('navio.jolly_empty')}</p>
          {/if}
          <textarea
            class="jolly-input"
            rows="3"
            placeholder={t('navio.jolly_ph')}
            bind:value={jollyDraft}
          ></textarea>
          <button class="send jolly-save" onclick={saveJolly} disabled={jollySaving}>
            {jollySaving ? t('common.saving') : t('navio.declare_flag')}
          </button>

        {:else if hudTab === 'cartaz'}
          <p class="hint">{t('cartaz.hint')}</p>
          {#if !legendData || !legendData.targets?.length}
            <p class="hint">{t('cartaz.empty')}</p>
          {:else}
            {#each legendData.targets as tg (tg.card_id)}
              <div class="poster">
                {#if editingLegendId === tg.card_id}
                  <div class="poster-head">
                    <span class="poster-wanted">WANTED</span>
                    <select class="editinput poster-status-edit" bind:value={legendDraft.wanted_status}>
                      <option value="none">{t('wanted.none')}</option>
                      <option value="alive_only">{t('wanted.alive_only')}</option>
                      <option value="dead_or_alive">{t('wanted.dead_or_alive')}</option>
                    </select>
                  </div>
                  <div class="poster-name">{tg.name || '—'}{#if tg.is_player}<span class="dim">{t('cartaz.you')}</span>{/if}</div>
                  <input class="editinput" bind:value={legendDraft.epithet} placeholder={t('cartaz.epithet_ph')} />
                  <textarea class="editinput" rows="2" bind:value={legendDraft.public_image} placeholder={t('cartaz.image_ph')}></textarea>
                  <textarea class="editinput" rows="2" bind:value={legendDraft.divergence_note} placeholder={t('cartaz.divergence_ph')}></textarea>
                  <textarea class="editinput" rows="2" bind:value={legendDraft.poster_note} placeholder={t('cartaz.portrait_ph')}></textarea>
                  <div class="edit-actions">
                    <button class="send sm" onclick={saveLegend}>{t('common.save')}</button>
                    <button class="ghost sm" onclick={() => (editingLegendId = null)}>{t('common.cancel')}</button>
                  </div>
                {:else}
                  <div class="poster-head">
                    <span class="poster-wanted">WANTED</span>
                    <span class="poster-head-right">
                      {#if tg.wanted_status !== 'none'}
                        <span class="rep-badge poster-status">{wantedLabel(tg.wanted_status)}</span>
                      {/if}
                      <button class="ghost sm" onclick={() => startEditLegend(tg)} title={t('common.edit')}>✎</button>
                      {#if legendHasEntry(tg)}
                        <button class="ghost sm del" onclick={() => removeLegend(tg)} title={t('cartaz.delete')}>✕</button>
                      {/if}
                    </span>
                  </div>
                  <div class="poster-name">{tg.name || '—'}{#if tg.is_player}<span class="dim">{t('cartaz.you')}</span>{/if}</div>
                  {#if tg.epithet}<div class="poster-epithet">“{tg.epithet}”</div>{/if}
                  <div class="poster-bounty">{fmtBerries(tg.bounty)}</div>
                  {#if tg.poster_note}<p class="poster-note">{tg.poster_note}</p>{/if}
                  {#if tg.public_image}
                    <p class="poster-image"><span class="poster-label">{t('cartaz.image_label')}</span> {tg.public_image}</p>
                  {/if}
                  {#if tg.divergence_note}
                    <p class="poster-image poster-divergence"><span class="poster-label">{t('cartaz.divergence_label')}</span> {tg.divergence_note}</p>
                  {/if}
                  {#if tg.history?.length > 1}
                    <details class="poster-history">
                      <summary>{t('cartaz.history', { n: tg.history.length - 1 })}</summary>
                      <ul>
                        {#each tg.history.slice(0, -1).reverse() as h, i (i)}
                          <li>
                            <span class="dim">{t('combate.turn_n', { n: h.turn_index })}</span>
                            {#if h.epithet}<span class="poster-hist-epithet">“{h.epithet}”</span>{/if}
                            {#if h.public_image}<span>{h.public_image}</span>{/if}
                            {#if h.reason}<span class="dim">{h.reason}</span>{/if}
                          </li>
                        {/each}
                      </ul>
                    </details>
                  {/if}
                {/if}
              </div>
            {/each}
          {/if}

        {:else if hudTab === 'reputacao'}
          <p class="hint">{t('reputacao.hint')}</p>
          {#if !factionsData || factionsData.factions.length === 0}
            <p class="hint">{t('reputacao.empty')}</p>
          {:else}
            <ul class="commslist faction-list">
              {#each factionsData.factions as f (f.faction_id)}
                <li class={`faction-row rep-${f.player_bucket}`}>
                  <span class="cname">{f.name}</span>
                  <span class={`rep-badge rep-${f.player_bucket}`}>{repBucketLabel(f.player_bucket)}</span>
                  {#if f.crew_bucket !== f.player_bucket}
                    <span class="dim">{t('reputacao.crew', { x: repBucketLabel(f.crew_bucket) })}</span>
                  {/if}
                </li>
              {/each}
            </ul>
          {/if}
          {#if factionsData?.npcs?.length}
            <h4 class="comms-sub">{t('reputacao.npcs')}</h4>
            <ul class="commslist faction-list">
              {#each factionsData.npcs as n (n.id)}
                <li>
                  <span class="cname">{n.name || n.id}</span>
                  {#each n.reputations as r (r.faction_id)}
                    <span class={`rep-badge rep-${r.bucket}`}>{r.name}: {repBucketLabel(r.bucket)}</span>
                  {/each}
                </li>
              {/each}
            </ul>
          {/if}

        {:else if hudTab === 'aliancas'}
          <p class="hint">{t('aliancas.hint')}</p>
          {#if !alliancesData || alliancesData.alliances.length === 0}
            <p class="hint">{t('aliancas.empty')}</p>
          {:else}
            <ul class="commslist faction-list">
              {#each alliancesData.alliances as a (a.crew_b_id)}
                <li class="faction-row">
                  <span class="cname">{a.crew_b_display_name || a.crew_b_id}</span>
                  <span class="rep-badge">{formalityLabel(a.formality)}</span>
                  <span class="dim">{hierarchyLabel(a.hierarchy)}</span>
                  {#if a.origin_note}<span class="dim alliance-origin">{a.origin_note}</span>{/if}
                </li>
              {/each}
            </ul>
          {/if}
          {#if alliancesData?.recent_bounty_hunters?.length}
            <h4 class="comms-sub">{t('aliancas.hunters')}</h4>
            <ul class="commslist faction-list">
              {#each alliancesData.recent_bounty_hunters as h, i (i)}
                <li><span class="dim">{h.archetype || h.affiliation}</span></li>
              {/each}
            </ul>
          {/if}

        {:else if hudTab === 'tripulacao'}
          <p class="hint">{t('tripulacao.hint')}</p>
          {#if crewData}
            <p class="crew-align">
              {t('tripulacao.leaning')} <strong>{repBucketLabel(crewData.crew_alignment?.bucket)}</strong>
              · {crewData.size}/{crewData.soft_cap} {crewData.is_fleet ? t('tripulacao.fleet') : ''}
            </p>
          {/if}
          {#if crewData?.pending_offers?.length}
            <h4 class="comms-sub">{t('tripulacao.offers')}</h4>
            <ul class="commslist">
              {#each crewData.pending_offers as o (o.npc_id)}
                <li class="offer-row">
                  <span class="cname">{o.npc_name || o.npc_id}</span>
                  <span class="offer-actions">
                    <button class="ghost mini" onclick={() => respondCrewOffer(campaignId, o.npc_id, true).then(() => loadTab('tripulacao'))}>{t('common.accept')}</button>
                    <button class="ghost mini" onclick={() => respondCrewOffer(campaignId, o.npc_id, false).then(() => loadTab('tripulacao'))}>{t('common.decline')}</button>
                  </span>
                </li>
              {/each}
            </ul>
          {/if}
          <h4 class="comms-sub">{t('tripulacao.members')}</h4>
          {#if !crewData || crewData.members.length === 0}
            <p class="hint">{t('tripulacao.empty')}</p>
          {:else}
            <ul class="commslist crew-list">
              {#each crewData.members as m (m.id)}
                <li class="crew-row">
                  <span class="cname">{m.name || m.id}</span>
                  {#if m.specialty}<span class="rep-badge">{m.specialty}</span>{/if}
                  <span class="dim">{bondLabel(m.bond_tier)}</span>
                  <span class="dim dissat-{m.dissatisfaction_bucket}">{dissatLabel(m.dissatisfaction_bucket)}</span>
                  {#if m.status && m.status !== 'alive'}<span class="dim">· {m.status}</span>{/if}
                </li>
              {/each}
            </ul>
          {/if}

        {:else if hudTab === 'comunicacao'}
          {#if comms?.mushi_call_active}
            <p class="mushi-active">{t('comunicacao.call_active', { x: comms.mushi_call_active.caller_npc_id ?? '…' })}</p>
          {/if}
          <h4 class="comms-sub">{t('comunicacao.paired')}</h4>
          {#if !comms || comms.paired_mushis.length === 0}
            <p class="hint">{t('comunicacao.paired_empty')}</p>
          {:else}
            <ul class="commslist">
              {#each comms.paired_mushis as p (p.npc_id)}
                <li>
                  <span class="mk">{p.mushi_kind === 'visual' ? '▣' : p.mushi_kind === 'standard' ? '◉' : '◌'}</span>
                  <span class="cname">{p.name || p.npc_id}</span>
                  <span class="dim">{p.mushi_kind}{p.mushi_kind === 'visual' ? t('comunicacao.video') : ''}{p.owner_status && p.owner_status !== 'alive' ? ` · ${p.owner_status}` : ''}</span>
                </li>
              {/each}
            </ul>
          {/if}
          <h4 class="comms-sub">{t('comunicacao.vivre')}</h4>
          {#if !comms || comms.vivre_cards.length === 0}
            <p class="hint">{t('comunicacao.vivre_empty')}</p>
          {:else}
            <ul class="commslist vivre">
              {#each comms.vivre_cards as v (v.npc_id)}
                <li class={`vs-${v.visual_state}`}>
                  <span class="vicon" title={v.visual_state}>{vivreIcon[v.visual_state] ?? '◻'}</span>
                  <span class="cname">{v.name || v.npc_id}</span>
                  {#if v.origin_note}<span class="origin">{v.origin_note}</span>{/if}
                  <span class="dim">{v.visual_state}{v.owner_location ? ` · ${v.owner_location}` : ''}</span>
                </li>
              {/each}
            </ul>
          {/if}

          <!-- Exotic comms: Buster Call, counter-surveillance, taps. -->
          {#if comms?.buster_call_active}
            <p class="buster-banner">{t('comunicacao.buster', { x: comms.buster_call_active.target_island || '…' })}{comms.buster_call_active.reason ? ` — ${comms.buster_call_active.reason}` : ''}</p>
          {/if}
          {#if comms?.surveillance_on_player}
            <p class="surveil-warn">{t('comunicacao.surveil')}</p>
          {:else if comms?.white_mushi_active}
            <p class="hint">{t('comunicacao.white_clean')}</p>
          {/if}
          {#if comms?.black_mushi_taps?.length}
            <h4 class="comms-sub">{t('comunicacao.taps')}</h4>
            <ul class="commslist">
              {#each comms.black_mushi_taps as tap (tap.target_npc_id)}
                <li>
                  <span class="mk">⬤</span>
                  <span class="cname">{tap.name || tap.target_npc_id}</span>
                  <span class="dim">{t('comunicacao.tapped')}{tap.owner_status && tap.owner_status !== 'alive' ? ` · ${tap.owner_status}` : ''}</span>
                </li>
              {/each}
            </ul>
          {/if}

        {:else if hudTab === 'diretivas'}
          <p class="hint">{t('diretivas.hint_a')}<code>{t('diretivas.hint_cmd')}</code>{t('diretivas.hint_b')}</p>
          {#if directives.length === 0}
            <p class="hint">{t('diretivas.empty')}</p>
          {:else}
            <ul class="dirlist">
              {#each directives as d (d.id)}
                <li>
                  <span class="dirtext">{d.text}</span>
                  <button class="ghost del" onclick={() => removeDirective(d.id)} title={t('diretivas.forget')}>✕</button>
                </li>
              {/each}
            </ul>
          {/if}

        {:else if hudTab === 'fios'}
          <p class="hint">{t('fios.hint')}</p>
          {#if !creatingThread}
            <div class="edit-actions">
              <button class="ghost sm" onclick={startCreateThread} data-testid="thread-new">{t('fios.new')}</button>
            </div>
          {/if}
          {#if creatingThread || openThreads.length}
            <ul class="cards">
              {#if creatingThread}
                <li data-testid="thread-new-row">
                  <textarea class="editinput" rows="3" bind:value={threadDraft.description} placeholder={t('fios.description_ph')}></textarea>
                  <input class="editinput" bind:value={threadDraft.theme_tag} placeholder={t('fios.theme_ph')} />
                  <input class="editinput" bind:value={threadDraft.where_hint} placeholder={t('fios.where_ph')} />
                  <input class="editinput" bind:value={threadDraft.source_island_name} placeholder={t('fios.island_ph')} />
                  <div class="edit-actions">
                    <button class="send sm" onclick={saveThread}>{t('common.save')}</button>
                    <button class="ghost sm" onclick={() => (creatingThread = false)}>{t('common.cancel')}</button>
                  </div>
                </li>
              {/if}
              {#each openThreads as th (th.hook_id)}
                <li data-testid="thread-row">
                  {#if editingThreadId === th.hook_id}
                    <textarea class="editinput" rows="3" bind:value={threadDraft.description} placeholder={t('fios.description_ph')}></textarea>
                    <input class="editinput" bind:value={threadDraft.theme_tag} placeholder={t('fios.theme_ph')} />
                    <input class="editinput" bind:value={threadDraft.where_hint} placeholder={t('fios.where_ph')} />
                    <input class="editinput" bind:value={threadDraft.source_island_name} placeholder={t('fios.island_ph')} />
                    <div class="edit-actions">
                      <button class="send sm" onclick={saveThread}>{t('common.save')}</button>
                      <button class="ghost sm" onclick={() => (editingThreadId = null)}>{t('common.cancel')}</button>
                    </div>
                  {:else}
                    <span class="cardline">
                      <span class="cname-c">{th.theme_tag || t('fios.fallback')}</span>
                      <span class="kind">
                        {planterLabel(th.planter)}{th.source_island_name ? ` · ${th.source_island_name}` : ''}
                        · {th.age_in_turns > 0 ? t(th.age_in_turns === 1 ? 'fios.age_one' : 'fios.age_many', { n: th.age_in_turns }) : t('fios.age_now')}
                      </span>
                    </span>
                    <span class="fact">{th.description}</span>
                    {#if th.where_hint}<span class="aliases">↪ {th.where_hint}</span>{/if}
                    <div class="row-actions">
                      <button class="ghost sm" onclick={() => startEditThread(th)} title={t('common.edit')} data-testid="thread-edit">✎</button>
                      <button class="ghost sm del" onclick={() => removeThread(th)} title={t('common.delete')}>✕</button>
                    </div>
                  {/if}
                </li>
              {/each}
            </ul>
          {:else}
            <p class="hint">{t('fios.empty')}</p>
          {/if}
          {#if resolvedThreads.length}
            <details class="poster-history">
              <summary>{t('fios.resolved', { n: resolvedThreads.length })}</summary>
              <ul>
                {#each resolvedThreads as th (th.hook_id)}
                  <li data-testid="thread-resolved-row">
                    <span>
                      <strong>{th.theme_tag || t('fios.fallback')}</strong>
                      <span class="dim">{t('fios.resolved_at', { n: th.resolved_at_turn_index })}{th.source_island_name ? ` · ${th.source_island_name}` : ''}</span>
                      <button class="ghost sm del" onclick={() => removeThread(th)} title={t('fios.delete_history')}>✕</button>
                    </span>
                    <span>{th.description}</span>
                  </li>
                {/each}
              </ul>
            </details>
          {/if}

        {:else if hudTab === 'jornal'}
          {#if newsNemesis?.current_nemesis_id || newsNemesis?.history?.length}
            <p class="nemesis-line">
              {t('jornal.nemesis')}{newsNemesis?.rank ? ` · ${newsNemesis.rank}` : ''}
              {#if newsNemesis?.history?.length}<span class="dim">{t('jornal.fallen', { n: newsNemesis.history.length })}</span>{/if}
            </p>
          {/if}
          {#if newsEditions.length === 0}
            <p class="hint">{t('jornal.empty')}</p>
          {:else}
            {#each [...newsEditions].reverse() as ed (ed.id ?? ed.scheduled_day)}
              <article class="news-edition">
                {#each parseNews(ed.markdown) as blk}
                  {#if blk.type === 'h1'}
                    <h1>{#each blk.spans as s}{#if s.b}<strong>{s.t}</strong>{:else if s.i}<em>{s.t}</em>{:else}{s.t}{/if}{/each}</h1>
                  {:else if blk.type === 'h2'}
                    <h2>{#each blk.spans as s}{#if s.b}<strong>{s.t}</strong>{:else if s.i}<em>{s.t}</em>{:else}{s.t}{/if}{/each}</h2>
                  {:else if blk.type === 'h3'}
                    <h3 class="npc-sub">{#each blk.spans as s}{#if s.b}<strong>{s.t}</strong>{:else if s.i}<em>{s.t}</em>{:else}{s.t}{/if}{/each}</h3>
                  {:else if blk.type === 'cap'}
                    <p class="cap">{#each blk.spans as s}{s.t}{/each}</p>
                  {:else if blk.type === 'li'}
                    <p class="li">▪ {#each blk.spans as s}{#if s.b}<strong>{s.t}</strong>{:else if s.i}<em>{s.t}</em>{:else}{s.t}{/if}{/each}</p>
                  {:else}
                    <p>{#each blk.spans as s}{#if s.b}<strong>{s.t}</strong>{:else if s.i}<em>{s.t}</em>{:else}{s.t}{/if}{/each}</p>
                  {/if}
                {/each}
              </article>
            {/each}
          {/if}

        {:else if hudTab === 'final'}
          <p class="hint">{t('final.hint')}</p>
          {#if endingData?.endings_reached?.length}
            <h4 class="comms-sub">{t('final.reached', { n: endingData.endings_reached.length })}</h4>
            <ul class="commslist ending-list">
              {#each endingData.endings_reached as e, i (e.kind + '-' + i)}
                <li class="ending-row">
                  <div class="ending-row-head">
                    <span class="cname">{endingLabel(e.kind)}</span>
                    <span class="rep-badge">{e.valence === 'bad' ? t('final.grim') : t('final.bright')}</span>
                    <button class="send" onclick={() => (epilogue = { kind: e.kind, prose: e.epilogue_summary, valence: e.valence })}>{t('final.reread')}</button>
                  </div>
                  {#if e.reasoning}<span class="dim">{e.reasoning}{e.reached_at_day != null ? t('final.day', { n: e.reached_at_day }) : ''}</span>{/if}
                </li>
              {/each}
            </ul>
          {:else}
            <p class="hint">{t('final.none')}</p>
          {/if}
          <h4 class="comms-sub">{t('final.world')}</h4>
          <ul class="commslist faction-list">
            <li><span class="dim">{t('final.laugh_tale', { x: endingData?.world_flags?.laugh_tale_revealed ? t('final.revealed') : t('final.hidden') })}</span></li>
            <li><span class="dim">{t('final.rio', { x: endingData?.world_flags?.rio_poneglyph_read ? t('final.read') : t('final.unread') })}</span></li>
          </ul>
          {#if poneglyphData?.poneglyphs?.length}
            <h4 class="comms-sub">{t('final.poneglyphs', { n: poneglyphData.poneglyphs.length })}</h4>
            <ul class="commslist faction-list">
              {#each poneglyphData.poneglyphs as p (p.id)}
                <li class="faction-row">
                  <span class="cname">{p.name}</span>
                  <span class="rep-badge">{p.poneglyph_kind ?? '?'}</span>
                  <span class="dim">{p.content_revealed ? t('final.deciphered') : (p.translated ? t('final.translating') : (p.transcribed_by_player ? t('final.transcribed') : t('final.sighted')))}</span>
                </li>
              {/each}
            </ul>
          {/if}
        {/if}
        </div>
      </section>
    </aside>
  {/if}

  {#if newsToast}
    <button class="news-toast" onclick={() => openHud('jornal')} title={t('toast.news_title')}>
      <span class="bell">◈</span>
      <span class="toast-body">
        <strong>{t('toast.news', { n: newsToast.day })}</strong>
        <span>{newsToast.headline}</span>
      </span>
    </button>
  {/if}

  {#if mushiToast}
    <button class="news-toast mushi-toast" onclick={() => openHud('comunicacao')} title={t('toast.mushi_title')}>
      <span class="bell">◉</span>
      <span class="toast-body">
        <strong>{t('toast.mushi')}</strong>
        <span>{mushiToast.motive || t('toast.mushi_fallback')}</span>
      </span>
    </button>
  {/if}

  {#if endingToast}
    <button class="news-toast ending-toast" onclick={() => openHud('final')} title={t('toast.ending_title')}>
      <span class="bell">⚓</span>
      <span class="toast-body">
        <strong>{t('toast.ending')}</strong>
        <span>{endingLabel(endingToast.kind)}</span>
      </span>
    </button>
  {/if}

  {#if crewOffer}
    <div class="news-toast crew-toast" title={t('toast.crew_title')}>
      <span class="bell">⚑</span>
      <span class="toast-body">
        <strong>{t('toast.crew_join', { name: crewOffer.name || t('toast.someone') })}</strong>
        <span class="crew-toast-actions">
          <button class="ghost mini" onclick={() => respondOffer(true)}>{t('common.accept')}</button>
          <button class="ghost mini" onclick={() => respondOffer(false)}>{t('common.decline')}</button>
        </span>
      </span>
    </div>
  {/if}

  {#if epilogue}
    <div class="epilogue-overlay" role="dialog" aria-modal="true">
      <div class="epilogue-card">
        <div class="drawer-head">
          <h3>{t('epilogue.title', { x: endingLabel(epilogue.kind) })}</h3>
          <button class="ghost" onclick={() => (epilogue = null)}>{t('common.close')}</button>
        </div>
        <div class="epilogue-prose">
          {#each paragraphs(epilogue.prose) as p}
            <p class="prose" class:dlg={isDialogue(p)}>
              {#each tokenize(p) as tok}{#if tok.npc}<span class="npc">{tok.npc}</span>{:else}{tok.t}{/if}{/each}
            </p>
          {/each}
        </div>
        <p class="hint epilogue-foot">{t('epilogue.foot')}</p>
      </div>
    </div>
  {/if}

  {#if devtoolsOpen}
    <aside class="drawer wide">
      <div class="drawer-head">
        <h3>{t('devtools.title')}</h3>
        <button class="ghost" onclick={() => (devtoolsOpen = false)}>{t('common.close')}</button>
      </div>
      {#if traces.length === 0}
        <p class="hint">{t('devtools.empty')}</p>
      {:else}
        <div class="trace-pick">
          <select bind:value={selectedTraceKey}>
            {#each [...traces].reverse() as tr (tr.key)}
              <option value={tr.key}>{tr.label}{tr.action ? ` — ${tr.action.slice(0, 36)}` : ''}</option>
            {/each}
          </select>
          <span class="hint">{t('devtools.calls', { n: currentTrace?.entries.length ?? 0 })}</span>
        </div>
        {#if currentTrace}
          {@const tot = tokTotals(currentTrace.entries)}
          <div class="trace-total">
            <span title={t('devtools.turn_total_title')}>turn: <b>{kb(tot.total)} tok</b></span>
            <span class="dim">in {kb(tot.inp)} · out {kb(tot.out)}</span>
            <span class="dim" class:warn={!tot.cacheRead && !tot.cacheWrite}>
              {#if tot.cacheRead || tot.cacheWrite}
                {t('devtools.cache_rw', { r: kb(tot.cacheRead), w: kb(tot.cacheWrite) })}
              {:else}{t('devtools.cache_off')}{/if}
            </span>
          </div>
          <div class="calls">
            {#each currentTrace.entries as e (e.seq)}
              <div class="call">
                <div class="call-head">
                  <span class="seq">#{e.seq}</span>
                  <span class="call-label">{e.label}</span>
                  <span class="badge b-{e.tag}">{e.tag}</span>
                </div>
                <div class="call-meta">
                  <span class="model">{e.model}</span>
                  {#if e.usage}
                    <span title={t('devtools.usage_title')}>
                      in {kb(e.usage.input)} · out {kb(e.usage.output)}{e.usage.cache_read ? t('devtools.cache_read', { n: kb(e.usage.cache_read) }) : ''}{e.usage.cache_creation ? t('devtools.cache_write', { n: kb(e.usage.cache_creation) }) : ''}
                    </span>
                  {/if}
                  <span class="psize" title={t('devtools.sys_title')}>sys {kb(e.instructions_chars)} ch</span>
                </div>
                {#if e.output?.friction_note}
                  <p class="iolabel" style="color:#e6a23c">{t('devtools.friction')}</p>
                  <pre class="iobody" style="border-left:2px solid #e6a23c; color:#e6a23c">{e.output.friction_note}</pre>
                {/if}
                <p class="iolabel out-lbl">{t('devtools.output')}</p>
                <pre class="iobody out">{fmtOutput(e.output)}</pre>
                {#if e.input?.length}
                  <details class="io-in">
                    <summary>{t(e.input.length === 1 ? 'devtools.input_one' : 'devtools.input_many', { n: e.input.length })}</summary>
                    {#each e.input as s}
                      <p class="sectitle">{s.title}{s.truncated ? t('devtools.truncated') : ''}</p>
                      <pre class="iobody">{s.body}</pre>
                    {/each}
                  </details>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      {/if}
    </aside>
  {/if}

  <!-- Map: read-only full-screen overlay. -->
  {#if mapOpen && world}
    <div class="map-overlay" data-testid="map-overlay">
      <Map
        islands={world.islands}
        position={world.position}
        worldTotal={world.world_total}
        vivreCards={comms?.vivre_cards || []}
        onclose={() => (mapOpen = false)}
      />
    </div>
  {/if}
  {#if mapError}
    <p class="err map-err">{mapError}</p>
  {/if}
</div>

<style>
  /* wanted poster (tab Cartaz) */
  .poster {
    border: 1px solid var(--line-strong);
    border-radius: var(--radius);
    background: var(--bg-raised);
    padding: 0.9rem 1rem;
    margin-bottom: 0.75rem;
  }
  .poster-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.4rem;
  }
  .poster-head-right {
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }
  .poster-status-edit {
    max-width: 11rem;
  }
  .poster-wanted {
    font-size: 0.68rem;
    font-weight: 650;
    letter-spacing: 0.35em;
    color: var(--ink-dim);
  }
  .poster-status {
    text-transform: uppercase;
    font-size: 0.62rem;
  }
  .poster-name {
    font-size: 1.05rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--ink);
  }
  .poster-epithet {
    font-style: italic;
    font-size: 0.82rem;
    color: var(--accent-hi);
    margin-top: 0.1rem;
  }
  .poster-bounty {
    font-variant-numeric: tabular-nums;
    font-weight: 650;
    font-size: 0.95rem;
    color: var(--ink);
    margin: 0.45rem 0;
    padding-bottom: 0.45rem;
    border-bottom: 1px solid var(--line);
  }
  .poster-note,
  .poster-image {
    font-size: 0.78rem;
    color: var(--ink-body);
    margin: 0.3rem 0 0;
    line-height: 1.45;
  }
  .poster-label {
    color: var(--ink-dim);
    font-weight: 550;
  }
  .poster-divergence {
    color: var(--warn, #d2a53f);
  }
  .poster-history {
    margin-top: 0.55rem;
    font-size: 0.74rem;
  }
  .poster-history summary {
    cursor: pointer;
    color: var(--ink-dim);
  }
  .poster-history ul {
    list-style: none;
    padding: 0.35rem 0 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .poster-history li {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    border-left: 2px solid var(--line);
    padding-left: 0.55rem;
    color: var(--ink-body);
  }
  .poster-hist-epithet {
    font-style: italic;
    color: var(--accent-hi);
  }

  .game {
    position: fixed;
    inset: 0;
    display: flex;
    flex-direction: column;
    background: var(--bg);
  }
  .column {
    width: min(720px, 100%);
    margin: 0 auto;
  }

  .map-overlay {
    position: fixed;
    inset: 0;
    z-index: 2000;
  }
  .map-err {
    position: fixed;
    bottom: 1rem;
    left: 50%;
    transform: translateX(-50%);
    z-index: 2001;
  }

  /* topbar */
  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    height: 46px;
    padding: 0 0.75rem;
    border-bottom: 1px solid var(--line);
    background: color-mix(in srgb, var(--bg-raised) 85%, transparent);
    backdrop-filter: blur(10px);
    flex: 0 0 auto;
  }
  .title {
    text-align: center;
    line-height: 1.15;
    overflow: hidden;
    min-width: 0;
    flex: 1;
  }
  .cname {
    display: block;
    font-weight: 550;
    font-size: 0.84rem;
    letter-spacing: -0.01em;
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .carc {
    display: block;
    font-size: 0.66rem;
    color: var(--ink-dim);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* On narrow screens the arc subtitle and clock chips yield to the controls. */
  @media (max-width: 640px) {
    .carc {
      display: none;
    }
    .clockbox > span {
      display: none;
    }
  }
  .clockbox {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.72rem;
    font-variant-numeric: tabular-nums;
    color: var(--ink-dim);
    white-space: nowrap;
  }
  .ghost {
    padding: 0.3rem 0.55rem;
    font-size: 0.76rem;
  }
  .hud-menu {
    border: 1px solid var(--line);
    background: var(--bg-elevated);
  }

  /* scene strip */
  .scenestrip {
    width: min(720px, 100%);
    margin: 0 auto;
    padding: 0.7rem 1rem 0;
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.5rem 0.8rem;
  }
  .loc {
    font-weight: 550;
    font-size: 0.8rem;
    letter-spacing: -0.01em;
    color: var(--ink);
  }
  .amb {
    font-size: 0.78rem;
    color: var(--ink-dim);
    flex: 1 1 100%;
    order: 3;
  }
  .present {
    display: flex;
    gap: 0.3rem;
  }
  .chip {
    font-size: 0.66rem;
    font-weight: 500;
    border: 1px solid var(--line);
    border-radius: 99px;
    padding: 0.12rem 0.5rem;
    color: var(--ink-dim);
    background: var(--bg-elevated);
  }
  .chip.crew {
    border-color: color-mix(in srgb, var(--ok) 45%, transparent);
    color: var(--ok);
    background: var(--ok-soft);
  }

  /* narration log */
  .log {
    flex: 1;
    overflow-y: auto;
    padding: 1.4rem 1rem 2rem;
  }
  .action {
    font-size: 0.86rem;
    color: var(--ink-dim);
    border-left: 2px solid var(--line-strong);
    padding-left: 0.8rem;
    margin: 1.4rem 0 1rem;
  }
  .action.meta {
    font-family: var(--mono);
    font-size: 0.78rem;
    border-left-color: var(--accent);
    color: var(--accent-hi);
  }
  .prose {
    font-size: 0.95rem;
    line-height: 1.75;
    letter-spacing: -0.006em;
    color: var(--ink-body);
    margin: 0 0 1rem;
  }
  .prose.dlg {
    margin-left: 0.2rem;
  }
  .npc {
    color: var(--accent-hi);
    font-weight: 550;
  }
  .ooc {
    border: 1px solid var(--line);
    border-left: 2px solid var(--accent);
    background: var(--bg-raised);
    padding: 0.65rem 0.9rem;
    margin: 0 0 1.4rem;
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  }
  .ooc p {
    font-family: var(--mono);
    font-size: 0.8rem;
    line-height: 1.6;
    color: var(--ink-body);
    margin: 0 0 0.6rem;
  }
  .ooc p:last-child {
    margin-bottom: 0;
  }
  .meta-note {
    font-family: var(--mono);
    font-size: 0.74rem;
    color: var(--ok);
    margin: 0 0 1.4rem;
  }
  .turnsep {
    border: none;
    border-top: 1px solid var(--line);
    margin: 1.6rem 0;
  }
  .phase {
    font-size: 0.74rem;
    color: var(--ink-dim);
  }
  .caret {
    display: inline-block;
    width: 0.45rem;
    height: 0.85rem;
    margin-left: 0.25rem;
    background: var(--accent);
    border-radius: 1px;
    vertical-align: text-bottom;
    animation: blink 1s steps(2) infinite;
  }
  @keyframes blink {
    50% {
      opacity: 0;
    }
  }

  /* Inline narration edit in the log. */
  .prose-edit textarea {
    width: 100%;
    box-sizing: border-box;
    font-size: 0.92rem;
    line-height: 1.65;
    resize: vertical;
  }
  .edit-actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.5rem;
  }

  /* Turn commands: icons in the right margin; regenerate opens a box beside it. Collapses inline when narrow. */
  .turn {
    position: relative;
  }
  .turn-tools {
    position: absolute;
    top: 1.4rem; /* align with the turn's first line */
    left: 100%;
    margin-left: 0.9rem;
    display: flex;
    gap: 0.3rem;
  }
  .tool {
    width: 26px;
    height: 26px;
    padding: 0;
    display: grid;
    place-items: center;
    font-size: 0.8rem;
    line-height: 1;
    color: var(--ink-dim);
    background: transparent;
    border: 1px solid var(--line);
    border-radius: 6px;
  }
  .tool:hover:not(:disabled) {
    color: var(--ink);
    border-color: var(--line-strong);
    background: var(--bg-hover);
  }
  .tool.on {
    color: var(--accent-hi);
    border-color: var(--accent);
  }
  .reroll-pop {
    position: absolute;
    top: calc(1.4rem + 26px + 0.5rem);
    left: 100%;
    margin-left: 0.9rem;
    width: 250px;
    display: grid;
    gap: 0.5rem;
    padding: 0.6rem;
    background: var(--bg-raised);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    box-shadow: var(--shadow-2);
  }
  .reroll-pop textarea {
    width: 100%;
    box-sizing: border-box;
    font-size: 0.78rem;
    line-height: 1.5;
    resize: vertical;
  }
  .reroll-pop .send {
    justify-self: end;
  }
  @media (max-width: 1280px) {
    .turn-tools {
      position: static;
      margin: 0 0 0.6rem;
      justify-content: flex-end;
    }
    .reroll-pop {
      position: static;
      width: auto;
      margin: 0 0 1rem;
    }
  }

  /* Runtime error banner above the composer. */
  .turn-error {
    width: min(720px, 100%);
    margin: 0.4rem auto 0;
    padding: 0 1rem;
  }
  .turn-error-inner {
    display: flex;
    gap: 0.65rem;
    align-items: flex-start;
    padding: 0.7rem 0.85rem;
    border: 1px solid color-mix(in srgb, var(--orange) 45%, transparent);
    border-radius: var(--radius-sm);
    background: var(--bg-raised);
    box-shadow: var(--shadow-2);
    animation: toastIn 0.2s ease-out;
  }
  .turn-error.quota .turn-error-inner {
    border-color: color-mix(in srgb, var(--accent) 50%, transparent);
  }
  .turn-error .te-icon {
    flex: 0 0 auto;
    width: 1.35rem;
    height: 1.35rem;
    display: grid;
    place-items: center;
    border-radius: 99px;
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--orange);
    background: color-mix(in srgb, var(--orange) 14%, transparent);
  }
  .turn-error.quota .te-icon {
    color: var(--accent-hi);
    background: var(--accent-soft);
  }
  .turn-error .te-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .turn-error .te-body strong {
    font-size: 0.8rem;
    font-weight: 550;
    letter-spacing: -0.01em;
    color: var(--ink);
  }
  .turn-error .te-body span {
    font-size: 0.74rem;
    color: var(--ink-dim);
    line-height: 1.5;
  }
  .turn-error .te-dismiss {
    font-size: 0.7rem;
    padding: 0 0.3rem;
    flex-shrink: 0;
  }

  /* composer */
  .composer {
    border-top: 1px solid var(--line);
    background: color-mix(in srgb, var(--bg-raised) 85%, transparent);
    backdrop-filter: blur(10px);
    padding: 0.7rem 1rem;
    flex: 0 0 auto;
  }
  .composer-inner {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
  }
  select {
    font-size: 0.76rem;
    color: var(--ink-dim);
    padding: 0.5rem 0.45rem;
  }
  textarea {
    flex: 1;
    min-width: 0;
    resize: none;
    font-size: 0.9rem;
    line-height: 1.45;
    padding: 0.5rem 0.7rem;
  }
  .send {
    padding: 0.5rem 1.1rem;
    font-size: 0.82rem;
  }
  .send.sm {
    padding: 0.22rem 0.7rem;
    font-size: 0.72rem;
  }

  /* drawer / HUD */
  .drawer {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(380px, 90vw);
    background: var(--bg-raised);
    border-left: 1px solid var(--line);
    box-shadow: var(--shadow-3);
    padding: 1rem 1.1rem;
    overflow-y: auto;
    animation: drawerIn 0.18s ease-out;
  }
  @keyframes drawerIn {
    from {
      transform: translateX(12px);
      opacity: 0;
    }
    to {
      transform: translateX(0);
      opacity: 1;
    }
  }
  .drawer-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--line);
    padding-bottom: 0.6rem;
    margin-bottom: 0.8rem;
  }
  .drawer-head h3 {
    margin: 0;
  }

  /* HUD: two panels, grouped nav left and content right; each panel scrolls on its own. */
  .drawer.hud {
    width: min(840px, 96vw);
    padding: 0;
    display: flex;
    overflow: hidden;
  }
  .hud-nav {
    flex: 0 0 172px;
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    padding: 0.85rem 0.6rem 1rem;
    border-right: 1px solid var(--line);
    background: var(--bg);
    overflow-y: auto;
  }
  .hud-group {
    margin: 0.9rem 0.5rem 0.25rem;
    font-size: 0.6rem;
    font-weight: 550;
    text-transform: uppercase;
    letter-spacing: 0.11em;
    color: var(--ink-dim);
    opacity: 0.8;
  }
  .hud-nav .hud-group:first-child {
    margin-top: 0;
  }
  .hud-tab {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    width: 100%;
    text-align: left;
    font-size: 0.78rem;
    font-weight: 500;
    letter-spacing: -0.008em;
    border: none;
    border-radius: var(--radius-sm);
    padding: 0.32rem 0.55rem;
    color: var(--ink-dim);
    background: transparent;
  }
  .hud-tab:hover:not(:disabled) {
    background: var(--bg-hover);
    color: var(--ink);
  }
  .hud-tab.active {
    background: var(--bg-elevated);
    color: var(--ink);
  }
  .hud-tab .hud-tab-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .hud-count {
    flex: 0 0 auto;
    font-size: 0.62rem;
    font-weight: 550;
    font-variant-numeric: tabular-nums;
    line-height: 1;
    padding: 0.16rem 0.4rem;
    border-radius: 99px;
    color: var(--accent-hi);
    background: var(--accent-soft);
  }
  .hud-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .hud-head {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.8rem 1.25rem;
    border-bottom: 1px solid var(--line);
  }
  .hud-head h3 {
    margin: 0;
    font-size: 0.88rem;
    font-weight: 590;
    text-transform: none;
    letter-spacing: -0.012em;
    color: var(--ink);
  }
  .hud-close {
    font-size: 0.8rem;
    padding: 0.2rem 0.45rem;
  }
  .hud-body {
    flex: 1;
    overflow-y: auto;
    padding: 1rem 1.25rem 1.4rem;
  }
  /* Narrow window: nav becomes a scrollable top row. */
  @media (max-width: 720px) {
    .drawer.hud {
      flex-direction: column;
    }
    .hud-nav {
      flex: 0 0 auto;
      flex-direction: row;
      align-items: center;
      gap: 0.15rem;
      padding: 0.5rem 0.6rem;
      border-right: none;
      border-bottom: 1px solid var(--line);
      overflow-x: auto;
      overflow-y: hidden;
    }
    .hud-group {
      display: none;
    }
    .hud-tab {
      flex: 0 0 auto;
      width: auto;
    }
  }

  /* Story-defined key/value pairs. */
  .props {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .props li {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.5rem 0.1rem;
    border-bottom: 1px solid var(--line);
    font-size: 0.82rem;
  }
  .props li:last-child {
    border-bottom: none;
  }
  .props .pk {
    flex: 0 0 auto;
    color: var(--ink-dim);
  }
  .props .pv {
    min-width: 0;
    text-align: right;
    color: var(--ink);
    overflow-wrap: anywhere;
  }

  /* Inline edit forms. */
  .editform {
    display: grid;
    gap: 0.6rem;
    margin-bottom: 1rem;
  }
  .editform.inline {
    grid-template-columns: 1fr auto;
    align-items: end;
    gap: 0.6rem;
    margin-bottom: 0.4rem;
  }
  .editform.two-col {
    grid-template-columns: 1fr 1fr;
    column-gap: 0.8rem;
  }
  .editform .span2 {
    grid-column: 1 / -1;
  }
  .editform .form-foot {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    margin-top: 0.2rem;
  }
  .editform label {
    display: grid;
    gap: 0.3rem;
    font-size: 0.74rem;
    font-weight: 500;
    letter-spacing: -0.005em;
    color: var(--ink-dim);
  }
  /* Buttons hug their label instead of stretching the column. */
  .editform > button {
    justify-self: start;
  }
  .editform input,
  .editform select,
  .editform textarea,
  .editinput {
    width: 100%;
    box-sizing: border-box;
    font-size: 0.84rem;
    padding: 0.42rem 0.55rem;
  }
  .editinput {
    margin-bottom: 0.4rem;
    text-transform: none;
    letter-spacing: -0.008em;
  }
  .edit-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.4rem;
    margin-bottom: 0.4rem;
  }
  .edit-grid .editinput {
    margin-bottom: 0;
  }
  .editform .dim {
    text-transform: none;
    letter-spacing: -0.008em;
    font-weight: 400;
    font-size: 0.72rem;
    color: var(--ink-dim);
  }
  .savemsg {
    font-size: 0.72rem;
    color: var(--ok);
  }
  .row-actions {
    display: flex;
    gap: 0.25rem;
    margin-top: 0.2rem;
  }
  .row-actions .sm,
  .edit-actions .sm {
    font-size: 0.68rem;
    padding: 0.12rem 0.45rem;
  }

  .search {
    width: 100%;
    box-sizing: border-box;
    font-size: 0.82rem;
    padding: 0.45rem 0.65rem;
    margin-bottom: 0.8rem;
  }
  .tabs {
    display: flex;
    gap: 0.3rem;
    margin-bottom: 0.9rem;
  }
  .tab {
    font-size: 0.7rem;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    padding: 0.2rem 0.6rem;
    color: var(--ink-dim);
    background: transparent;
  }
  .tab.active {
    border-color: color-mix(in srgb, var(--accent) 50%, transparent);
    color: var(--accent-hi);
    background: var(--accent-soft);
  }
  .grouplbl {
    font-size: 0.62rem;
    font-weight: 550;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--ink-dim);
    margin: 0.6rem 0 0.5rem;
  }
  .cards {
    list-style: none;
    margin: 0 0 0.4rem;
    padding: 0;
    display: grid;
    gap: 0.5rem;
  }
  .cards li {
    display: grid;
    gap: 0.2rem;
    background: var(--bg-elevated);
    border: 1px solid var(--line);
    border-radius: var(--radius-sm);
    padding: 0.55rem 0.7rem;
    transition: border-color 0.12s ease;
  }
  .cards li:hover {
    border-color: var(--line-strong);
  }
  .cardline {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .cname-c {
    font-weight: 550;
    font-size: 0.84rem;
    letter-spacing: -0.01em;
    color: var(--ink);
  }
  .kind {
    font-family: var(--mono);
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ink-dim);
    white-space: nowrap;
  }
  .aliases {
    font-size: 0.7rem;
    color: var(--ink-dim);
  }
  .crystals {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.5rem;
  }
  .crystals li {
    display: grid;
    gap: 0.2rem;
    background: var(--bg-elevated);
    border: 1px solid var(--line);
    border-radius: var(--radius-sm);
    padding: 0.55rem 0.7rem;
  }
  .cat {
    font-family: var(--mono);
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--accent-hi);
  }
  .fact {
    font-size: 0.82rem;
    line-height: 1.55;
    color: var(--ink-body);
  }
  .dirlist {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.5rem;
  }
  .dirlist li {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.5rem;
    background: var(--bg-elevated);
    border: 1px solid var(--line);
    border-left: 2px solid var(--accent);
    border-radius: var(--radius-sm);
    padding: 0.45rem 0.5rem 0.45rem 0.7rem;
  }
  .dirtext {
    font-size: 0.84rem;
    line-height: 1.5;
    color: var(--ink-body);
  }
  .del {
    color: var(--down);
  }
  .ghost.del:hover:not(:disabled) {
    color: var(--down);
    background: var(--down-soft);
  }
  .err {
    color: var(--down);
  }
  .hint code {
    color: var(--accent-hi);
  }

  /* Devtools */
  .ghost.on {
    color: var(--accent-hi);
    background: var(--accent-soft);
  }
  .drawer.wide {
    width: min(680px, 96vw);
  }
  .trace-pick {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-bottom: 0.9rem;
  }
  .trace-pick select {
    flex: 1;
    font-family: var(--mono);
    font-size: 0.74rem;
    color: var(--ink);
    padding: 0.4rem 0.5rem;
  }
  .trace-total {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 0.9rem;
    align-items: baseline;
    font-family: var(--mono);
    font-size: 0.7rem;
    color: var(--ink-body);
    background: var(--bg-elevated);
    border: 1px solid var(--line);
    border-radius: var(--radius-sm);
    padding: 0.45rem 0.6rem;
    margin-bottom: 0.9rem;
  }
  .trace-total b {
    color: var(--accent-hi);
  }
  .trace-total .dim {
    color: var(--ink-dim);
  }
  .trace-total .warn {
    color: var(--down);
  }
  .calls {
    display: grid;
    gap: 0.7rem;
  }
  .call {
    border: 1px solid var(--line);
    border-radius: var(--radius-sm);
    padding: 0.6rem 0.7rem;
    background: var(--bg-elevated);
  }
  .call-head {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
  }
  .seq {
    font-family: var(--mono);
    font-size: 0.66rem;
    color: var(--ink-dim);
  }
  .call-label {
    font-weight: 550;
    font-size: 0.84rem;
    letter-spacing: -0.01em;
    color: var(--ink);
    flex: 1;
  }
  .badge {
    font-family: var(--mono);
    font-size: 0.58rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    border: 1px solid var(--line);
    border-radius: 99px;
    padding: 0.1rem 0.45rem;
    color: var(--ink-dim);
    white-space: nowrap;
  }
  .b-director {
    border-color: color-mix(in srgb, var(--accent) 55%, transparent);
    color: var(--accent-hi);
  }
  .b-narrator {
    border-color: color-mix(in srgb, var(--warn) 55%, transparent);
    color: var(--warn);
  }
  .b-agent {
    border-color: color-mix(in srgb, var(--ok) 55%, transparent);
    color: var(--ok);
  }
  .b-auditor {
    border-color: color-mix(in srgb, var(--accent-hi) 55%, transparent);
    color: var(--accent-hi);
  }
  .audit-seal {
    font-family: var(--mono);
    font-size: 0.62rem;
    letter-spacing: 0.04em;
    color: var(--ok);
    opacity: 0.75;
    margin: 0 0 0.4rem;
    cursor: help;
  }
  .call-meta {
    display: flex;
    gap: 0.7rem;
    margin: 0.25rem 0 0.5rem;
    font-family: var(--mono);
    font-size: 0.64rem;
    color: var(--ink-dim);
  }
  .iolabel {
    font-family: var(--mono);
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--ink-dim);
    margin: 0 0 0.3rem;
  }
  .out-lbl {
    color: var(--accent-hi);
  }
  .iobody {
    font-family: var(--mono);
    font-size: 0.72rem;
    line-height: 1.5;
    color: var(--ink-body);
    background: var(--bg);
    border: 1px solid var(--line);
    border-radius: var(--radius-sm);
    padding: 0.5rem 0.6rem;
    margin: 0 0 0.4rem;
    max-height: 360px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .iobody.out {
    border-color: color-mix(in srgb, var(--accent) 35%, transparent);
  }
  .io-in {
    margin-top: 0.3rem;
  }
  .io-in summary {
    font-family: var(--mono);
    font-size: 0.66rem;
    color: var(--ink-dim);
    cursor: pointer;
    padding: 0.2rem 0;
  }
  .io-in summary:hover {
    color: var(--ink);
  }
  .sectitle {
    font-family: var(--mono);
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--ink-dim);
    margin: 0.5rem 0 0.25rem;
  }

  /* News Coo */
  .ghost.alert {
    color: var(--accent-hi);
    background: var(--accent-soft);
    animation: newsPulse 1.6s ease-in-out infinite;
  }
  @keyframes newsPulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.55; }
  }
  .nemesis-line {
    font-size: 0.76rem;
    color: var(--down);
    background: var(--bg-elevated);
    border: 1px solid var(--line);
    border-radius: var(--radius-sm);
    padding: 0.45rem 0.6rem;
    margin: 0 0 0.9rem;
  }
  .nemesis-line .dim {
    color: var(--ink-dim);
  }
  .news-edition {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 0.85rem 1rem 1rem;
    margin-bottom: 1.1rem;
    background: var(--bg-elevated);
  }
  .news-edition h1 {
    font-size: 1.05rem;
    font-weight: 590;
    letter-spacing: -0.018em;
    line-height: 1.35;
    color: var(--ink);
    margin: 0 0 0.3rem;
  }
  .news-edition h2 {
    font-family: var(--mono);
    font-size: 0.64rem;
    font-weight: 550;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--ink-dim);
    border-bottom: 1px solid var(--line);
    padding-bottom: 0.3rem;
    margin: 1rem 0 0.5rem;
  }
  .news-edition h3.npc-sub {
    font-size: 0.88rem;
    font-weight: 550;
    text-transform: none;
    letter-spacing: -0.01em;
    color: var(--ink);
    margin: 0.7rem 0 0.2rem;
  }
  .news-edition p {
    font-size: 0.84rem;
    line-height: 1.6;
    color: var(--ink-body);
    margin: 0 0 0.5rem;
  }
  .news-edition p.cap {
    font-style: italic;
    color: var(--ink-dim);
    font-size: 0.76rem;
    margin: 0 0 0.7rem;
  }
  .news-edition p.li {
    margin: 0 0 0.3rem;
    padding-left: 0.2rem;
  }
  .news-edition strong {
    color: var(--ink);
    font-weight: 590;
  }

  /* toasts (bottom-right) */
  .news-toast {
    position: absolute;
    right: 1.2rem;
    bottom: 6.2rem;
    display: flex;
    align-items: center;
    gap: 0.65rem;
    max-width: min(360px, 80vw);
    text-align: left;
    background: var(--bg-raised);
    border: 1px solid var(--line-strong);
    border-radius: var(--radius);
    box-shadow: var(--shadow-3);
    padding: 0.6rem 0.85rem;
    cursor: pointer;
    animation: toastIn 0.22s cubic-bezier(0.2, 0.7, 0.3, 1);
  }
  @keyframes toastIn {
    from { transform: translateY(8px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
  }
  .news-toast .bell {
    font-size: 0.95rem;
    color: var(--accent-hi);
  }
  .news-toast .toast-body {
    display: flex;
    flex-direction: column;
    gap: 0.12rem;
    overflow: hidden;
  }
  .news-toast .toast-body strong {
    font-size: 0.68rem;
    font-weight: 550;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--accent-hi);
  }
  .news-toast .toast-body span {
    font-size: 0.8rem;
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .mushi-toast {
    bottom: 10.4rem;
  }
  .mushi-toast .bell,
  .mushi-toast .toast-body strong {
    color: var(--ok);
  }

  .ending-toast {
    bottom: 14.6rem;
  }
  .ending-toast .bell,
  .ending-toast .toast-body strong {
    color: var(--warn);
  }

  .ending-list .ending-row {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--line);
  }
  .ending-row-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
  }

  /* epilogue (modal) */
  .epilogue-overlay {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-overlay);
    backdrop-filter: blur(6px);
    padding: 1.5rem;
    animation: toastIn 0.25s ease-out;
  }
  .epilogue-card {
    display: flex;
    flex-direction: column;
    width: min(760px, 96vw);
    max-height: 90vh;
    background: var(--bg-raised);
    border: 1px solid var(--line-strong);
    border-radius: 12px;
    box-shadow: var(--shadow-3);
    padding: 1rem 1.4rem 1.2rem;
  }
  .epilogue-prose {
    overflow-y: auto;
    padding-right: 0.4rem;
  }
  .epilogue-foot {
    margin-top: 0.8rem;
    border-top: 1px solid var(--line);
    padding-top: 0.6rem;
  }

  /* HUD surfaces */
  .comms-sub {
    margin: 1.6rem 0 0.7rem;
    font-size: 0.64rem;
    font-weight: 550;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--ink-dim);
  }
  /* First section of a tab hugs the panel top. */
  .hud-body > .comms-sub:first-child {
    margin-top: 0.2rem;
  }
  .mushi-active {
    margin: 0 0 0.4rem;
    font-size: 0.8rem;
    color: var(--ok);
  }
  .buster-banner {
    margin: 0.5rem 0 0.4rem;
    padding: 0.45rem 0.6rem;
    font-size: 0.8rem;
    font-weight: 590;
    color: var(--down);
    background: var(--down-soft);
    border: 1px solid color-mix(in srgb, var(--down) 55%, transparent);
    border-radius: var(--radius-sm);
    letter-spacing: 0.01em;
  }
  .surveil-warn {
    margin: 0.5rem 0 0.4rem;
    font-size: 0.8rem;
    color: var(--warn);
  }
  /* HUD lists: flat rows with hairline dividers. */
  .commslist {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }
  .commslist li {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    flex-wrap: wrap;
    padding: 0.5rem 0.1rem;
    border-bottom: 1px solid var(--line);
  }
  .commslist li:last-child {
    border-bottom: none;
  }
  .commslist .cname {
    font-weight: 550;
    font-size: 0.84rem;
    letter-spacing: -0.01em;
    color: var(--ink);
  }
  .commslist .mk {
    color: var(--ok);
  }
  .commslist .dim {
    font-size: 0.72rem;
    color: var(--ink-dim);
  }
  .commslist .origin {
    flex-basis: 100%;
    font-size: 0.78rem;
    color: var(--ink-dim);
  }
  .commslist.vivre li { border-left: 2px solid transparent; padding-left: 0.55rem; }
  .commslist.vivre li.vs-burning { border-left-color: var(--orange); }
  .commslist.vivre li.vs-errant { border-left-color: var(--warn); }
  .commslist.vivre li.vs-ashes { border-left-color: var(--line-strong); opacity: 0.55; }
  .commslist.vivre .vicon { font-size: 0.92rem; }

  .commslist.invlist .qty {
    font-family: var(--mono);
    font-size: 0.72rem;
    color: var(--accent-hi);
  }

  .ship {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    padding: 0.55rem 0.7rem;
    background: var(--bg-elevated);
    border: 1px solid var(--line);
    border-left: 3px solid var(--line-strong);
    border-radius: var(--radius-sm);
  }
  .ship-line { display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap; }
  .ship-line .cname {
    font-weight: 550;
    color: var(--ink);
  }
  .hull-bucket { font-weight: 590; font-size: 0.82rem; color: var(--ink); }
  .ship .dim { font-size: 0.74rem; color: var(--ink-dim); }
  .ship .origin { font-size: 0.78rem; color: var(--ink-dim); margin: 0.2rem 0 0; }
  .hull-pristine { border-left-color: var(--ok); }
  .hull-scarred { border-left-color: var(--warn); }
  .hull-damaged { border-left-color: var(--orange); }
  .hull-broken { border-left-color: var(--down); }
  .jolly-input {
    width: 100%;
    margin-top: 0.5rem;
    resize: vertical;
    box-sizing: border-box;
    font-size: 0.84rem;
  }
  .jolly-save { margin-top: 0.5rem; }

  .faction-list .faction-row { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
  .rep-badge {
    font-size: 0.68rem;
    font-weight: 550;
    padding: 0.08rem 0.45rem;
    border-radius: 99px;
    border: 1px solid var(--line-strong);
    color: var(--ink-dim);
  }
  .rep-ally { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 55%, transparent); background: var(--ok-soft); }
  .rep-hostile { color: var(--down); border-color: color-mix(in srgb, var(--down) 55%, transparent); background: var(--down-soft); }
  .rep-neutral { color: var(--ink-dim); border-color: var(--line-strong); }

  .alliance-origin { flex-basis: 100%; font-style: italic; opacity: 0.85; }

  /* Crew */
  .crew-align {
    font-size: 0.8rem;
    color: var(--ink-body);
    margin: 0.1rem 0 0.5rem;
  }
  .crew-align strong {
    color: var(--ink);
    font-weight: 550;
  }
  .crew-row, .offer-row { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
  .offer-row .offer-actions, .crew-toast-actions { display: flex; gap: 0.3rem; margin-left: auto; }
  button.mini { font-size: 0.7rem; padding: 0.12rem 0.5rem; border: 1px solid var(--line); }
  .crew-toast .toast-body { display: flex; flex-direction: column; gap: 0.3rem; }
  .crew-toast .bell { color: var(--ink-dim); }
  .dissat-uneasy { color: var(--warn); }
  .dissat-frustrated { color: var(--orange); }
  .dissat-at_breaking_point { color: var(--down); font-weight: 590; }
</style>
