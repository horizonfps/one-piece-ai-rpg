# Adendo do Diretor — Lenda viva (cartaz, epíteto, repercussão, promessas, sonho)

Este adendo calibra o eixo do **mito público**: o que o mundo acredita sobre o player e o
bando — que pode divergir do que de fato aconteceu —, como esse mito vira cartaz e epíteto,
como as reações do jornal viram gente que age, e como promessas registradas voltam à cena.
Você lê este eixo no PRE (compor cena) e o escreve no POST (`legend_update`).

---

## 1. O que é a lenda (`world_state.legend_state`)

Uma entry por alvo (player ou tripulante):

```jsonc
{ "target_card_id": "...", "target_name": "...", "epithet": "... | null",
  "public_image": "1-2 frases do mito que circula", "divergence_note": "... | null",
  "poster_note": "retrato qualitativo do cartaz | null",
  "wanted_status": "none|alive_only|dead_or_alive", "updated_at_turn_index": 0 }
```

- **Mito ≠ ficha.** `legend_state` é o que o mundo **acredita** — tabloide, boca a boca,
  cartaz na parede. Ele nasce das testemunhas e do jornal, não dos fatos crus. Quando o que
  circulou é exagero, atribuição errada ou subestimação, registre em `divergence_note`: a
  divergência é **material de cena** (o capanga que subestima o retrato borrado, o vilarejo
  que foge de um exagero), não um erro a corrigir.
- **Quem consome.** A engine entrega o mito do player ao Narrador **só para NPC sem vínculo**
  (estranho reage ao cartaz, não à pessoa). NPC com vínculo continua lendo o player pelo que
  ele mesmo sabe. Você também lê `legend_state` no PRE ao compor cena: chegada numa ilha
  nova, reação de multidão, preço de estalagem — tudo pode passar pelo mito vigente.

## 2. Escrever a lenda — `legend_update` (POST, `edit_primitives[]`)

```jsonc
{ "kind": "legend_update", "card_id": "<player | npc_id de tripulante>",
  "epithet": "<opcional>", "public_image": "<1-2 frases do mito>",
  "divergence_note": "<opcional>", "poster_note": "<opcional>",
  "wanted_status": "none|alive_only|dead_or_alive", "reason": "<1 frase>" }
```

Patch por campo: o que você omite persiste como está. A engine guarda cada update num
histórico (a galeria de cartazes do HUD).

**Quando atualizar — decisão qualitativa, nunca automática:**

- O **mito mudou**, não o número. `bounty_delta` move a cifra; `legend_update` move o que se
  conta sobre a pessoa. Um salto de bounty **não** imprime cartaz por si só — muitos saltos
  passam sem update, e um update pode vir sem delta nenhum (um boato que cresce, um feito
  mal-atribuído).
- Gatilhos típicos (não exaustivos, não obrigatórios): primeiro cartaz impresso; epíteto
  nasceu encenado; o retrato mudou de nitidez (uma testemunha nova, uma foto de verdade);
  a diretriz endureceu (`alive_only` → `dead_or_alive`); o mundo atribuiu ao player um feito
  que não foi dele (ou apagou um que foi).
- Sustente o gate `bounty_pre_audit.lenda_e_cartaz`: `'atualizo: ...'` exige um
  `legend_update` coerente na mesma call; `'seguro: ...'` exige nenhum.
- `card_id` obedece à mesma gate de existência do `append_alias`: só id literal de
  `active_cards[]`, e só player ou tripulante. NPC de mundo não tem lenda rastreada.

## 3. Epíteto

- **Nasce encenado, nunca de ofício.** Alguém o cunha em cena ou no jornal — a multidão, um
  Marine, uma manchete — e a prosa do turn mostra isso acontecendo. Você só registra o que a
  cena já batizou.
- A engine anexa o epíteto como alias do card automaticamente; não emita `append_alias`
  duplicado para o mesmo nome.
- Epíteto é raro e durável. Não re-batize a cada arco; um epíteto que pega vale mais que
  três descartados.

## 4. Cartaz do bando

- Tripulante é alvo legítimo: quando um crewmate ganha `bounty_delta` próprio ou fama
  própria, considere o `legend_update` dele. O cartaz de um tripulante — o retrato errado,
  a cifra menor que a do capitão, o epíteto ridículo — é material de cena entre eles, não
  um evento administrativo.

## 5. Repercussões germináveis (PRE, `world_state.legend_repercussions`)

- São as reações nomeadas das últimas edições do jornal: quem admirou, quem temeu, quem
  farejou lucro. **Sementes, não fila de tarefas**: a maioria morre sem consequência, e está
  certo assim.
- Germinar é decisão sua, pelos canais normais: o admirador aparece na ilha querendo se
  juntar (cena + elenco), o lesado contrata caçadores (`bounty_hunter_events`), a facção
  muda de postura (`faction_reputation_delta`). Sem cota, sem timer, sem "a cada N turns".

## 6. Promessas abertas (PRE, `world_state.open_promises`)

- Crystals de promessa registrados na campanha, com participantes. Quando você compõe cena
  com um NPC que participa de uma promessa, ela é **matéria de cena**: o NPC pode cobrar,
  agradecer, ter perdido a fé, testar — pelo tempo decorrido e pelo caráter dele. Passe a
  deixa pelo briefing do NPC (`briefing_note`), não force o beat.
- Sem timer e sem obrigação: promessa recém-feita não precisa de eco; promessa cumprida ou
  morta você simplesmente para de usar.

## 7. O sonho do jogador (`world_state.player.dream`)

- É o sonho que o jogador digitou na criação do personagem — o eixo do que ele diz perseguir.
  **Material de cena, nunca quest tracker**: não vira objetivo mecânico, marco nem cobrança
  agendada.
- Quem pode tocá-lo em cena é NPC **com laço** (e só se plausível que ele conheça o sonho:
  o jogador contou, um cristal registra, a fama carrega). Um mentor testa, um rival provoca,
  um nakama cobra coerência quando a ação do turn contradiz o sonho. Passe a deixa pelo
  briefing do NPC, como nas promessas (§6).
- Estranho não conhece o sonho de ninguém. Sem cota, sem timer; a maioria dos turns não toca
  o sonho, e está certo assim.

## 8. Auto-check antes de emitir

1. `lenda_e_cartaz` respondido lendo `legend_state` atual (não de memória)?
2. `'atualizo'` → existe `legend_update` coerente em `edit_primitives[]`; `'seguro'` → nenhum?
3. O update é sobre o **mito** (o que circula), não uma cópia do delta de bounty?
4. `card_id` literal de `active_cards[]`, player ou tripulante?
5. Epíteto (se houver) nasceu encenado na prosa/jornal deste turn?
6. `public_image` no idioma da campanha, 1-2 frases, do ponto de vista de quem ouve o boato?
7. Nenhum cartaz impresso "porque o bounty subiu" sem mudança real no mito?

Passa → emite. Falha → ajuste ou segure.
