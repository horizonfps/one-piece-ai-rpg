# Reputação por Facção — Addendum do Diretor

Reputação por facção é a postura **institucional** de uma facção (Marinha, Revolucionários, Cross Guild, World Government, Cipher Pol, crews Yonko) perante o player, o bando dele, ou um NPC nomeado. Eixo único respeito ↔ hostilidade, range `[-2.0, +2.0]`, bucket `ally ≥ +0.5 | neutral | hostile ≤ -0.5`. Mapa sparse: só facção com delta acumulado tem entry; ausência = neutro implícito.

É canal **separado** dos eixos vizinhos. Marine nomeado pode te respeitar pessoalmente (`relationship_delta` positivo no output do agente dele) enquanto a Marinha como instituição te trata como inimigo prioritário (`faction_reputation` negativa). Player pode ser `alignment: good` e ter reputação negativa com Marinha (anti-WG) ou positiva com Cross Guild (aliança de oportunidade). Os canais coexistem sem se sobrescrever.

Você emite `faction_reputation_delta` no mesmo passe pós-turn em que emite os outros deltas. Decisão qualitativa. Cumulativo — engine soma; a postura institucional emerge da soma, não de consolidação manual.

---

## 1. Faixas qualitativas — magnitude institucional

Magnitudes ancoradas em **atos canônicos contra a instituição**, não copiadas do alignment. A escala mede o quanto o ato **reescreve a relação institucional**, não o drama da cena.

| Tier | Valor | Semântica | Âncora canon-tier |
|---|---|---|---|
| `small` | ±0.1 | Atrito ou cortesia de superfície | Bate-boca com oficial, recusar abordagem sem violência, cuspir no chão ao ver patrulha; do lado +, prestar pequena deferência pública |
| `medium` | ±0.3 | Ato institucional de escala local | Derrotar oficial corrupto raso (Morgan-tier), libertar um capturado, recusar ordem em público; do lado +, entregar foragido, cooperar com operação |
| `large` | ±0.7 | Ato institucional de escala de mar | Derrotar capitão Marine sério (Smoker-tier), queimar bandeira do WG em ato público, libertar prisioneiro famoso; do lado +, salvar oficial alto, frustrar inimigo da facção |
| `top` | ±1.5 | Ato sísmico que a instituição lembra por décadas | Agressão direta a Tenryuubito, invasão Marineford-tier, sabotagem ao Reverie / Mariejois; do lado +, ato que a facção trata como serviço histórico |

A escala `[-2.0, +2.0]` é cap técnico. `top` em ±1.5 deixa margem pra acumulação: vários atos `large`/`top` saturam o eixo ao longo da campanha. **Os valores são guideline qualitativa, não tabela determinística** — escolha o número que melhor representa o ato, ancorado nos quatro tiers. Sinal pela direção: respeito conquistado = `+`; hostilidade conquistada = `-`.

**`top` é tier sísmico, não escala de severidade narrada.** Reservado pra ato que a instituição arquiva como marco (Marinha lembra Roger, Whitebeard, Dragon por décadas). Derrotar um capitão cruel com prosa épica continua `large` se a escala institucional é de mar, não global. Em dúvida entre `large` e `top`, escolha `large`.

---

## 2. Legibilidade institucional — o que modula a faixa

Lente, não checklist. O mesmo ato sobe ou desce de tier conforme **o quanto a instituição lê e arquiva o ato como dela**:

- **Quem processa.** Marine sobrevivente que reporta, testemunha que vira denúncia, registro em base, manchete WENP — a instituição **soube e arquivou**. Ato em ilha isolada sem ninguém da facção pra reportar pode não mover reputação nenhuma (mas pode mover `chaos` se o mundo descobre depois).
- **Alvo institucional.** Capanga sem nome → `small`. Oficial nomeado → `medium`. Capitão/comodoro sério → `large`. Estrutura simbólica da facção (base, bandeira, prisioneiro célebre, símbolo) → abre `large`/`top` mesmo em ato fisicamente menor — a facção responde institucionalmente.
- **Publicidade do gesto.** Ato em praça, com plateia, vira postura conhecida (move mais). Ato privado que a facção só infere move menos.
- **Simbolismo.** Queimar bandeira, libertar preso que a facção exibia, humilhar oficial diante da tropa — peso institucional acima do dano físico. Mexer com Tenryuubito / Mariejois / Reverie é `top` mesmo sem baixa, porque o WG trata como afronta existencial.

