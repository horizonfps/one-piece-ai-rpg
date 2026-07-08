<script module>
  // Preview placeholder; coords are [y, x] in tile-set space (0..50000).
  // Island state is read from current_state.summary_text + flags[], never typed enums.
  export const EXEMPLO_ISLANDS = [
    {
      id: 'foosha', name: 'Foosha Village', jp_name: 'フーシャ村',
      cluster: 'East Blue', region: 'Dawn Island', coords: [37500, 64398],
      canonical: 'canon',
      fog: { discovered: true, visited: true, discovered_via: 'visited' },
      current_state: { summary_text: 'Pacata; vila independente na borda do Reino de Goa.', flags: ['rural', 'moinhos'] },
      description:
        'Vila portuária na borda do Reino de Goa, conhecida pelos moinhos de vento e pastagens. 17 moinhos pintam o horizonte; pescadores e agricultores dividem a população.',
      related: [
        { kind: 'NPC', name: 'Makino' },
        { kind: 'NPC', name: 'Woop Slap' },
        { kind: 'LOCATION', name: 'Monte Colubo' },
      ],
    },
    {
      id: 'goa', name: 'Goa Kingdom', jp_name: 'ゴア王国',
      cluster: 'East Blue', region: 'Dawn Island', coords: [37860, 64620],
      canonical: 'canon',
      fog: { discovered: true, visited: true, discovered_via: 'visited' },
      current_state: { summary_text: 'Monarquia aliada ao Governo Mundial; tensão de castas latente.', flags: ['sistema de castas', 'Gray Terminal', 'alta muralha'] },
      description:
        'Monarquia em Dawn Island com hierarquia social extrema: nobres em High Town murada, comuns em Central/Edge Town, e o Gray Terminal onde vivem os descartados pelo reino.',
      related: [
        { kind: 'LOCATION', name: 'High Town' },
        { kind: 'LOCATION', name: 'Gray Terminal' },
      ],
    },
    {
      id: 'branch153', name: '153rd Marine Branch', jp_name: '海軍第153支部',
      cluster: 'East Blue', region: 'Yotsuba Island', coords: [38188, 60976],
      canonical: 'canon',
      fog: { discovered: true, visited: true, discovered_via: 'visited' },
      current_state: { summary_text: 'Base da Marinha em Shells Town; comando atual reto.', flags: ['base da Marinha', 'Shells Town'] },
      description:
        'Base da Marinha em Shells Town. Por anos sob o tirânico Capitão Morgan, até sua deposição. Hoje serve à população com retidão.',
      related: [{ kind: 'FACTION', name: 'Marinha' }],
    },
    {
      id: 'orange', name: 'Orange Town', jp_name: 'オレンジの町',
      cluster: 'East Blue', region: 'Organ Archipelago', coords: [34024, 57296],
      canonical: 'canon',
      fog: { discovered: true, visited: true, discovered_via: 'visited' },
      current_state: { summary_text: 'Cidade costeira; histórico de assédio pirata.', flags: ['cidade costeira', 'arquitetura germânica'] },
      description:
        'Pequena cidade no Organ Archipelago, fundada por refugiados de uma vila destruída por piratas. Resistiu a múltiplos ataques ao longo das décadas.',
      related: [{ kind: 'NPC', name: 'Prefeito Boodle' }],
    },
    {
      id: 'syrup', name: 'Syrup Village', jp_name: 'シロップ村',
      cluster: 'East Blue', region: 'Gecko Archipelago', coords: [32736, 53120],
      canonical: 'canon',
      fog: { discovered: true, visited: false, discovered_via: 'npc-mention' },
      current_state: { summary_text: 'Vila quieta sobre falésias; afiliada ao Governo Mundial.', flags: ['falésias', 'mansão Kaya'] },
      description:
        'Vila quieta no Gecko Archipelago, construída sobre falésias íngremes. Famosa pela mansão de Kaya. Terra natal de Yasopp e Usopp.',
      related: [{ kind: 'LOCATION', name: 'Mansão Kaya' }],
    },
    {
      id: 'arlong', name: 'Arlong Park', jp_name: 'アーロンパーク',
      cluster: 'East Blue', region: 'Conomi Archipelago', coords: [37574, 48804],
      canonical: 'canon',
      fog: { discovered: true, visited: true, discovered_via: 'visited' },
      current_state: { summary_text: 'Base do Arlong Crew destruída; estrutura em ruínas.', flags: ['estrutura destruída', 'arco de 8 anos'] },
      description:
        'Base do Arlong Crew, dissidência dos Sun Pirates. A torre era um pagode de cinco andares; foi destruída na derrota de Arlong.',
      related: [{ kind: 'FACTION', name: 'Sun Pirates' }],
    },
    {
      id: 'cocoyasi', name: 'Cocoyasi Village', jp_name: 'ココヤシ村',
      cluster: 'East Blue', region: 'Conomi Archipelago', coords: [37720, 48978],
      canonical: 'canon',
      fog: { discovered: true, visited: true, discovered_via: 'visited' },
      current_state: { summary_text: 'Vila portuária libertada; bosque de tangerinas.', flags: ['vila de coco', 'tangerinas'] },
      description:
        'Pequena vila portuária no Conomi Archipelago. Oprimida por Arlong por anos até ser libertada. Cercada por um bosque de tangerinas.',
      related: [{ kind: 'NPC', name: 'Genzou' }],
    },
    {
      id: 'gosa', name: 'Gosa Town', jp_name: 'ゴサの町',
      cluster: 'East Blue', region: 'Conomi Archipelago', coords: [37720, 49234],
      canonical: 'canon',
      fog: { discovered: true, visited: true, discovered_via: 'visited' },
      current_state: { summary_text: 'Cidade portuária reconstruída após destruição.', flags: ['reconstruída', 'cidade portuária'] },
      description:
        'Cidade portuária a leste de Cocoyasi, destruída quando os cidadãos não pagaram tributo a Arlong e reconstruída após sua queda.',
      related: [{ kind: 'NPC', name: 'Chabo' }],
    },
    {
      id: 'branch16', name: '16th Marine Branch', jp_name: '海軍第16支部',
      cluster: 'East Blue', region: 'East Blue', coords: [38698, 47804],
      canonical: 'canon',
      fog: { discovered: true, visited: false, discovered_via: 'news-coo' },
      current_state: { summary_text: 'Base da Marinha sob comando corrupto.', flags: ['base da Marinha', 'comando corrupto'] },
      description:
        'Base da Marinha próxima ao Conomi Archipelago. Comandada pelo corrupto Capitão Nezumi, que tematizou a base com aparência de rato.',
      related: [{ kind: 'FACTION', name: 'Marinha' }],
    },
    {
      id: 'brick-bay', name: 'Brick Bay', jp_name: '',
      cluster: 'East Blue', region: 'East Blue (sul de Conomi)', coords: [36400, 51900],
      canonical: 'generated',
      fog: { discovered: true, visited: true, discovered_via: 'visited' },
      current_state: { summary_text: 'Enseada gerada in-game; ocupação mercenária em curso.', flags: ['gerada', 'crise', 'ocupação mercenária'] },
      description:
        'Pequena enseada ao sul de Conomi, gerada in-game na campanha. Um grupo de ex-Marines cobra tributo dos pescadores. Não consta em mapas oficiais — coords aproximadas por cartas de pescadores.',
      related: [{ kind: 'NPC', name: 'Hench (líder)' }],
    },
  ]
  export const EXEMPLO_POSITION = { kind: 'island', island_id: 'foosha' }
