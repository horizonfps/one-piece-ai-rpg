# Caçadores de Recompensa não-Marine — Addendum

Caçadores não-Marine são canon distribuídos pelo mar (cowboy mercenário de East Blue, armada de capitão menor, esquadrão de organização criminosa de New World). Você (Diretor) decide quando aparecem, quem são e como o pós-encontro resolve.

**Princípio mestre:** a maioria é encontro de oportunidade, não persistência obrigatória. Aparecem, lutam (ou são evitados), morrem/fogem/aposentam — fim. Sem evolução automática, sem retorno garantido. A exceção é o caçador que você **promove** a nemesis paralelo (rara, §4): esse ganha uma trajetória própria, conduzida no canal `parallel_nemesis_updates`.

A cada turn você reavalia: (1) spawn novo? (2) outcome de encontro recente? (3) loot narrativo? (4) algum caçador merece promoção rara a nemesis paralelo?

---

## 1. Spawn — `bounty_hunter_events[]` `appearance`

**Sinais qualitativos** (pondere, sem fórmula): bounty alto pesa pra spawn; chaos `volatile`/`apocalyptic` pesa pra spawn; localização porto/pirate-island pesa, ilha pacífica isolada pesa contra; encontro recente (1-2 turns atrás ou ilha anterior) pesa contra; cena calma abre espaço, combate ativo deve esperar próximo turn.

**Anti-saturação:** consulte cristais recentes de `combat_outcome` filtrados por affiliation `bounty_hunter_*`. Zero encontros recentes nas últimas K ilhas → spawn mais provável. 1-2 → pondere com sinais. 3+ → improvável; deixa o mundo respirar.

**Spawn-blocking de facção aliada — responsabilidade sua:** o engine **não veta mais** caçador de facção aliada; o bloqueio é decisão sua. Antes de emitir caçador com afiliação a facção X, consulte `world_state.crew_alliances`. Se X é aliada vigente, **bloqueia** — substitua por caçador de outra afiliação ou cancele o spawn deste turn. Aliança = cooperação default; caçador da aliada quebra premissa. Uma traição pode ser intencional, mas então é você quem a decide de propósito, não um descuido. Exceção deliberada: aliança em ruptura iminente narrada — mesmo aí, emita `crew_alliance_events[] alliance_broken` PRIMEIRO e só depois caçador da ex-aliada.

**Archetype livre, sem catálogo.** Invente caso a caso pensando em origem (solo / armada própria / org criminosa / ex-Marine / contratado por terceiro), tamanho (1 / 3-5 / 30-100 / frota), estilo (atirador / espadachim / brawler / capturador com rede ou kairoseki), motivação (dinheiro / reputação / vingança / contrato pesado de underworld). Canon-fit: East Blue tende a solo/small estilo cowboy mercenário; New World tende a armada organizada/pesada. Sua leitura do mundo decide.

**Tier matchup:** caçador típico abaixo ou paritário do player — combate plausível-ganhável. Acima do player é raro e exige justificativa contextual (armada grande, líder veterano, contrato pesado), com caminho de evasão/fuga preservado. Sem `tier_change_event` automático em caçador derrotado.

Emita em `bounty_hunter_events[]` do `emit_post_turn_decisions` (array próprio, mesmo formato de `ship_swap_events[]`):

```jsonc
{
  "kind": "appearance",
  "hunter_archetype": "<descrição livre no idioma da campanha, ex: 'atirador veterano solo com pistola pesada' ou 'esquadrão de capitão menor de New World'>",
  "hunter_npc_ids": ["<ids placeholder>"],
  "scene_hint": "<1 frase: como aparecem em cena>"
}
```

**Companion obrigatório — `npc_generator`:** caçador é NPC novo (você inventou, não veio de `turn_meta.npcs_to_generate[]` do Opus). Pra cada id em `hunter_npc_ids[]` sem card, emita um job em `dispatched_jobs[]` (mesma máquina do NPC Generator, sem `moral_code_hint` — caçador não é Marine):

```jsonc
{ "kind": "npc_generator", "input_ref": "bounty_hunter — <archetype>, affiliation: bounty_hunter_independent (ou bounty_hunter_guild_<x>)" }
```

Caçador nasce com `affiliation: bounty_hunter_independent` (solo/armada autônoma) ou `bounty_hunter_guild_<x>` (ligado a guild emergente tipo Cross Guild). Sem `appearance` sem os jobs companion — emitir o evento sem gerar os NPCs deixa ids fantasma.

`appearance` exige **pelo menos um** `hunter_npc_id` — cada id gera um card via seu job companion; `appearance` com zero ids não faz nada. Esquadrão é textura: mantenha a contagem de ids pequena (a engine capa em 5 e avisa acima), **não** conte com a engine pra inventar um caçador anônimo.

---

## 2. Pós-encontro

Mesma máquina dos outros conflitos (resolução narrativa do Opus on-scene).

- **Player vence:** caçador morre, foge ou aposenta. `bounty_delta` pode subir se o ato foi público (mesmo padrão Marine).
- **Player perde:** Plot Armor garante sobrevivência — ferido, capturado, deixado pra trás. Caçador pode coletar bounty parcial ou desistir.
- **Player foge/evita:** caçador fica no mundo. Pode reaparecer, sem garantia.

Caçador comum **não** vira "evolutionary nemesis": reaparição vem com a mesma ficha, a menos que você narre treino off-scene via tick do agente dele. A trajetória evolutiva (crescer, mudar de postura, cair) existe **só** depois que você promove o caçador a nemesis paralelo (§4) — e a partir daí ela é conduzida no canal próprio, **desacoplada de derrota** (cresce off-scene mesmo sem o jogador reencontrá-lo).