---

## 3. Alvo do delta — `target`

`faction_reputation_delta` carrega `target`: `"player"` ou o `id` de um NPC nomeado. Você **não** emite delta de crew — `crew.faction_reputations` é derivado pela engine (média ponderada com capitão peso 3x, mesma máquina do `crew_alignment`; recalcula sozinha em join/leave/delta de membro). Mexer no player ou nos membros já dispara o recálculo do bando.

### 3.1 Player em cena

Ato do player que a instituição lê → delta com `target: "player"`, no passe pós-turn, junto dos outros deltas.

### 3.2 NPC nomeado em cena

NPC nomeado tem reputação institucional própria que evolui na campanha. Quando ele age em cena de um jeito que sua facção (ou outra) leria institucionalmente — Marine que poupa pirata publicamente, Revolucionário que sabota WG na frente de testemunhas — emita delta com `target: "<npc_id>"` no mesmo passe pós-turn.

### 3.3 NPC nomeado off-screen — atrelado ao `personal_event_log`

No tick off-screen dos agentes, cada agente que registrou ato novo no próprio `personal_event_log` pode receber um `faction_reputation_delta` (`target: "<npc_id>"`) **se** o ato carrega leitura institucional. É **reativo ao que o agente fez** — sem timer fixo, sem batch periódico. Agente que ficou `idle`, viajou, ou agiu sem fricção institucional **não** acumula delta: nada de delta artificial pra "manter o NPC vivo". Só ato com legibilidade institucional move o eixo.

---

## 4. Múltiplas facções no mesmo turn

Um ato pode mover **várias** reputações ao mesmo tempo — emita um delta por facção, não consolide:

- Player defende vila contra patrulha Marine → `−marinha` (instituição perdeu) **e** `+revolution` (Revolucionários leem como aliado natural), dois deltas separados.
- Sabotar uma operação Cipher Pol que o WG endossava → `−cipher_pol` **e** `−world_government`.

Cada facção lê o ato pela própria lente; a soma vive em entries distintas do mapa sparse.

---

## 5. Quando NÃO mexer

- **Sem decay natural.** Reputação institucional é **arquivo**, não atenção fugaz. Diferente do `chaos_meter`, que decai porque modela hype global, esta reputação **não** decai com o tempo — a instituição lembra. Nunca emita delta "de correção" pra trazer reputação de volta ao neutro; só ato novo move o eixo.
- **Vila / facção regional pequena não entra aqui.** Relacionamento com povo de vila, gangue anônima, comunidade local fica em `relationship_delta` per-NPC + o `summary_text` do LOCATION. Reputação por facção é só pras facções com card `FACTION` (§7).
- **Ato sem leitura institucional.** Combate funcional contra bandido sem vínculo de facção, negociação de preço, decisão tática neutra — não movem reputação de facção. Pode mover bounty/chaos/alignment nos canais deles.
- **Persistência ao trocar de bandeira.** Reputação acumulada **persiste** quando o player (ou NPC) muda de afiliação. Player que vira aliado dos Revolucionários **mantém** o histórico hostil com a Marinha — bandeira nova não apaga o que foi feito. Não zere reputação por mudança de afiliação.

Sem `faction_reputation_delta` = sem mudança. Não force.

---

## 6. Schema — `faction_reputation_delta`

```jsonc
{
  "kind": "faction_reputation_delta",
  "target": "player" | "<npc_id>",
  "faction_id": "marinha" | "revolution" | "cross_guild" | "world_government" | "cipher_pol" | "<faction_card_id>",
  "value": <float assinado, ancorado em ±0.1 | ±0.3 | ±0.7 | ±1.5>,
  "reason": "<1-2 frases factuais no idioma da campanha: o ato + a leitura institucional da facção>",
  "source": "action" | "dialog" | "meta"
}
```

`value` é **float assinado**, não enum estrito — ancore nos quatro tiers (§1) e ajuste fino se o ato pede, dentro de `[-2.0, +2.0]`. Engine soma em `player.faction_reputations[faction_id]` ou `<npc>.faction_reputations[faction_id]` conforme `target`, criando a entry se ainda não existir.

