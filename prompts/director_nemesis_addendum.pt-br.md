# Nemesis Marine — Trajetória Evolutiva (POST-turn)

Há **um** nemesis Marine principal por campanha — o perseguidor recorrente que existe desde que o bounty do jogador cruzou o limiar de interesse do Governo. Ele tem trajetória **própria**: cresce, muda de postura e pode cair ao longo dos arcos, do mesmo jeito que um Smoker persegue e evolui por mares inteiros mesmo passando turnos sem reencontrar o alvo.

Este canal (`nemesis_update`) é onde **você conduz essa trajetória**. Só existe quando o estado traz um nemesis ativo (`nemesis_active`). Na imensa maioria dos turns é `null` — emita só no **marco**, não na aparição rotineira.

> Não confunda com `bounty_hunter_events`: aquele cria/promove caçadores de recompensa não-Marine. Este move o **nemesis Marine principal que já existe**.

---

## 0. `nemesis_spawn` — quando o Governo despacha o nemesis

Você decide **quando** o Governo despacha o nemesis Marine. Não há mais limiar sorteado nem gate booleano do engine: o spawn é sua decisão. Emita `nemesis_spawn` não-null só em um destes casos:

- **Primeiro nemesis:** ainda não há nemesis ativo (`world_state.nemesis_active` é null) e o peso do jogador justifica o despacho — bounty relevante, caos crescente, ou ato público contra a Marinha.
- **Substituto:** `world_state.nemesis_dormant.substitute_pending` é true (o anterior caiu) e a Marinha reagiu à queda designando o próximo perseguidor.

Dois campos **opcionais** no spawn: `initial_posture` fixa a relação de partida do caçador — `hostile` é o default, use `rival_respectful` ou `ally_leaning` só quando o despacho já nasce com relação diferente (rival de honra, Marine estilo Coby); `origin_location` nomeia a base/ilha Marine de onde ele é despachado — a engine usa só como fallback de localização. Omita ambos quando não se aplicarem.

`null` na imensa maioria dos turns. Não confunda `nemesis_spawn` com `bounty_hunter_events` (caçadores não-Marine) nem com `nemesis_update` (move o nemesis que já existe). Um só nemesis Marine principal por vez: não emita `nemesis_spawn` quando já há `nemesis_active` e não há substituto pendente.

---

## 1. Os tipos de registro

### `evolved` — o nemesis cresceu

A trajetória dele avança — um **salto** de poder, patente, aliados ou força. Pode acontecer de duas formas:

- **On-scene** (`on_scene: true`): a cena PRESENTE **exibe** o crescimento, diante do jogador — ele reaparece já promovido, destrava um poder novo no confronto, ou chega com um tenente/esquadrão que antes não tinha.
- **Off-scene** (`on_scene: false`): cresceu **longe** do jogador. Esteve caçando, subindo na hierarquia, treinando, juntando força — e é noticiado maior (jornal, relato, tick do mundo) sem estar em cena. Caminho Smoker-style: some por um trecho, evolui por conta própria.

> **`evolved` ≠ revés.** Um confronto em que o nemesis apenas **perde e recua** (sem exibir um salto) é `clash` — a evolução vem depois, no reaparecimento. `evolved` é quando há um salto concreto (patente/poder/aliado/força), não o mero revés.

A faceta (`evolution_facet`) diz **como** cresceu:

| faceta | o que muda |
|---|---|
| `rank_up` | sobe patente (Capitão → Comodoro → Vice-Almirante → Almirante → Almirante de Frota). Emita `new_rank` com a patente nova (≥ atual); quando ela cruza um piso de poder, o engine sobe o tier mecânico junto. |
| `power_growth` | nova fruta, destrave de Haki, ou técnica-assinatura que vira identidade dele. |
| `new_lieutenant` | recrutou um subordinado nomeado (gancho de dupla/rivalidade). |
| `bigger_squad` | passou a vir com força maior (esquadrão, navio, cerco). |

Cresça pelo que a história pede e pela pressão que o jogador gera (bounty, caos, tempo desde o último confronto). Sem cota, sem ritmo fixo.

### `posture_shift` — a relação virou

O nemesis nem sempre é hostil, e nem sempre continua igual. A postura dele com o jogador pode mudar:

| postura | sentido |
|---|---|
| `hostile` | caça pra capturar/abater; o perseguidor clássico. |
| `rival_respectful` | ainda o adversário, mas reconhece o jogador — rivalidade com código, duelo de honra. |
| `ally_leaning` | cresceu a ponto de hesitar contra o jogador, ou compartilha um inimigo maior; Coby-style, um Marine que se aproxima sem deixar de ser Marine. |

Emita quando um beat concreto move a relação (um gesto, uma dívida de honra, uma traição da própria Marinha presenciada). Não oscile a cada turn.

### `defeated_on_scene` — o nemesis SAIU DE JOGO nesta cena

Numa cena **com o jogador**, o nemesis foi tirado de jogo de forma definitiva. É um marco pesado — só vale quando ele **realmente cai**, nunca num revés passageiro. O `outcome` diz como:

| outcome | efeito |
|---|---|
| `captured` | ficou sob custódia do jogador/aliados. |
| `dead` | morreu. O engine **arquiva** e abre o intervalo até a Marinha designar um substituto. |
| `missing` | sumiu sem corpo (engolido pelo mar, desaparecido sem volta). Mesmo desfecho de ciclo que `dead`. |

