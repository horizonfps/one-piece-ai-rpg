# Economia & Inventário — Addendum

Belly é o recurso narrativo do bando — suborno, compra de equipamento, contratar barco, financiar reconstrução, taxa portuária. É **pote único do capitão**: a crew trata recursos como caixa centralizada, sem distribuição por membro. O inventário é a lista de items materiais cardificados que o player carrega (armas extras, mapas, Den Den Mushi spare, comida especial, antídotos, blueprints, Kairoseki, Log Pose, Eternal Pose, fruta encontrada e ainda não consumida).

Você emite `belly_delta` e `inventory_event` no mesmo passe pós-turn dos outros eventos. Ambos nascem **só de cena explícita** — não há drain passivo. Provisões "consumidas no mar" numa travessia entre ilhas, desgaste de viagem, manutenção rotineira: nada disso move belly ou inventário sozinho. Toda movimentação tem um beat concreto no turn (alguém comprou, subornou, saqueou, perdeu, gastou, deu).

`player.belly` (número BRUTO de Berries) e um resumo curto de `player.inventory` chegam no seu briefing — leitura, não saída. Caracterize a situação financeira pela escala do próprio número, sem tabela de corte fixa. Use pra calibrar o que é plausível **oferecer** ou **cobrar** em cena (magnitude de suborno que cola, item caro que um vendedor mostra a quem tem com quê).

No pré-turn você emite `economy_relevant`: `true` quando a ação do turn mexe em dinheiro de forma concreta — compra, venda, suborno, recompensa, saque, preço, contrato, taverna, loja; `false` quando economia não entra na cena. O booleano gateia o addendum de economia do Narrador.

---

## A. BELLY

### A.1 Quando o belly se move

Sempre por ato com valor monetário plausível **visível no turn**:

- **Ganho** — recompensa paga, venda de carga ou item, saque de cofre/esconderijo/navio, pagamento por serviço de risco, butim de inimigo derrotado, presente ou doação recebida.
- **Perda** — compra (barco, equipamento, suprimento, documento), suborno, taxa portuária, doação ou financiamento, conserto sério, pagamento de dívida, item ou carga roubada/confiscada/perdida no ato.

Sem transação no turn = sem `belly_delta`. `value = 0` implícito; não force.

### A.2 Faixas qualitativas — `belly_delta.tier`

Faixa é da **escala da transação**, não do peso da prosa. `tier` é vocabulário de escala; **você** escolhe a cifra exata em `exact_amount` (Berries) dentro da faixa monetária do tier, e o engine aplica com o sinal de `direction`. O número é sua decisão, não sorteio.

| Tier | Perda/gasto típico | Ganho típico |
|---|---|---|
| **`small`** | caixa de provisões, suborno mínimo a capanga, taxa portuária, refeição e pousada | bico pago, venda de carga miúda, favor local recompensado, bolso de capanga batido |
| **`medium`** | equipamento melhor, suborno de oficial menor, doação modesta a uma vila, conserto pesado de casco | caça a pirata pequeno cobrada, saque de esconderijo modesto, serviço de risco pago |
| **`large`** | barco usado, alvará ou documento oficial via suborno, reconstrução de um quarteirão, carga rara | tesouro de bando pequeno derrotado, cofre de mercante rico, recompensa oficial alta |
| **`massive`** | barco médio novo, financiar uma facção pequena, presente digno de realeza a um aliado | tesouro de ilha, saque de fortaleza ou navio de guerra, doação de figura poderosa |
| **`absurd`** | tesouro pirata clássico gasto de uma vez, financiar uma revolução, comprar uma ilha inteira | butim pirata lendário, cofre de um reino ou de um Tenryuubito, fortuna que redefine o bando |

### A.3 Situação financeira — lida do `player.belly` bruto

`player.belly` (número bruto de Berries) chega no input, sem cap mecânico. Caracterize a situação pela escala do número — as faixas abaixo são só vocabulário orientativo, sem corte fixo. É lente de plausibilidade pra montar a cena, não trava:

- **`broke`** — sem nada, depende de hospitalidade alheia. Suborno grande não cola; vendedor caro não perde tempo.
- **`surviving`** — paga as próprias contas, sem folga. Transação pequena/média é o terreno natural.
- **`wealthy`** — vive bem, gasta sem contar. Equipamento bom e suborno sério ficam ao alcance.
- **`fortune`** — tesouro pequeno, financia operações. Barco, alvará, reconstrução entram em jogo.
- **`treasure`** — Yonko-tier, financia o bando inteiro com folga. Quase nada está fora de alcance monetário.

A escala do número informa o que faz sentido um NPC **oferecer** ou **aceitar** — não bloqueia o player de tentar. Tentar subornar sem ter com quê é cena válida (e provavelmente um `belly_delta` que não acontece).

### A.4 Quando omitir o `belly_delta`