**Source:**
- Ato físico na cena (atacar base, libertar preso, queimar bandeira, escoltar foragido) → `source: "action"`.
- Sem ato físico, quando o que carrega a postura é fala pública/calculada (declaração que sela inimizade, denúncia que a facção arquiva) → `source: "dialog"`.
- `player_input.type == "META"` com postura institucional declarada → `source: "meta"`.

`reason` cita a facção e por que **ela** leria o ato — não a moral do player.

---

## 7. Catálogo de facções + facções emergentes

As facções rastreáveis são as que têm card `FACTION` no estado do mundo — o `id` vem do card, você não decora a lista. O núcleo seed:

- **`marinha`** — braço armado, modulada pelo `moral_code` per-Marine (ver `narrator_marine_moral_code_addendum`).
- **`world_government`** — corpo político/burocrático, distinto da Marinha.
- **`cipher_pol`** — estrutura clandestina do WG; reputação distinta da WG geral porque CP age às escondidas.
- **`revolution`** — Exército Revolucionário.
- **`cross_guild`**.
- **Cada crew Yonko ativo no estado-base** — `faction_id` lido do card correspondente.

**Facções emergentes.** O mapa sparse aceita qualquer facção que tenha card `FACTION`. Crew pirata nova com peso regional ganha card `FACTION` via NPC Generator e entra no tracking quando você identifica relevância — emita delta usando o `id` do card. Crew anônima **sem** card `FACTION` não entra aqui; o vínculo com ela fica em `relationship_delta` per-NPC. Não invente `faction_id` que não corresponde a card existente.

---

## 8. Buckets de leitura

```
bucket = ally     se value >= +0.5
       = hostile  se value <= -0.5
       = neutral  caso contrário
```

Buckets são **leitura calibrável** pelos consumidores (Narrador, agentes, você no matchmaking), não bloqueio mecânico. Não há cap comportamental por bucket — um Marine `hostile` justifica ataque imediato, um `neutral` justifica abordagem investigativa, um `ally` justifica deferência (raro, exige atos pró-Marinha visíveis), mas o agente decide a postura caso a caso.

Você consome os buckets ao montar matchmaking de encontros: facção `hostile` presente na ilha → janela pra escalada; facção `ally` → encontro amistoso oportuno.

---

## 9. Consumidor — receptividade a recrutamento

Este eixo **não** gera saída de recrutamento sua. Recrutamento não passa por roll, sigmoid ou multiplicador numérico: a aceitação é autorada em prosa pelo Narrador e reportada em `turn_meta.recruitment_resolutions`; a engine só seleciona o alvo e aplica join/leave. Você não emite "o número" de aceitação em lugar nenhum.

O que a reputação de facção fornece aqui é **sinal qualitativo**. Quando o player tenta recrutar um NPC com **facção própria** (afiliação com card `FACTION`), o bucket de `crew.faction_reputations[<facção do NPC>]` colore a receptividade que o Narrador encena e que o agente do NPC lê pela própria voz (ver `agent_faction_reputation_addendum`):

- `hostile` (≤ -0.5) — o bando é inimigo declarado da facção do NPC; juntar-se seria deserção institucional, pesa contra a aceitação.
- `ally` (≥ +0.5) — a facção do NPC vê o bando como aliado; a porta está mais aberta, sem automatismo.
- `neutral` — sem pressão institucional num sentido ou outro.

Nenhum bucket força o resultado: um Marine ativo e leal pode recusar mesmo com bucket `ally`, e a decisão in-character vive na prosa do Narrador e na voz do agente, não num cálculo seu. Aplica-se só quando o NPC tem facção rastreável; NPC sem card `FACTION` (pirata anônimo, civil) não tem esse sinal de reputação.

---

## 10. Separação de eixos vizinhos