</script>

<script>
  // Read-only Leaflet map with custom CRS. Shows player position, fog of war,
  // and canon info for known islands. Visualization only, no action controls.
  import { onMount, untrack } from 'svelte'
  import L from 'leaflet'
  import 'leaflet/dist/leaflet.css'
  import { t } from './i18n.svelte.js'

  // Pre-bundled tiles served by Vite in dev and FastAPI in prod; no runtime internet.
  const TILE_URL = '/tiles/Blueworld/{z}/{x}/{y}.png'

  // Props; defaults are sample data for preview only.
  let {
    islands = EXEMPLO_ISLANDS,
    position = EXEMPLO_POSITION,
    worldTotal = null, // catalogued world total; null falls back to islands.length
    vivreCards = [], // player vivre cards with live `direction` bearing
    onclose = null,
  } = $props()

  let mapEl = $state(null)
  let ready = $state(false)
  let selectedId = $state(null)
  let showVoyage = $state(false) // voyage-rules popover, sea only
  let focusedCardId = $state(null) // vivre card whose direction ray is lit

  // Leaflet instances; not reactive, live outside the runes cycle.
  let map = null
  let markersById = {}
  let playerMarker = null
  let playerAt = null // current pin [y,x]; voyage animation target
  let playerAnim = null // requestAnimationFrame handle for the pin slide
  let fitted = false
  let vivreRay = null // directional needle of the focused vivre card

  // On-screen needle length (px), fixed at any zoom. A bearing pointer from the pin,
  // not a navigation route; never routes around land or reaches the owner's island.
  const VIVRE_NEEDLE_PX = 56

  const currentIslandId = $derived(position?.kind === 'island' ? position.island_id : null)

  // Discovery fog: current | visited | seen | hidden
  function fogStateOf(island) {
    const fog = island?.fog || {}
    if (currentIslandId && island.id === currentIslandId) return 'current'
    if (fog.visited) return 'visited'
    if (!fog.discovered) return 'hidden'
    return 'seen'
  }
  // Canonicity is orthogonal to fog; an island can be visited and in-game generated.
  function isGenerated(island) {
    return (island?.canonical || island?.current_state?.canonical) === 'generated'
  }

  const fogLabel = (s) => t(`fog.${s}`)

  // Non-navigable containers (a sea/marker/umbrella) never draw as a dockable marker; their coords
  // stay resolvable in `islands` for the player pin. Older payloads without the flag stay visible.
  const isDockable = (i) => i?.navigable !== false
  const knownIslands = $derived(
    (islands || []).filter((i) => (i?.fog?.discovered || i?.fog?.visited) && isDockable(i))
  )
  const mappedCount = $derived(knownIslands.length)
  const totalCount = $derived(Number.isFinite(worldTotal) ? worldTotal : (islands || []).length)
  const selected = $derived((islands || []).find((i) => i.id === selectedId) || null)
  const legendStates = $derived([
    ...['current', 'visited', 'seen'].filter((s) => knownIslands.some((i) => fogStateOf(i) === s)),
    ...(knownIslands.some(isGenerated) ? ['gen'] : []),
  ])

  // Active voyage: route + progress for the info button.
  const atSea = $derived(position?.kind === 'sea')
  const voyage = $derived.by(() => {
    if (position?.kind !== 'sea') return null
    const nameOf = (id) => (islands || []).find((i) => i.id === id)?.name || id
    const adrift = !position.dest_id
    const total = Number.isFinite(position.travel_days_total) ? position.travel_days_total : null
    const elapsed = Number.isFinite(position.days_elapsed) ? position.days_elapsed : 0
    return {
      adrift,
      origin: nameOf(position.origin_id),
      dest: adrift ? t('map.open_sea') : nameOf(position.dest_id),
      total,
      elapsed,
      remaining: adrift || total == null ? null : Math.max(0, total - elapsed),
      pct: !adrift && total ? Math.round((Math.max(0, Math.min(total, elapsed)) / total) * 100) : 0,
    }
  })

  // Vivre cards with a drawable direction (null direction is excluded).
  const activeVivre = $derived((vivreCards || []).filter((c) => c?.direction))

  // Needle endpoint: project the pin to a screen point, step VIVRE_NEEDLE_PX along the
  // bearing (screen: East=+x, North=-y), map back to latlng. Requires a mounted `map`.
  function needleEnd(fromYX, bearingDeg) {
    const r = (bearingDeg * Math.PI) / 180
    const p0 = map.latLngToContainerPoint(fromYX)
    const p1 = L.point(p0.x + Math.sin(r) * VIVRE_NEEDLE_PX, p0.y - Math.cos(r) * VIVRE_NEEDLE_PX)
    return map.containerPointToLatLng(p1)
  }

  function clearVivreRay() {
    if (vivreRay) { vivreRay.remove(); vivreRay = null }
  }

  // Toggle focus; the $effect below owns ray drawing so its origin tracks the pin.
  function focusVivre(card) {
    const id = card?.npc_id
    focusedCardId = focusedCardId === id ? null : id
  }

  // Draw the focused card's directional ray from the player pin without moving the
  // camera. Clears focus if the card left the inventory; same_island has no bearing.
  function syncVivreRay() {
    clearVivreRay()
    const card = activeVivre.find((c) => c.npc_id === focusedCardId)
    if (!card) {
      if (focusedCardId != null) focusedCardId = null
      return
    }
    const dir = card.direction || {}
    const from = playerLatLng()
    if (!map || !from || dir.same_island || !Number.isFinite(dir.bearing_deg)) return
    vivreRay = L.polyline([from, needleEnd(from, dir.bearing_deg)], {
      className: `vivre-ray${dir.stable ? '' : ' unstable'}`,
      color: '#fde68a', weight: 3, opacity: 0.95, interactive: false,
    }).addTo(map)
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])
  }

  function select(id) {
    selectedId = selectedId === id ? null : id
  }

  // Player position in tile-set space [y, x]; lerped while at sea.
  function playerLatLng() {
    if (!position) return null
    if (position.kind === 'island') {
      return (islands || []).find((i) => i.id === position.island_id)?.coords || null
    }
    if (position.kind === 'sea') {
      const o = (islands || []).find((i) => i.id === position.origin_id)?.coords
      const d = (islands || []).find((i) => i.id === position.dest_id)?.coords
      if (!o) return null
      if (!d) return o // adrift: no destination, hold at origin
      const t = Math.max(0, Math.min(1, position.lerp_t ?? 0))
      return [o[0] + (d[0] - o[0]) * t, o[1] + (d[1] - o[1]) * t]
    }
    return null
  }

  function fitToKnown(list) {
    if (!map) return
    if (!list.length) { map.setView([37500, 55000], 2); return }
    if (list.length === 1) { map.setView(list[0].coords, 4); return }
    const ys = list.map((i) => i.coords[0]).filter(Number.isFinite)
    const xs = list.map((i) => i.coords[1]).filter(Number.isFinite)
    map.fitBounds([[Math.min(...ys), Math.min(...xs)], [Math.max(...ys), Math.max(...xs)]], { padding: [70, 70] })
  }

  function applySelection() {
    for (const [id, mk] of Object.entries(markersById)) {
      mk.getElement()?.classList.toggle('selected', id === selectedId)
    }
  }

  function drawAll() {
    if (!map) return
    // Clear island markers only; the player pin is managed separately.
    for (const mk of Object.values(markersById)) mk.remove()
    markersById = {}

    // Read selection without a reactive dependency, so selectedId alone never redraws.
    const sel = untrack(() => selectedId)
    const known = (islands || []).filter(
      (i) => i?.coords && (i?.fog?.discovered || i?.fog?.visited) && isDockable(i)
    )
    for (const island of known) {
      const st = fogStateOf(island)
      const jp = island.jp_name ? `<span class="label-jp">${esc(island.jp_name)}</span>` : ''
      const icon = L.divIcon({
        className: `op-marker fog-${st}${isGenerated(island) ? ' kind-gen' : ''}${island.id === sel ? ' selected' : ''}`,
        html: `<span class="dot"></span><span class="label">${esc(island.name)}</span>${jp}`,
        iconSize: [0, 0],
        iconAnchor: [0, 0],
      })
      const mk = L.marker(island.coords, { icon }).addTo(map)
      mk.on('click', () => select(island.id))
      markersById[island.id] = mk
    }

    if (!fitted) { fitToKnown(known); fitted = true }
  }

  function makePlayerIcon() {
    return L.divIcon({
      className: 'op-player-pin',
      html: '<span class="pulse"></span><span class="pulse pulse-2"></span><span class="glow"></span>',
      iconSize: [0, 0],
      iconAnchor: [0, 0],
    })
  }

  function setPlayerLatLng(ll) {
    if (!playerMarker || !ll) return
    playerMarker.setLatLng(ll)
    playerAt = ll
  }

  // Create the pin (snaps on first run) or slide it to the new point.
  function syncPlayer() {
    if (!map) return
    const target = playerLatLng()
    if (!target) {
      if (playerAnim) { cancelAnimationFrame(playerAnim); playerAnim = null }
      playerMarker?.remove(); playerMarker = null; playerAt = null
      return
    }
    if (!playerMarker) {
      playerMarker = L.marker(target, { icon: makePlayerIcon(), interactive: false, zIndexOffset: 1000 }).addTo(map)
      playerAt = target
      return
    }
    animatePlayerTo(target)
  }

  // Slide the pin to `target` via rAF, interpolating latLng each frame. No CSS transition,
  // which would drag the pin during pan/zoom.
  function animatePlayerTo(target) {
    const from = playerAt
    if (!from) { setPlayerLatLng(target); return }
    if (from[0] === target[0] && from[1] === target[1]) return
    if (playerAnim) cancelAnimationFrame(playerAnim)
    const DURATION = 2200
    const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2)
    let startTs = null
    const step = (ts) => {
      if (startTs === null) startTs = ts
      const p = Math.min(1, (ts - startTs) / DURATION)
      const k = ease(p)
      setPlayerLatLng([from[0] + (target[0] - from[0]) * k, from[1] + (target[1] - from[1]) * k])
      playerAnim = p < 1 ? requestAnimationFrame(step) : null
    }
    playerAnim = requestAnimationFrame(step)
  }

  onMount(() => {
    // Custom CRS cloned from L.CRS.Simple; does not mutate the global.
    const mapMaxZoom = 7
    const mapMaxResolution = 2.0
    const tileExtent = [0, 0, 50000, 50000]
    const mapMinResolution = Math.pow(2, mapMaxZoom) * mapMaxResolution
    const crs = L.extend({}, L.CRS.Simple, {
      transformation: new L.Transformation(1, -tileExtent[0], -1, tileExtent[3]),
      scale: (zoom) => Math.pow(2, zoom) / mapMinResolution,
      zoom: (scale) => Math.log(scale * mapMinResolution) / Math.LN2,
    })

    map = L.map(mapEl, {
      crs,
      minZoom: 1,
      maxZoom: 7,
      zoomControl: false, // wheel/pinch only
      attributionControl: false, // custom attribution instead
    })

    L.tileLayer(TILE_URL, {
      minZoom: 1,
      maxZoom: 7,
      maxNativeZoom: 6, // pre-bundle stops at z6; z7 is upscale
      tileSize: L.point(512, 512),
      noWrap: true,
      tms: false,
    }).addTo(map)

    // Needle is fixed in px, so zoom changes the latlng/screen mapping; redraw it.
    map.on('zoomend', () => { if (ready && focusedCardId) syncVivreRay() })

    ready = true
    return () => {
      if (playerAnim) cancelAnimationFrame(playerAnim)
      clearVivreRay()
      map?.remove()
      map = null
      markersById = {}
      playerMarker = null
      playerAt = null
      playerAnim = null
    }
  })

  // Redraw islands on structural change; while at sea currentIslandId is null, so
  // voyage progress only animates the pin.
  $effect(() => {
    islands
    currentIslandId
    if (ready) drawAll()
  })

  // Animate the pin on position change.
  $effect(() => {
    position
    if (ready) syncPlayer()
  })

  // Sync selection without redrawing or re-fitting.
  $effect(() => {
    selectedId
    if (ready) applySelection()
  })

  // Redraw the focused vivre ray; depends on focus, pin position, and the card inventory.
  $effect(() => {
    focusedCardId
    position
    activeVivre
    if (ready) syncVivreRay()
  })
