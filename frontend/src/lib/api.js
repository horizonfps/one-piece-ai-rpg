// Backend API client. Relative paths: Vite proxies /api in dev, same-origin in prod.

import { apiError } from './i18n.svelte.js'

async function jsonOrThrow(res) {
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* non-JSON body */
    }
    throw new Error(apiError(detail))
  }
  return res.json()
}

export async function getHealth() {
  return jsonOrThrow(await fetch('/api/health'))
}

export async function listCampaigns() {
  const d = await jsonOrThrow(await fetch('/api/campaigns'))
  return d.campaigns
}

export async function createCampaign(name) {
  return jsonOrThrow(
    await fetch('/api/campaigns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name || null }),
    })
  )
}

export async function getCampaign(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}`))
}

// Deletes a campaign and its whole save; UI confirms first.
export async function deleteCampaign(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}`, { method: 'DELETE' }))
}

// App settings, stored separately from the save.
export async function getSettings() {
  return jsonOrThrow(await fetch('/api/settings'))
}

export async function updateSettings(patch) {
  return jsonOrThrow(
    await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
  )
}

// In-game tutorial: player guide markdown read from disk, per UI language.
export async function getPlayerGuide(lang = 'pt-br') {
  return jsonOrThrow(await fetch(`/api/player-guide?lang=${encodeURIComponent(lang)}`))
}

// OAuth broker: returns the auth url; caller opens it and polls getHealth for completion.
export async function connectClaude() {
  return jsonOrThrow(await fetch('/api/setup/connect-claude', { method: 'POST' }))
}

// Regenerates the last turn's narration; optional instruction is one-shot, not persisted.
export async function rerollProse(id, turnIndex, instruction = '') {
  return jsonOrThrow(
    await fetch(`/api/campaigns/${id}/turns/${turnIndex}/reroll-prose`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction }),
    })
  )
}

// Undoes the last turn, reverting world state; returns the original input for the composer.
export async function rewindTurn(id, turnIndex) {
  return jsonOrThrow(
    await fetch(`/api/campaigns/${id}/turns/${turnIndex}/rewind`, { method: 'POST' })
  )
}

// Character creation.
export async function getCatalog() {
  return jsonOrThrow(await fetch('/api/catalog'))
}

export async function rollTraits({ seed = null, count = null } = {}) {
  const d = await jsonOrThrow(
    await fetch('/api/catalog/roll-traits', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed, count }),
    })
  )
  return d.traits
}

export async function createCharacter(campaignId, sheet) {
  return jsonOrThrow(
    await fetch(`/api/campaigns/${campaignId}/character`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sheet),
    })
  )
}

// META directives.
export async function listDirectives(id) {
  const d = await jsonOrThrow(await fetch(`/api/campaigns/${id}/directives`))
  return d.directives
}

export async function deactivateDirective(id, directiveId) {
  return jsonOrThrow(
    await fetch(`/api/campaigns/${id}/directives/${directiveId}/deactivate`, { method: 'POST' })
  )
}

// Map and navigation, read-only: islands with fog, position, day counter.
export async function getWorld(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/world`))
}

// Memory inspector.
export async function listCards(id, kind) {
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : ''
  const d = await jsonOrThrow(await fetch(`/api/campaigns/${id}/cards${qs}`))
  return d.cards
}

export async function searchMemory(id, query, { kind, category } = {}) {
  const params = new URLSearchParams({ q: query })
  if (kind) params.set('kind', kind)
  if (category) params.set('category', category)
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/search?${params.toString()}`))
}

// News Coo: newspaper editions plus nemesis state.
export async function listNews(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/news`))
}

// Communication: paired mushis, vivre cards, ongoing call.
export async function getComms(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/comms`))
}

// Economy and inventory: belly, bucket, resolved item cards.
export async function getEconomy(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/economy`))
}

// Inventory items: human add/edit/remove. Editing doesn't advance the turn.
export async function addInventoryItem(id, body) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/inventory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }))
}

export async function editInventoryItem(id, itemCardId, patch) {
  return jsonOrThrow(await patchJson(`/api/campaigns/${id}/inventory/${itemCardId}`, patch))
}

export async function deleteInventoryItem(id, itemCardId) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/inventory/${itemCardId}`, { method: 'DELETE' }))
}