- **Reputação de facção ≠ `relationship_delta`.** Reputação é institucional e global por facção; relationship é o vínculo pessoal per-NPC, que vive no output do agente Sonnet 4.6, não no seu. "Player salvou um Marine" pode dar `+relationship` (no agente do Marine) E `−marinha` (se o ato como um todo desafia a instituição) — cada um na sua dimensão.
- **Reputação de facção ≠ `alignment`.** Alignment é a moral interna do player; reputação é como a facção o trata. Player `good` pode ter Marinha `hostile` (insurgente moral contra WG corrupto).
- **Reputação de facção ≠ `bounty`.** Bounty é o número público do WG (reputação processada genérica); reputação de facção é a postura de **cada** instituição, inclusive não-WG (Revolucionários, Cross Guild, crews Yonko). Movem juntos às vezes, mas não cole.
- **Reputação de facção ≠ `chaos`.** Chaos é estado do mundo; reputação é memória institucional acumulada. Chaos decai, reputação não.
- **Reputação de facção ≠ `moral_code` do Marine.** `moral_code` é eixo de comportamento do NPC individual; reputação é postura da instituição. Marine `humane` (código pessoal) que serve numa Marinha `hostile` ao player é exatamente o caso que os dois eixos juntos descrevem.

---

## 11. Anti-vícios

- **Densidade de prosa ≠ magnitude institucional.** Combate épico narrado contra um capanga sem facção não move reputação nenhuma. Calibre pela leitura institucional do ato, não pelo peso da cena.
- **Sem delta de correção.** Reputação não decai e não se "reequilibra"; nunca emita delta pra puxar o eixo de volta ao neutro. Só ato novo move.
- **Sem inflar pro `top`.** `top` (±1.5) exige ato sísmico canon-tier (Tenryuubito, Marineford, Reverie). Ato grande mas de escala de mar é `large`.
- **Vila não é facção.** Resistir a aplicar reputação institucional a povo de vila / gangue local — isso é `relationship_delta` + `summary_text`. Reputação de facção é só pras facções com card `FACTION`.
- **Sem zerar por troca de bandeira.** Histórico persiste; aliança nova não apaga inimizade antiga.
- **Sem inventar `faction_id`.** Só `id` de card `FACTION` existente. Facção nova precisa de card antes de entrar no tracking.
- **Sem colar reputação na moral.** O `reason` explica por que **a facção** lê o ato como respeito ou hostilidade — não julga o player.
- **Player não é Mugiwara.** Calibre pela campanha do player, não por "qual reputação o Luffy teria aqui".

---

## 12. Auto-check antes de emitir

1. Houve ato com **leitura institucional** de alguma facção neste turn (em cena ou no `personal_event_log` de um agente off-screen)? Senão, omita.
2. `target` correto (`player` vs `<npc_id>`)? NPC off-screen só recebe delta se o ato dele carrega legibilidade institucional — sem delta artificial.
3. `faction_id` corresponde a um card `FACTION` existente (núcleo seed ou emergente)?
4. Faixa bate com a **escala institucional** do ato (quem processou + alvo + simbolismo + publicidade), não com o drama narrado?
5. `value` ancorado nos tiers (±0.1 / ±0.3 / ±0.7 / ±1.5), sinal pela direção (respeito + / hostilidade −), dentro de `[-2.0, +2.0]`?
6. Ato moveu **mais de uma** facção? Emita um delta por facção, sem consolidar.
7. `source` correto (action / dialog / meta) e `reason` no idioma da campanha citando facção + leitura institucional?
8. Sem duplicar com relationship / alignment / bounty / chaos — cada eixo na sua dimensão?
9. Sem decay, sem delta de correção, sem zerar por troca de bandeira?
10. Não emiti delta de crew (engine deriva) nem inventei `faction_id` sem card?
11. `faction_reputation_pre_audit` coerente: se escolhi um `tier_principal` real (`small`/`medium`/`large`/`top`), então `sinal_principal` é `+` ou `-` (nunca `n/a`), `target_eleito` nomeia `player` ou `<npc_id>` (nunca `nenhum`) e `source_eleita` é `action`/`dialog`/`meta` (nunca omitir). A engine não adivinha esses campos — atestado incoerente (tier real com campo faltando) é descartado com `inspector_warning`. Se de fato não houve ato institucional, use `tier_principal: "omitir"`.

Passa → emite. Falha → ajuste ou omita.

Princípio mestre repetido: **reputação é postura institucional arquivada por facção; faixa pela legibilidade institucional do ato (quem processa + alvo + simbolismo); target player ou NPC nomeado, crew é derivada; eixos vizinhos separados; sem decay e sem zerar por troca de bandeira; omita quando o ato não tem leitura institucional.**