</script>

<div class="map" data-testid="map-root">
  <!-- Leaflet render container -->
  <div class="map-stage" bind:this={mapEl} data-testid="map-stage"></div>

  <!-- Discovery counter -->
  <div class="counter" data-testid="map-counter">{t('map.counter', { mapped: mappedCount, total: totalCount })}</div>

  {#if onclose}
    <button class="close" data-testid="map-close" onclick={onclose} aria-label={t('map.close')}>✕</button>
  {/if}

  <!-- Voyage-rules button; only at sea -->
  {#if atSea}
    <button
      class="info-btn"
      class:active={showVoyage}
      data-testid="map-voyage-info-btn"
      onclick={() => (showVoyage = !showVoyage)}
      aria-label={t('map.voyage_info')}
      title={t('map.voyage_info')}
    >i</button>

    {#if showVoyage}
      <div class="voyage-info" data-testid="map-voyage-info">
        <h4>{t('map.voyage_title')}</h4>
        {#if voyage}
          <p class="voyage-route">{voyage.origin} → {voyage.dest}</p>
          {#if voyage.total != null}
            <p class="voyage-progress">
              {t('map.voyage_day', { elapsed: voyage.elapsed, total: voyage.total })}
              {#if voyage.remaining > 0}{t('map.voyage_left', { n: voyage.remaining })}{:else}{t('map.voyage_in_sight')}{/if}
            </p>
            <div class="voyage-bar"><span style="width:{voyage.pct}%"></span></div>
          {/if}
        {/if}
        <ul>
          <li>{t('map.rule_fixed_days')}</li>
          <li>{t('map.rule_time_passes')}</li>
          <li>{t('map.rule_hurry')}</li>
        </ul>
      </div>
    {/if}
  {/if}

  <!-- Legend -->
  {#if legendStates.length}
    <div class="legend" data-testid="map-legend">
      <h4>{t('map.legend')}</h4>
      {#each legendStates as s}
        <div class="legend-row"><span class="ldot fog-{s}"></span> {fogLabel(s)}</div>
      {/each}
    </div>
  {/if}

  <!-- Vivre Cards: bearing per card from the player position; click lights a short ray. -->
  {#if activeVivre.length}
    <div class="vivre-overlay" data-testid="map-vivre-overlay">
      <h4>{t('map.vivre_title')}</h4>
      <ul>
        {#each activeVivre as c (c.npc_id)}
          {@const d = c.direction || {}}
          <li>
            <button
              type="button"
              class="vivre-row state-{c.visual_state || 'white'}"
              class:focused={focusedCardId === c.npc_id}
              class:unstable={d.stable === false}
              data-testid="vivre-card-row"
              onclick={() => focusVivre(c)}
              title={d.same_island ? t('map.same_island') : t('map.heading', { cardinal: d.cardinal })}
            >
              <span class="vivre-arrow" style={d.same_island ? '' : `--b: ${d.bearing_deg}deg; transform: rotate(${d.bearing_deg}deg)`}
                >{d.same_island ? '⌖' : '↑'}</span
              >
              <span class="vivre-name">{c.name || t('map.unknown')}</span>
              <span class="vivre-dir">{d.same_island ? t('map.here') : d.cardinal}</span>
            </button>
          </li>
        {/each}
      </ul>
    </div>
  {/if}

  <!-- Read-only side panel from the LOCATION card -->
  {#if selected}
    {@const cs = selected.current_state || {}}
    <aside class="side" data-testid="map-side-panel">
      <header class="side-hero">
        <span class="tag">{(selected.canonical || cs.canonical || 'canon')} · LOCATION</span>
        <div class="side-name">
          <h1 data-testid="side-name">{selected.name}</h1>
          {#if selected.jp_name}<div class="side-jp">{selected.jp_name}</div>{/if}
        </div>
        <div class="side-cluster">{selected.region || ''}{selected.region && selected.cluster ? ' · ' : ''}{selected.cluster || ''}</div>
      </header>

      {#if cs.summary_text}
        <section class="side-section">
          <h3>{t('map.state')}</h3>
          <p>{cs.summary_text}</p>
        </section>
      {/if}

      {#if (cs.flags || []).length}
        <section class="side-section">
          <h3>{t('map.flags')}</h3>
          <div class="chips">{#each cs.flags as flag}<span class="chip">{flag}</span>{/each}</div>
        </section>
      {/if}

      {#if selected.description}
        <section class="side-section">
          <h3>{t('map.description')}</h3>
          <p>{selected.description}</p>
        </section>
      {/if}

      {#if (selected.related || []).length}
        <section class="side-section">
          <h3>{t('map.related')}</h3>
          <div class="related">
            {#each selected.related as r}
              <div class="related-item">
                <span class="related-kind">{r.kind}</span>
                <span class="related-name">{r.name}</span>
              </div>
            {/each}
          </div>
        </section>
      {/if}
      <!-- No action-row; the map has no action buttons. -->
    </aside>
  {/if}

  <!-- Tile attribution, always visible -->
  <div class="attribution" data-testid="map-attribution">Tiles · Library of Ohara · Map data ©Eiichiro Oda</div>
</div>

<style>
  .map {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 480px;
    background: #0a2440;
    color: var(--ink, #f7f8f8);
    overflow: hidden;
    font-family: var(--sans);
    font-size: 14px;
    letter-spacing: -0.011em;
  }
  .map-stage {
    position: absolute;
    inset: 0;
    z-index: 1;
    background: #0a2440;
  }

  /* ===== chrome above the map ===== */
  .counter {
    position: absolute;
    top: 0.7rem;
    right: 0.8rem;
    z-index: 1000;
    background: rgba(10, 11, 13, 0.82);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    backdrop-filter: blur(10px);
    padding: 0.3rem 0.7rem;
    font-size: 0.76rem;
    font-variant-numeric: tabular-nums;
    color: #d0d6e0;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  }
  .close {
    position: absolute;
    top: 0.7rem;
    left: 0.8rem;
    z-index: 1000;
    background: rgba(10, 11, 13, 0.82);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    backdrop-filter: blur(10px);
    color: #d0d6e0;
    cursor: pointer;
    padding: 0.28rem 0.6rem;
    font-size: 0.78rem;
    transition: background 0.12s ease, color 0.12s ease;
  }
  .close:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #f7f8f8;
  }

  /* voyage-rules button and popover */
  .info-btn {
    position: absolute;
    top: 2.7rem;
    right: 0.8rem;
    z-index: 1001;
    width: 1.7rem;
    height: 1.7rem;
    display: grid;
    place-items: center;
    background: rgba(10, 11, 13, 0.82);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 99px;
    backdrop-filter: blur(10px);
    color: #828fff;
    cursor: pointer;
    font-family: var(--sans);
    font-weight: 600;
    font-size: 0.82rem;
    line-height: 1;
    transition: background 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease;
  }
  .info-btn:hover,
  .info-btn.active {
    background: rgba(94, 106, 210, 0.22);
    border-color: rgba(130, 143, 255, 0.6);
    box-shadow: 0 0 12px rgba(94, 106, 210, 0.5);
  }
  .voyage-info {
    position: absolute;
    top: 4.8rem;
    right: 0.8rem;
    z-index: 1001;
    width: min(300px, 78%);
    background: rgba(10, 11, 13, 0.92);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 0.75rem 0.9rem;
    font-size: 0.78rem;
    line-height: 1.5;
    color: #d0d6e0;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(12px);
  }
  .voyage-info h4 {
    margin: 0 0 0.45rem;
    font-size: 0.64rem;
    font-weight: 550;
    color: #8a8f98;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
  .voyage-route { margin: 0 0 0.2rem; font-weight: 590; letter-spacing: -0.01em; color: #f7f8f8; }
  .voyage-progress { margin: 0 0 0.35rem; color: #8a8f98; font-size: 0.74rem; font-variant-numeric: tabular-nums; }
  .voyage-bar { height: 4px; border-radius: 99px; background: rgba(255, 255, 255, 0.1); overflow: hidden; margin-bottom: 0.55rem; }
  .voyage-bar span { display: block; height: 100%; background: linear-gradient(90deg, #5e6ad2, #828fff); transition: width 400ms ease; }
  .voyage-info ul { margin: 0; padding-left: 1.05rem; display: grid; gap: 0.3rem; }
  .voyage-info li { color: #8a8f98; }

  .legend {
    position: absolute;
    bottom: 1.8rem;
    left: 0.8rem;
    z-index: 1000;
    background: rgba(10, 11, 13, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    backdrop-filter: blur(10px);
    padding: 0.6rem 0.8rem;
    font-size: 0.74rem;
    color: #d0d6e0;
    pointer-events: none;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  }
  .legend h4 {
    margin: 0 0 0.4rem;
    font-size: 0.62rem;
    font-weight: 550;
    color: #8a8f98;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
  .legend-row { display: flex; align-items: center; gap: 0.45rem; padding: 0.12rem 0; }
  .ldot { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; background: #8a8270; }
  .ldot.fog-current { background: #828fff; box-shadow: 0 0 8px #828fff; }
  .ldot.fog-visited { background: #fbbf24; box-shadow: 0 0 8px #fde68a; }
  .ldot.fog-seen { background: #8a8270; }
  .ldot.fog-gen { background: #e3f6ff; box-shadow: 0 0 6px #e3f6ff; }

  /* ===== Vivre Cards: bearing on the map ===== */
  .vivre-overlay {
    position: absolute;
    top: 3rem;
    left: 0.8rem;
    z-index: 1000;
    max-width: 230px;
    background: rgba(10, 11, 13, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    backdrop-filter: blur(10px);
    padding: 0.55rem 0.6rem;
    font-size: 0.78rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  }
  .vivre-overlay h4 {
    margin: 0 0 0.4rem;
    padding: 0 0.15rem;
    font-size: 0.62rem;
    font-weight: 550;
    color: #8a8f98;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
  .vivre-overlay ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.15rem; }
  .vivre-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: #d0d6e0;
    cursor: pointer;
    padding: 0.24rem 0.4rem;
    font: inherit;
    letter-spacing: inherit;
    text-align: left;
    transition: background 0.12s ease, border-color 0.12s ease;
  }
  .vivre-row:hover { background: rgba(255, 255, 255, 0.06); }
  .vivre-row.focused { background: rgba(94, 106, 210, 0.18); border-color: rgba(130, 143, 255, 0.55); color: #f7f8f8; }
  .vivre-arrow {
    display: inline-block;
    width: 1.1em;
    text-align: center;
    font-weight: 700;
    color: #fde68a;
    flex: 0 0 auto;
    transform-origin: 50% 50%;
  }
  .vivre-name { flex: 1 1 auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .vivre-dir { color: #8a8f98; font-size: 0.7rem; flex: 0 0 auto; letter-spacing: 0.03em; }
  /* card vital state (maps visual_state) */
  .vivre-row.state-burning .vivre-arrow { color: #fc7840; text-shadow: 0 0 7px rgba(252, 120, 64, 0.9); }
  .vivre-row.state-errant .vivre-arrow { color: #cdd6e0; opacity: 0.85; }
  .vivre-row.unstable .vivre-arrow { animation: vivre-tremble 1.1s ease-in-out infinite; }
  @keyframes vivre-tremble {
    0%, 100% { transform: rotate(var(--b, 0deg)); }
    25% { transform: rotate(calc(var(--b, 0deg) - 9deg)); }
    75% { transform: rotate(calc(var(--b, 0deg) + 9deg)); }
  }

  /* directional ray drawn by Leaflet as an SVG path */
  :global(path.vivre-ray) { filter: drop-shadow(0 0 4px rgba(253, 230, 138, 0.7)); }
  :global(path.vivre-ray.unstable) { animation: vivre-ray-flicker 1.2s ease-in-out infinite; }
  @keyframes vivre-ray-flicker { 0%, 100% { opacity: 0.9; } 50% { opacity: 0.35; } }

  .side {
    position: absolute;
    top: 0;
    right: 0;
    width: min(360px, 80%);
    height: 100%;
    z-index: 1000;
    background: rgba(10, 11, 13, 0.94);
    border-left: 1px solid rgba(255, 255, 255, 0.12);
    padding: 1.1rem 1.2rem;
    overflow: auto;
    box-shadow: -24px 0 64px rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(14px);
    animation: sideIn 0.18s ease-out;
  }
  @keyframes sideIn {
    from { transform: translateX(12px); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  .side-hero { border-bottom: 1px solid rgba(255, 255, 255, 0.1); padding-bottom: 0.8rem; margin-bottom: 0.8rem; }
  .side-hero .tag {
    font-family: var(--mono);
    font-size: 0.6rem;
    color: #828fff;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
  .side-name h1 {
    font-size: 1.15rem;
    font-weight: 590;
    letter-spacing: -0.02em;
    color: #f7f8f8;
    margin: 0.3rem 0 0;
  }
  .side-jp { color: #8a8f98; font-size: 0.8rem; }
  .side-cluster { color: #8a8f98; font-size: 0.74rem; margin-top: 0.25rem; }
  .side-section { margin-bottom: 0.95rem; }
  .side-section h3 {
    font-size: 0.62rem;
    font-weight: 550;
    color: #8a8f98;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin: 0 0 0.35rem;
  }
  .side-section p { margin: 0; line-height: 1.6; font-size: 0.82rem; color: #d0d6e0; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.3rem; }
  .chip {
    background: rgba(94, 106, 210, 0.14);
    border: 1px solid rgba(130, 143, 255, 0.35);
    color: #b0b8ff;
    border-radius: 99px;
    padding: 0.12rem 0.55rem;
    font-size: 0.7rem;
    font-weight: 500;
  }
  .related { display: grid; gap: 0.3rem; }
  .related-item { display: flex; gap: 0.5rem; align-items: baseline; }
  .related-kind { font-family: var(--mono); font-size: 0.6rem; color: #8a8f98; text-transform: uppercase; letter-spacing: 0.06em; min-width: 64px; }
  .related-name { font-size: 0.82rem; color: #f7f8f8; }

  .attribution {
    position: absolute;
    bottom: 0.35rem;
    right: 0.8rem;
    z-index: 1000;
    font-size: 0.62rem;
    color: rgba(247, 248, 248, 0.5);
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
  }

  /* ===== markers and player pin (Leaflet-injected, must be global) ===== */
  :global(.op-marker) { width: 0; height: 0; cursor: pointer; }
  :global(.op-marker .dot) {
    position: absolute;
    left: -7px; top: -7px;
    width: 14px; height: 14px;
    border-radius: 50%;
    background: radial-gradient(circle at 35% 30%, #fde68a 0%, #fbbf24 55%, #b8860b 100%);
    box-shadow: 0 0 0 2px #0a2440, 0 0 12px rgba(251, 191, 36, 0.7), 0 3px 8px rgba(0, 0, 0, 0.6);
    transition: transform 200ms cubic-bezier(0.2, 0.7, 0.3, 1.3);
  }
  :global(.op-marker:hover .dot) { transform: scale(1.35); }
  :global(.op-marker .label) {
    position: absolute;
    left: 14px; top: -14px;
    white-space: nowrap;
    font-weight: 600;
    font-size: 12px;
    letter-spacing: -0.01em;
    color: #f7f8f8;
    text-shadow: 0 0 4px #0a2440, 0 0 4px #0a2440, 0 1px 2px rgba(0, 0, 0, 0.9), 1px 0 0 #0a2440, -1px 0 0 #0a2440;
    pointer-events: none;
  }
  :global(.op-marker .label-jp) {
    position: absolute;
    left: 14px; top: 3px;
    white-space: nowrap;
    font-size: 9px;
    color: #fde68a;
    text-shadow: 0 0 3px #0a2440, 0 0 3px #0a2440;
    pointer-events: none;
    letter-spacing: 0.5px;
  }
  /* fog seen: smaller grey dot, labels hidden until hover */
  :global(.op-marker.fog-seen .dot) {
    background: radial-gradient(circle at 35% 30%, #d0c8b8 0%, #8a8270 60%, #4a4538 100%);
    box-shadow: 0 0 0 2px #0a2440, 0 2px 4px rgba(0, 0, 0, 0.6);
    width: 10px; height: 10px; left: -5px; top: -5px;
  }
  :global(.op-marker.fog-seen .label),
  :global(.op-marker.fog-seen .label-jp) { opacity: 0; transition: opacity 150ms; }
  :global(.op-marker.fog-seen:hover .label) { opacity: 0.6; }
  /* in-game generated; must follow fog-seen in source order to win the color */
  :global(.op-marker.kind-gen .dot) {
    background: radial-gradient(circle at 35% 30%, #ffffff 0%, #e3f6ff 55%, #5a93b8 100%);
    box-shadow: 0 0 0 2px #0a2440, 0 0 10px rgba(227, 246, 255, 0.8), 0 3px 8px rgba(0, 0, 0, 0.6);
  }
  :global(.op-marker.kind-gen .label-jp) { color: #e3f6ff; }
  /* selected */
  :global(.op-marker.selected .dot) {
    transform: scale(1.5);
    box-shadow: 0 0 0 2px #0a2440, 0 0 0 4px #828fff, 0 0 22px rgba(130, 143, 255, 0.85);
  }

  :global(.op-player-pin) { width: 0; height: 0; pointer-events: none; }
  :global(.op-player-pin .pulse) {
    position: absolute;
    left: -22px; top: -22px;
    width: 44px; height: 44px;
    border-radius: 50%;
    border: 2.5px solid #828fff;
    animation: op-ring-pulse 2.4s ease-out infinite;
  }
  :global(.op-player-pin .pulse-2) { border-color: #ffffff; animation-delay: 1.2s; }
  :global(.op-player-pin .glow) {
    position: absolute;
    left: -16px; top: -16px;
    width: 32px; height: 32px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(94, 106, 210, 0.75) 0%, rgba(94, 106, 210, 0) 70%);
    animation: op-glow-pulse 2.4s ease-in-out infinite;
  }
  @keyframes op-ring-pulse { 0% { transform: scale(0.4); opacity: 1; } 100% { transform: scale(1.6); opacity: 0; } }
  @keyframes op-glow-pulse { 0%, 100% { transform: scale(1); opacity: 0.6; } 50% { transform: scale(1.3); opacity: 0.2; } }

  /* hide the default Leaflet UI we replace */
  :global(.leaflet-control-zoom) { display: none !important; }
</style>
