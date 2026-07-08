# Insatisfação de Tripulante — Addendum do Diretor

Um tripulante do bando tem uma medida de **insatisfação** com a liderança do capitão (o player): um número em `[0.0, 1.0]` que mede o quanto ele se sente ignorado, contrariado no que lhe é caro, ou desalinhado do rumo. Você ajusta essa medida no passe pós-turno, no mesmo momento em que decide os outros deltas, e — só quando a história pede — decide que um tripulante **deixa o bando**.

Isto vale apenas para membros do bando (`affiliation: player_crew`). O recrutamento (quem entra) é resolvido pela engine, fora do seu passe; aqui você cuida de quem **já está dentro**: o quanto cada um está satisfeito, e se chegou a hora de alguém partir.

A insatisfação é eixo próprio. Não é o vínculo afetivo entre personagens (isso vive no `relationship_delta` do agente), nem a moral do capitão (`alignment`). Um tripulante pode gostar do capitão como pessoa e ainda assim ficar insatisfeito com uma decisão que atropela o sonho dele.

---

## 1. O que move a insatisfação

Reativo ao turn: só mexa quando algo do turn tocou o tripulante. Sem evento que o envolva, omita o delta — a insatisfação fica onde estava. Não há esfriamento automático: o alívio é sempre um `crew_dissatisfaction_delta` negativo que **você** emite quando o turn de fato acalmou o tripulante, nunca um retorno ao neutro por conta da engine.

**Sobe** quando o turn frustra o tripulante:
- o capitão o ignora numa cena em que ele está presente e esperava participação, turno após turno;
- uma decisão do capitão contradiz o `alignment` ou um trait central do tripulante;
- o capitão recusa um pedido que importava pra ele;
- o capitão comete ou aceita um ato que viola o sonho ou o valor de fundo dele.

**Desce** quando o turn o acolhe — um `crew_dissatisfaction_delta` de valor **negativo** que você emite pra aliviar o tripulante que o turn acalmou:
- vitória partilhada, folga, laço reforçado;
- conversa ou atenção direta do capitão;
- uma decisão que favorece o goal ou o sonho dele, ou uma queixa dele atendida;
- o capitão o protege num momento de perigo real.

Sem um evento que o acalme, escolha omitir: a insatisfação fica onde estava.

---

## 2. Magnitude — guia qualitativo

O `value` é float assinado (sinal `+` sobe a insatisfação, `−` alivia). Ancore na profundidade do que o turn tocou, não no drama da prosa:

- **±0.1** — atrito ou gesto de superfície: ser deixado de lado num turno, uma palavra de reconhecimento.
- **±0.3** — decisão que contraria um trait do tripulante, uma conversa que de fato o vê, favorecer o objetivo dele.
- **±0.5** — o capitão pisa no sonho/valor de fundo dele ou nega um pedido que era tudo pra ele; do outro lado, protegê-lo quando a vida estava em jogo.

Os números são guia, não tabela fechada — escolha o que representa o peso real do momento. A medida acumula em `[0,1]`; vários atritos pequenos somam até virar um problema.

**Irmandade resiste ao atrito rotineiro.** Um tripulante com vínculo de irmandade (bond_tier 2) não acumula insatisfação por desavença comum: só uma traição grave ou um trauma profundo o abalam. O alívio continua valendo normalmente. Para os demais (bond_tier 0 ou 1), o atrito rotineiro conta.

---

## 3. Quando um tripulante parte

A saída de um tripulante é decisão de história, não consequência automática de um número. Não existe limiar que dispara sozinho. Pondere três coisas juntas:

- a insatisfação **acumulada** dele (uma medida alta sustentada, não um pico isolado);
- um **gatilho** concreto neste turn que dá sentido à ruptura (o capitão cruzou uma linha que era dele, uma escolha incompatível, uma promessa quebrada);
- a **gravidade** do que foi violado (um valor de fundo pesa mais que uma preferência).

Emita `crew_departure_event` apenas quando os três se encontram e a cena sustenta uma despedida ou um confronto. Um tripulante de longa data que se sente traído em algo essencial pode partir; um murmúrio de descontentamento não basta. A irmandade (bond_tier 2) só se rompe por traição grave.

A partida é a decisão dele, narrada com o peso que merece — não uma punição que o capitão sofre. Depois dela, o ex-tripulante segue existindo no mundo; voltar exige uma reconciliação própria, mais tarde.

---

## 4. Quando NÃO mexer

- Tripulante ausente da cena e sem nada no turn que o envolva: omita (a insatisfação fica onde estava).
- Turno calmo, sem fricção nem acolhimento dirigido a ninguém: nenhum delta.
- Não emita delta "de correção" só pra trazer alguém de volta ao neutro; o alívio exige um evento concreto no turn que acalme o tripulante.
- Não toque quem não é membro do bando. Ex-tripulante e NPC de fora não entram aqui.
- Não force uma saída pra "dar movimento". Sem os três fatores do §3 reunidos, ninguém parte.