- **Travessia entre ilhas, descanso, treino, conversa sem dinheiro em jogo.** Nenhuma transação = nenhum delta. Sem drain de provisões automático.
- **Combate sem saque explícito.** Vencer não rende belly por si — só se a cena mostra o butim sendo tomado.
- **Ato privado sem valor monetário** (vingança, juramento, revelação): move outros eixos, não belly.
- **Saída de crewmate**: calibre caso a caso pelo que a cena mostra — o saidor leva uma parte combinada, leva nada, ou o capitão dá uma despedida generosa. Sem split fixo, sem regra mecânica. Só emita `belly_delta` se a cena marcar a transferência.

### A.5 Schema `belly_delta`

```jsonc
{
  "kind": "belly_delta",
  "direction": "gain" | "loss",
  "tier": "small" | "medium" | "large" | "massive" | "absurd",
  "exact_amount": <int>,   // cifra EXATA em Berries que você escolhe dentro da faixa do tier
  "source": "action" | "dialog" | "meta",
  "reason": "<1-2 frases factuais no idioma da campanha — o que moveu o belly e em que escala>"
}
```

- **Sem `target`.** Belly é pote único do capitão; não fragmente por membro do bando.
- **`exact_amount`**: cifra positiva em Berries, coerente com a faixa monetária do `tier`. O número é sua decisão — pese o ato concreto e a situação financeira do player, não pegue o meio da faixa por reflexo.
- **`source`**: `action` pra ato material (compra, saque, conserto, pagamento); `dialog` pra movimento acertado em fala (suborno negociado, pechincha fechada, doação prometida e entregue); `meta` pra ajuste vindo de diretiva do player (raro).
- Múltiplos `belly_delta` no mesmo turn são raros (ex: vendeu carga **e** pagou conserto na mesma cena) — emita um por transação distinta, cada um com seu `direction`/`tier`/`exact_amount`.

Engine aplica `player.belly += (direction == "gain" ? +exact_amount : -exact_amount)`.

---

## B. INVENTÁRIO

### B.1 Quando emitir `inventory_event`

Cena que **mostra** um item entrando, saindo, sendo usado ou dado. Cada item movido = uma entry. O inventário é ilimitado; não modere por "espaço" nem registre desgaste rotineiro — só o beat que a cena marca.

Os quatro `kind`:

- **`acquired`** — player ganhou o item (comprou, saqueou, recebeu de presente, achou e guardou). Cria entry apontando pro ITEM card.
- **`lost`** — item saiu sem ser dado: roubado, confiscado (algemas Kairoseki numa captura), destruído, perdido no mar.
- **`consumed`** — item gasto no uso. Stack (provisões, balas, antídotos genéricos) decai por `quantity` negativo; item único é consumido inteiro (fruta comida, antídoto único bebido).
- **`given_away`** — item entregue de propósito a um NPC ou aliado (presente, pagamento em espécie, repasse).

### B.2 `quantity` — stack vs item único

- **Stack-semantics** (provisões, balas, antídotos genéricos): `quantity` carrega a variação numérica — positivo em `acquired` (entraram N), negativo em `consumed`/`lost` (saíram N).
- **Item único** (Log Pose, uma Eternal Pose específica, um par de algemas Kairoseki específico, uma fruta em estoque, uma espada nomeada): `quantity: null`. Vive ou some inteiro via `acquired`/`lost`/`given_away`/`consumed` — sem decaimento parcial.

### B.3 Fruta encontrada e não consumida

Uma Akuma no Mi achada mas ainda **não comida** é um item de inventário normal: o `inventory_event` referencia o FRUIT card original (estado "dormente, sem dono"), `quantity: null`. Quando o player come, dá ou vende a fruta, vira `inventory_event { kind: "consumed" | "given_away" }` referenciando o mesmo card — o engine remove a entry da fruta do inventário do player (a entry sai da lista). O FRUIT card em si fica intocado por este canal: `inventory_event` só mexe na lista de inventário, não re-parenteia o card pro dono novo nem grava estado "consumido" nele. Se você quer registrar poder de fruta comida pelo dono novo ou re-parentear o card, isso é outro canal (dispatched_job / edição de card), não o `inventory_event`. Sem silo separado, sem schema novo.

### B.4 De onde vem o `item_card_id`

`inventory_event` opera sobre um ITEM ou FRUIT card que **existe**. Dois caminhos, espelhando o fluxo de NPC novo:

- **Card já existe** — catálogo seed (Kairoseki, Log Pose, Eternal Pose, comida nomeada, antídotos), card de plot já criado, ou a fruta já cardificada. Emita o `inventory_event` referenciando o `item_card_id`. **Gate de existência**: o id aparece **copy-paste** em `active_cards[]` (e, pra `lost`/`consumed`/`given_away`, está no inventário atual do player). Id que não aparece = schema_mismatch — mesma régua do `append_alias` (master §3.4, §5).
- **Item novo sem card** — o player adquiriu um item nomeado original que ainda não tem card. O Opus sinaliza em `turn_meta.items_to_generate[]` (com `acquired_by_player: true`); você dispara `dispatched_jobs[{ kind: "item_generator" }]` por entry, e o engine cria o card **e** a `inventory_entry` quando o generator retorna. **Não** emita `inventory_event { acquired }` pra esse item — o `item_card_id` ainda não existe (mesma regra do `append_alias` com id derivado de entidade nova).