// Ship and Jolly Roger: fleet (active plus reserve) and crew flag.
export async function getFleet(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/fleet`))
}

export async function setJollyRoger(id, description) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/jolly-roger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  }))
}

// Faction reputation: tracked institutional stance per faction.
export async function getFactions(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/factions`))
}

// Living legend: wanted posters of player and crewmates with update history.
export async function getLegend(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/legend`))
}

// Inline human edit of a wanted poster (empty string clears a field).
export async function editLegend(id, cardId, patch) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/legend/${cardId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }))
}

export async function deleteLegend(id, cardId) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/legend/${cardId}`, { method: 'DELETE' }))
}

// Continuity threads: hooks planted for a later payoff; human-editable.
export async function getThreads(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/threads`))
}

export async function createThread(id, body) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/threads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }))
}

export async function editThread(id, hookId, patch) {
  return jsonOrThrow(await patchJson(`/api/campaigns/${id}/threads/${hookId}`, patch))
}

export async function deleteThread(id, hookId) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/threads/${hookId}`, { method: 'DELETE' }))
}

// Crew alliances: active alliances plus recent hunter encounters.
export async function getAlliances(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/alliances`))
}

// Crew: roster, alignment, pending NPC-to-player offers.
export async function getCrew(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/crew`))
}

// Accepts or declines an NPC-initiated crew invite.
export async function respondCrewOffer(id, npcId, accept) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/crew/offers/${npcId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accept }),
  }))
}

// Endgame: log of reached endings plus world flags.
export async function getEnding(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/ending`))
}

// Discovered poneglyphs plus revealed Laugh Tale.
export async function getPoneglyphs(id) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/poneglyphs`))
}

// Global edit mode: inline inspector edits don't advance the turn; next turn reads new
// state. Each PATCH sends only the touched fields.
function patchJson(url, body) {
  return fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function getCard(id, storyCardId) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/cards/${storyCardId}`))
}

export async function editCard(id, storyCardId, patch) {
  return jsonOrThrow(await patchJson(`/api/campaigns/${id}/cards/${storyCardId}`, patch))
}

export async function editPlayer(id, patch) {
  return jsonOrThrow(await patchJson(`/api/campaigns/${id}/player`, patch))
}

export async function listTechniques(id) {
  const d = await jsonOrThrow(await fetch(`/api/campaigns/${id}/techniques`))
  return d.techniques
}

export async function editTechnique(id, techniqueId, patch) {
  return jsonOrThrow(await patchJson(`/api/campaigns/${id}/techniques/${techniqueId}`, patch))
}

export async function deleteTechnique(id, techniqueId) {
  return jsonOrThrow(
    await fetch(`/api/campaigns/${id}/techniques/${techniqueId}`, { method: 'DELETE' })
  )
}

// Player breakthroughs and fruit usage log (editable inspector).
export async function editBreakthrough(id, kind, patch) {
  return jsonOrThrow(await patchJson(`/api/campaigns/${id}/breakthroughs/${kind}`, patch))
}

export async function deleteBreakthrough(id, kind) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/breakthroughs/${kind}`, { method: 'DELETE' }))
}

export async function editFruitUsage(id, index, patch) {
  return jsonOrThrow(await patchJson(`/api/campaigns/${id}/fruit-usage/${index}`, patch))
}

export async function deleteFruitUsage(id, index) {
  return jsonOrThrow(await fetch(`/api/campaigns/${id}/fruit-usage/${index}`, { method: 'DELETE' }))
}

export async function editCrystal(id, crystalId, patch) {
  return jsonOrThrow(await patchJson(`/api/campaigns/${id}/crystals/${crystalId}`, patch))
}

export async function deleteCrystal(id, crystalId) {
  return jsonOrThrow(
    await fetch(`/api/campaigns/${id}/crystals/${crystalId}`, { method: 'DELETE' })
  )
}

export async function editTurnProse(id, turnIndex, prose) {
  return jsonOrThrow(await patchJson(`/api/campaigns/${id}/turns/${turnIndex}/prose`, { prose }))
}

// Turn WebSocket. Same origin; swaps http(s) for ws(s).
export function turnSocketUrl(campaignId) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/api/campaigns/${campaignId}/turn`
}