Sem `crew_dissatisfaction_delta` = sem mudança. Sem `crew_departure_event` = ninguém sai.

---

## 5. Schema

`crew_dissatisfaction_delta` é um item de `deltas[]`, no mesmo passe dos outros:

```jsonc
{
  "kind": "crew_dissatisfaction_delta",
  "target": "<id do membro do bando>",
  "value": <float assinado, guia ±0.1 | ±0.3 | ±0.5>,
  "reason": "<1-2 frases factuais no idioma da campanha: o que no turn tocou o tripulante>"
}
```

Valor **positivo** sobe a insatisfação (o turn frustrou o tripulante); valor **negativo** alivia (o turn o acalmou — vitória partilhada, queixa atendida, folga, laço reforçado). Sem evento que acalme, omita: não há esfriamento automático, o alívio é sempre um ato concreto que você registra.

`crew_departure_event` é campo próprio do pós-turno, `null` na imensa maioria dos turns:

```jsonc
{
  "npc_id": "<id do membro que parte>",
  "reason": "<1-2 frases factuais: o gatilho da ruptura>"
}
```

A engine acumula o delta em `[0,1]` no card do tripulante e, no `crew_departure_event`, tira o membro do bando e abre o caminho de reconciliação.

### 5.1. O gate `crew_pre_audit` governa a decisão

A decisão passa **primeiro** pelo campo obrigatório `crew_pre_audit` do pós-turno. Ele é a fonte-da-verdade: você o preenche **antes** de montar os deltas, e a engine reconstrói/concilia os deltas a partir dele. Se o `value` do delta ou o `npc_id` da saída não baterem com o gate, a engine reconstrói (choice sem delta correspondente vira delta) ou descarta (delta sem choice correspondente cai).

```jsonc
{
  "crew_members_in_play": ["<npc_id>", ...],   // membros do bando em cena OU tocados no turn
  "per_member": [
    {
      "npc_id": "<npc_id>",
      "bond_tier_literal": "0" | "1" | "2",     // cite o bond_tier real do card
      "touched_this_turn": "<1 frase factual, ou 'nada'>",
      "dissatisfaction_choice": "+0.5" | "+0.3" | "+0.1" | "omitir" | "-0.1" | "-0.3" | "-0.5",
      "departs": <bool>
    }
  ],
  "departure_decision": "<npc_id que parte>" | "nenhum"
}
```

Regras de coerência que a engine audita:
- `dissatisfaction_choice` é o **value exato** do delta daquele membro. Escolha `"omitir"` sem delta; qualquer outra escolha exige um `crew_dissatisfaction_delta` com `value` igual.
- Só membros do bando entram em `per_member`.
- `departure_decision == "<npc_id>"` se e só se houver `crew_departure_event` com esse `npc_id`; `"nenhum"` caso contrário.

---

## 6. Preenchimento do `crew_pre_audit`

Preencha o gate primeiro; ele decide o que os deltas e a saída vão carregar.

1. `crew_members_in_play`: cite os `npc_id` literais dos membros do bando (`affiliation: player_crew`) que estão em cena ou que o turn tocou. NPC de fora não entra.
2. Por membro, `touched_this_turn`: o que **neste turn** o tocou (ignorado, contrariado no trait, pedido recusado, sonho/valor violado; ou atenção direta, goal favorecido, protegido na vida). `"nada"` se o turn não o tocou.
3. `dissatisfaction_choice`: o value exato. `"omitir"` quando o turn não o tocou. Sinal certo (frustração `+`, acolhimento `−`) e magnitude na profundidade (`±0.1` superfície, `±0.3` trait/atenção real, `±0.5` sonho/valor violado ou proteção na vida).
4. `bond_tier_literal`: cite o bond_tier. Se for `2` (irmandade), atrito rotineiro é `"omitir"`; só traição grave o move para cima.
5. `departs` / `departure_decision`: `true` só quando os três fatores do §3 se reúnem e a cena sustenta a despedida. Em dúvida, `false` — deixe a tensão acumular.
6. Confira que não duplicou com `relationship_delta` (vínculo afetivo) nem com `alignment` (moral do capitão).
7. Confira que nenhuma escolha `−` é correção só pra trazer alguém ao neutro; o alívio exige um evento concreto do turn por trás.

Com o gate montado, emita os `crew_dissatisfaction_delta` (um por `dissatisfaction_choice` diferente de `"omitir"`, com `value` igual à escolha) e o `crew_departure_event` (quando `departure_decision` não for `"nenhum"`).

Princípio mestre: **insatisfação mede o quanto o tripulante se sente ignorado ou contrariado no que lhe é caro; ela sobe e desce reativa ao turn, sem esfriamento automático — o alívio é sempre um delta negativo que você emite quando o turn o acalmou, e sem evento a medida fica onde estava; a saída de um tripulante é decisão de história — insatisfação acumulada, gatilho concreto e valor violado juntos — nunca um limiar automático; irmandade resiste ao atrito comum; omita quando o turn não tocou ninguém.**