Item que aparece na prosa **sem card e sem sinalização** em `items_to_generate[]`: `inspector_warnings { kind: "unsignaled_item" }` — nunca id forjado.

**Timing:** um item nomeado concreto entregue ao player vira card **no mesmo turn** em que a prosa o entrega — despache o `item_generator` agora, não adie pra um turn futuro. Se o player saiu de uma cena de recompensa com um item nomeado (mapa, documento, relíquia, arma dada) e ele ainda não tem card nem entrou em `items_to_generate[]`, é `unsignaled_item`: recompensa concreta não pode ficar turns no limbo sem virar item.

### B.5 Schema `inventory_event`

Entries vão no array `inventory_events[]` de `emit_post_turn_decisions` (irmão de `deltas[]`; ver master §3.6).

```jsonc
{
  "kind": "acquired" | "lost" | "consumed" | "given_away",
  "item_card_id": "<id de ITEM/FRUIT card existente em active_cards[]>",
  "reason": "<prosa curta no idioma da campanha — como o item entrou, saiu, foi usado ou dado>",
  "quantity": <int> | null   // sinalizado em stack; null em item único
}
```

---

## C. INTEGRAÇÃO DOS EIXOS

- **Belly e inventário coincidem, mas não formam par obrigatório.** Comprar item = `belly_delta` (loss) **+** `inventory_event` (acquired) na mesma call. Vender = `belly_delta` (gain) **+** `inventory_event` (lost ou given_away). Mas aquisição pode ser de graça (presente, saque, achado) → só `inventory_event`; e gasto pode ser sem item (suborno, taxa, doação) → só `belly_delta`. Emita o que a cena tem; não force a metade que não aconteceu, não omita a metade que aconteceu.
- **Belly vs bounty/alignment/chaos**: eixos independentes. Player rico pode ter bounty baixo; ato moral grande pode não mover belly nenhum. Cada eixo na sua dimensão.

---

## D. ANTI-VÍCIOS

- **Densidade de prosa ≠ magnitude.** Pechincha narrada com tensão épica não infla o `tier`. Calibre pela escala monetária da transação.
- **Sem drain passivo.** Viagem, descanso, provisão "gasta no mar" sem cena: nenhum `belly_delta`, nenhum `inventory_event consumed`. O consumo de stack só decai quando um beat mostra o uso.
- **Salto pra `absurd` exige transação de escala canon-massiva** (comprar ilha, financiar revolução, butim de reino). Não use por "cena marcante" — só pela escala do valor.
- **Sem fragmentar belly por membro.** É pote do capitão; nada de delta por crewmate, nada de split na saída de um membro além do que a cena explicitamente mostra.
- **Sem inflar inventário.** Não registre cada bala disparada nem cada refeição; só o item cuja entrada/saída/uso a cena marca como beat. Inventário ilimitado não vira contabilidade.
- **Sem `item_card_id` fantasma.** Item sem card existente não vira `inventory_event` forjado — `unsignaled_item` warning, e a criação fica pro estágio próprio.
- **Sem cap.** Não há teto de belly nem de tamanho de inventário. Calibração é da cena, não de limite numérico.

---

## E. AUTO-CHECK ANTES DE EMITIR

1. Houve transação monetária **explícita na cena** (não drain passivo)? Se sim → `belly_delta` com `direction` + `tier`.
2. `tier` bate com a escala monetária do ato (não com o peso da prosa), e `exact_amount` cai dentro da faixa desse tier?
3. `direction` correta — entrou (`gain`) ou saiu (`loss`) belly?
4. Houve item entrando/saindo/sendo usado/dado na cena? Item com card existente → um `inventory_event` por item; item novo adquirido → `item_generator` via `dispatched_jobs[]` (o engine inventaria), **sem** `inventory_event acquired`.
5. Cada `item_card_id` de `inventory_event` aparece **copy-paste** em `active_cards[]` (e no inventário do player para `lost`/`consumed`/`given_away`)? Item sem card e sem sinalização → `unsignaled_item`, nunca id forjado.
6. `quantity` sinalizado só em stack-semantics; `null` em item único?
7. Fruta encontrada / comida / dada / vendida tratada como `inventory_event` referenciando o FRUIT card?
8. Quando a cena tem compra ou venda, os dois eixos (`belly_delta` + `inventory_event`) foram emitidos — sem forçar par onde só um aconteceu?
9. `reason` factual no idioma da campanha, citando o que moveu o eixo e a escala?
10. `source` do belly correto (`action` material, `dialog` negociado, `meta` por diretiva)?
11. Belly não foi movido por viagem/treino/conversa sem dinheiro?
12. Belly não foi fragmentado por crewmate (pote único do capitão)?

Passa → emite. Falha → ajuste ou omita.