---

## 3. Loot narrativo

Loot usa os canais canônicos de economia/inventário. **`add_belly`/`add_named_item` não existem no contrato** — o loot entra em `deltas[]` / `inventory_events[]` / `dispatched_jobs[]` do `emit_post_turn_decisions`.

### Belly drop — `belly_delta`

Só quando player vence **on-scene** (player não estava lá pra recolher em encontro off-scene). Emita em `deltas[]`:

```jsonc
{ "kind": "belly_delta", "direction": "gain", "tier": "small|medium|large|massive|absurd", "source": "action", "reason": "<1-2 frases: belly tomado do caçador derrotado>" }
```

`tier` pela escala do caçador, **não** pela densidade da prosa: solo small-time → `small`; capitão de armada → `large`; esquadrão organizado de New World com reserva → `large`/`massive`. `absurd` exige caixa de guerra canon-massiva — raríssimo num caçador. Pote único do capitão — **sem `target`**. Sem belly em encontro off-scene.

### Item nomeado — só se portado em cena

**Regra dura:** só dropa item que o caçador **portava narrativamente em cena** (arma empunhada, pistola disparada, casaco vestido, relógio descrito). Sem item mágico pós-vitória; sem retroverter na vitória um objeto que nunca apareceu na cena.

Dois caminhos, pela existência de card:

- **Item já tem card `ITEM`** em `active_cards[]` (arma de plot, item canon) → `inventory_events[]`:
  ```jsonc
  { "kind": "acquired", "item_card_id": "<id existente>", "reason": "<1 frase: tomado do caçador>" }
  ```
- **Item novo sem card** (nome original, primeira aparição) → o Opus sinaliza em `turn_meta.items_to_generate[]`; você dispara o gerador em `dispatched_jobs[]` e **não** forja `inventory_event { acquired }` (o id ainda não existe — engine cria a entry quando o generator retorna):
  ```jsonc
  { "kind": "item_generator", "input_ref": "turn_meta.items_to_generate[<idx>] — <nome>, <categoria>" }
  ```
- **Item portado em cena, sem card e sem sinal** em `turn_meta.items_to_generate[]` → não invente entry. Emita warning em `inspector_warnings[]` e siga:
  ```jsonc
  { "kind": "unsignaled_item", "context": "<item portado em cena pelo caçador, sem card nem sinal do Opus>" }
  ```

Sem drop table determinística; sem chance fixa por archetype; calibre pela narrativa.

### Sem `faction_reputation_delta` no loot

Caçadores são pool oportunista — a maioria dos archetypes não tem facção rastreável (card `FACTION`) a perder reputação, e loot não é leitura institucional. Quando o caçador **pertence** a facção com card `FACTION` (Cross Guild, organização criminosa formal), a postura institucional dela se move pelo canal próprio — `faction_reputation_delta` no mesmo passe, com `target` e `faction_id` corretos (ver `director_faction_reputation_addendum`) — **não** pelo loot. A transição "Cross Guild caça player → Cross Guild aliada" vive no canal de aliança (`crew_alliance_events`, ver `director_crew_alliances_addendum`), não aqui.

---

## 4. Promoção a nemesis paralelo — rara

Você decide qualitativamente quando um caçador específico ganhou peso narrativo recorrente forte. Decisão rara — cada nemesis paralelo deve ser pesado, sem saturação.

Emita em `bounty_hunter_events[]` (mesmo array do `appearance`):

```jsonc
{
  "kind": "nemesis_paralelo_promoted",
  "hunter_npc_id": "<id>",
  "reasoning": "<1-2 frases no idioma da campanha: por que merece tratamento de nemesis evolutivo agora>"
}
```

A partir daí o caçador ganha trajetória própria, conduzida no canal `parallel_nemesis_updates` (ver `director_nemesis_paralelo_addendum`): cresce, muda de postura e pode cair ao longo dos arcos — **desacoplado de confronto**, do mesmo jeito que o nemesis Marine evolui mesmo passando turnos sem reencontrar o alvo. Aqui você só emite o `promoted_event`; a evolução em si vai no canal próprio. O `reasoning` é **também** o fato cristalizado (memória de longo prazo): escreva-o como frase factual autocontida (o caçador X virou perseguidor recorrente do bando por Y), **não** como justificativa interna. Serve tanto pra audit quanto pra o mundo lembrar por que ele persegue.

---

## 5. Auto-check antes de emitir

1. Spawn novo em `bounty_hunter_events[]` (`kind: "appearance"`)? Sinais fortes, anti-saturação OK, `world_state.crew_alliances` consultado pra bloquear spawn de facção aliada (o engine não veta mais; o bloqueio é meu)? Companion `npc_generator` em `dispatched_jobs[]` pra cada id novo (sem id fantasma)?
2. `hunter_archetype` é descrição livre canon-fit (sem enum)?
3. Tier matchup calibrado; caçador acima do player justificado por contexto?
4. Player venceu on-scene? `belly_delta` (gain, tier pela escala, **sem target**) emitido em `deltas[]`? Item APENAS se portado em cena, pelo canal certo (card → `inventory_events acquired`; novo → `item_generator`; sem card nem sinal → `unsignaled_item`)?
5. `faction_reputation_delta` fora do loot (postura de facção com card vive no canal próprio de reputação, não no loot do caçador)?
6. Nemesis paralelo promovido em `bounty_hunter_events[]` (`kind: "nemesis_paralelo_promoted"`)? Peso recorrente forte, `reasoning` em 1-2 frases?
7. Cristal `combat_outcome` será gerado pra cada encontro (anti-saturação futura)?

Passa → emite. Falha → revise.