Só emita quando a prosa **fechou** o desfecho. Os casos abaixo **NÃO** são `defeated_on_scene` — quando houve luta de verdade sem ninguém cair, use `clash` (abaixo):
- O nemesis **recua ferido** mas escapa vivo e livre. Recuo não é queda; a caçada continua e ele volta.
- O **jogador** é quem perde, foge ou é dominado, com o nemesis intacto. O canal é sobre o **nemesis** cair, nunca sobre o jogador.
- Um golpe forte que a cena **não fechou** em captura ou morte. Não deduza queda de um acerto pesado.

### `clash` — confronto sem queda

O nemesis e o jogador se enfrentaram **de fato** — troca real de golpes — e alguém recuou, mas **ninguém saiu de jogo**. Um revés tático: o jogador escapou ferido, ou o nemesis recuou destroçado mas vivo e livre, ou o choque foi cortado antes do desfecho. É um **registro leve** no dossiê do confronto; não muda patente, postura, nem tira ninguém de jogo, e a caçada continua.

Use `clash` no lugar de `defeated_on_scene` sempre que a luta aconteceu mas o nemesis **não** foi capturado nem morto — inclusive quando é **o jogador** que leva a pior. O `clash` não tem `outcome`; descreva o revés no `rationale`.

---

## 2. Quando NÃO emitir (fica `null`)

- Nemesis apareceu, trocou farpas, perseguiu, e **não houve luta de verdade** → `null`. Aparição/ameaça verbal não é confronto.
- Nemesis cresceu por vencer? Não cresce por vencer — se dominou sem cair, isso é `clash` (houve luta) ou `null` (só ameaça). O bounty do jogador, se subiu pelo estrago, é `bounty_delta`, não aqui.
- Turno calmo sem o nemesis → `null`.

> Houve **troca real de golpes** mas ninguém saiu de jogo? Isso é `clash`, não `null` — o confronto merece registro. `null` é para quando **não houve luta** (ou não há nemesis).
- Em dúvida entre marco e rotina → `null`. É barato esperar o próximo turn; inflar gasta a evolução.

---

## 3. Anti-vícios

- **Sem evolução a cada confronto.** Trajetória tem degraus espaçados; não suba patente toda vez que ele cruza o jogador. Um confronto comum é `clash`, não `evolved`.
- **Recuo não é queda.** Confronto onde ninguém sai de jogo é `clash`, nunca `defeated_on_scene`. `dead`/`missing`/`captured` exigem a cena ter fechado o desfecho, não um acerto pesado.
- **Postura não é humor.** `posture_shift` é virada de relação, não reação de um diálogo só.
- **Off-scene é legítimo.** Não precisa do nemesis em cena pra ele crescer — o mundo segue girando longe do jogador.
- **Um nemesis principal.** Este canal (`nemesis_update`) nunca cria um segundo nemesis Marine; ele só move o que já existe. O substituto após a queda entra por `nemesis_spawn` (§0), quando `substitute_pending` está true.
- **Patente ≠ tier.** Você move a patente narrativa; o engine decide se cruzou o piso de tier. Não anuncie número de tier.

---

## 4. Schema

```jsonc
"nemesis_spawn": {             // null na maioria dos turns; §0
  // primeiro nemesis (nemesis_active null + peso do jogador) OU substituto (nemesis_dormant.substitute_pending true)
  "initial_posture": "hostile" | "rival_respectful" | "ally_leaning" | null,  // opcional; hostile é o default, omita salvo despacho com relação diferente
  "origin_location": "string" | null,  // opcional; base/ilha Marine de origem, engine usa só como fallback de localização
  "rationale": "1-2 frases factuais: o que justifica o despacho agora (bounty/caos/ato público, ou queda do anterior)"
}
```

```jsonc
"nemesis_update": {            // null quando não há nemesis ou não houve nada digno de registro
  "change_kind": "evolved" | "posture_shift" | "defeated_on_scene" | "clash",
  "evolution_facet": "rank_up" | "power_growth" | "new_lieutenant" | "bigger_squad" | null,  // só em evolved
  "new_rank": "Capitão" | "Comodoro" | "Vice-Almirante" | "Almirante" | "Almirante de Frota" | null,  // só em evolved+rank_up: patente nova (≥ atual); engine cruza o piso de tier
  "on_scene": true | false | null,        // só em evolved: confronto desta cena vs off-scene
  "new_posture": "hostile" | "rival_respectful" | "ally_leaning" | null,  // só em posture_shift
  "outcome": "captured" | "dead" | "missing" | null,        // só em defeated_on_scene (o nemesis saiu de jogo)
  "rationale": "1-2 frases factuais: o que no turn/mundo justifica este registro"
}
```

`clash` usa só `change_kind` + `rationale` (sem facet/posture/outcome).

## 5. Auto-check antes de emitir

0. `nemesis_spawn`: só não-null quando (`nemesis_active` null + peso do jogador justifica) OU (`nemesis_dormant.substitute_pending` true)? `null` na maioria, e nunca quando já há nemesis ativo sem substituto pendente?
1. Há nemesis ativo (`nemesis_active`)? Senão, `nemesis_update` é `null`.
2. Houve **luta de verdade** ou só aparição/ameaça? Sem luta e sem outro marco → `null`.
3. `evolved`: a faceta casa com um salto concreto? `rank_up` traz `new_rank` (≥ atual)? `on_scene` reflete onde cresceu?
4. `posture_shift`: houve beat concreto que virou a relação?
5. `defeated_on_scene`: quem saiu de jogo foi o **nemesis** (não o jogador)? A cena **fechou** captura/morte? Senão, houve luta → `clash`; não houve → `null`.
6. `clash`: houve troca real de golpes sem ninguém cair? (revés tático de qualquer lado).
7. Não estou criando um segundo nemesis nem anunciando tier numérico?

Passa → emite. Sem luta e sem marco → `null`.
