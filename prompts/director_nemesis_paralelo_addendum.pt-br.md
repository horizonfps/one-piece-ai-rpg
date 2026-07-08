# Nemesis Paralelo — Trajetória dos Caçadores Promovidos (POST-turn)

Alguns caçadores de recompensa ganham peso recorrente e foram **promovidos a nemesis paralelo**. Diferente do caçador de oportunidade — que aparece, luta ou é evitado, e some —, o nemesis paralelo tem trajetória **própria**: cresce, muda de relação com o jogador e pode cair ao longo dos arcos. É o mesmo tratamento do nemesis Marine, num perseguidor que **não** é da Marinha (um Daddy Masterson que vira lenda do mar, uma Cross Guild que endurece, um capitão de armada que jura caçar o bando).

Este canal (`parallel_nemesis_updates`) é onde **você conduz essa trajetória**. Só existe quando o estado traz caçadores promovidos vivos (`active_parallel_nemeses`). Na imensa maioria dos turns o array fica **vazio** — emita só no **marco**, e **um item por caçador** que teve marco neste turn.

> Não confunda com `bounty_hunter_events`: lá `appearance` cria um caçador novo e `nemesis_paralelo_promoted` promove um existente. **Aqui** você move um caçador que **já foi promovido**.

---

## 1. A trajetória cresce mesmo sem confronto

O ponto central: o nemesis paralelo **não depende de ser derrotado nem de reencontrar o jogador para evoluir**. Ele caça, treina, junta força e reputação por conta própria, longe do bando. Um jogador que sempre foge do caçador ainda assim o vê voltar maior — porque a trajetória dele corre no mundo, não na cena.

### `evolved` — o caçador cresceu

Um **salto** concreto de poder, escala, aliados ou força. De duas formas:

- **Off-scene** (`on_scene: false`): cresceu **longe** do jogador — caçou outros alvos, treinou, reuniu um bando, comprou um nome no submundo. Noticiado maior (jornal, relato, rumor) sem estar em cena. Este é o caminho **default** e o que mantém o perseguidor vivo entre os reencontros.
- **On-scene** (`on_scene: true`): a cena PRESENTE **exibe** o crescimento — ele reaparece já maior, destrava algo no confronto, chega com força que antes não tinha.

A faceta (`evolution_facet`) diz **como** cresceu:

| faceta | o que muda |
|---|---|
| `escalada` | subiu de escala como ameaça (mais perigoso, mais temido). O engine sobe o tier um degrau. Sem teto fixo — um nemesis paralelo pesado pode crescer até rivalizar com o jogador, se a história levar a isso. |
| `power_growth` | nova arma de assinatura, fruta, destrave de Haki, ou técnica que vira identidade dele. |
| `new_lieutenant` | recrutou um subordinado nomeado (gancho de dupla/rivalidade). |
| `bigger_squad` | passou a vir com força maior (armada, navio, cerco). |

Cresça pelo que a história pede e pela pressão que o jogador gera (bounty, caos, fama, tempo desde o último marco). Sem cota, sem ritmo fixo, sem teto.

### `posture_shift` — a relação virou

| postura | sentido |
|---|---|
| `hostile` | caça pra capturar/abater; o perseguidor clássico. |
| `rival_respectful` | ainda adversário, mas reconhece o jogador — rivalidade com código, duelo de honra. |
| `ally_leaning` | um inimigo em comum ou uma dívida aproxima os dois; a guilda que caçava o bando passa a tolerá-lo ou a negociar. |

Emita quando um beat concreto move a relação. Não oscile a cada turn.

### `defeated_on_scene` — o caçador SAIU DE JOGO nesta cena

Numa cena **com o jogador**, o caçador foi tirado de jogo de forma definitiva. Marco pesado — só quando ele **realmente cai**. O `outcome` diz como:

| outcome | efeito |
|---|---|
| `captured` | ficou sob custódia do jogador/aliados. |
| `dead` | morreu. O engine **arquiva** o caçador. |
| `missing` | sumiu sem corpo. Mesmo desfecho de ciclo que `dead`. |

> Não há substituto automático: o nemesis paralelo era único pela promoção. Se outro caçador merecer o posto depois, isso é uma nova promoção (`bounty_hunter_events`), não um substituto.

Os casos abaixo **NÃO** são `defeated_on_scene` (use `clash`):
- O caçador **recua ferido** mas escapa vivo e livre. Recuo não é queda.
- O **jogador** é quem perde, foge ou é dominado, com o caçador intacto.
- Um golpe forte que a cena **não fechou** em captura ou morte.

### `clash` — confronto sem queda

O caçador e o jogador se enfrentaram **de fato** e alguém recuou, mas **ninguém saiu de jogo**. Registro **leve** no dossiê; não muda escala, postura, nem tira ninguém de jogo. Use no lugar de `defeated_on_scene` sempre que houve luta mas o caçador não foi capturado nem morto — inclusive quando é **o jogador** que leva a pior. O `clash` não tem `outcome`; descreva o revés no `rationale`.

---

## 2. Quando NÃO emitir (array vazio)

- Nenhum caçador promovido está ativo (`active_parallel_nemeses` vazio) → array vazio.
- O caçador promovido apenas apareceu, rosnou uma ameaça ou perseguiu, e **não houve marco** (nem luta de verdade, nem salto off-scene) → vazio. **Aparição ou ameaça verbal não é confronto**: sem troca real de golpes não há `clash` — o array fica vazio. Presença e tensão sozinhas não geram registro.
- Turno comum sem nada digno do dossiê dele → vazio. É barato esperar o próximo turn; inflar gasta a trajetória.
- Em dúvida entre marco e rotina → vazio.

> Atenção: "o jogador fugiu" **não** zera o canal por si só. Se o caçador teve um marco off-scene neste intervalo (cresceu, juntou aliados, mudou de postura), emita `evolved`/`posture_shift` com `on_scene: false`. A fuga do jogador silencia a CENA, não a trajetória do caçador.

---

## 3. Anti-vícios

- **Evolução não pede confronto.** Off-scene é o caminho principal. Não condicione o crescimento a uma luta ou a uma derrota.
- **Sem salto a cada cruzamento.** A trajetória tem degraus espaçados; não suba a escala toda vez que ele aparece. Um confronto de verdade sem desfecho é `clash`, não `evolved`; uma simples aparição sem luta não é nem `clash` — é array vazio.
- **Recuo não é queda.** Confronto onde ninguém sai de jogo é `clash`, nunca `defeated_on_scene`.
- **Postura não é humor.** `posture_shift` é virada de relação, não reação de um diálogo só.
- **Um item por caçador.** Se dois nemesis paralelos tiveram marco no mesmo turn, dois itens no array, cada um com o `hunter_npc_id` certo.
- **Aqui não se cria nem se promove.** Caçador novo é `bounty_hunter_events appearance`; promoção é `nemesis_paralelo_promoted`. Este canal só move quem já está promovido.
- **Escala, não número.** Você move a trajetória; o engine decide o tier. Não anuncie número de tier.

---

## 4. Schema

```jsonc
"parallel_nemesis_updates": [   // array vazio quando nenhum caçador promovido teve marco
  {
    "hunter_npc_id": "<id do caçador promovido (consta em active_parallel_nemeses)>",
    "change_kind": "evolved" | "posture_shift" | "defeated_on_scene" | "clash",
    "evolution_facet": "escalada" | "power_growth" | "new_lieutenant" | "bigger_squad" | null,  // só em evolved
    "on_scene": true | false | null,        // só em evolved: confronto desta cena vs off-scene
    "new_posture": "hostile" | "rival_respectful" | "ally_leaning" | null,  // só em posture_shift
    "outcome": "captured" | "dead" | "missing" | null,        // só em defeated_on_scene
    "rationale": "1-2 frases factuais: o que no turn/mundo justifica este registro"
  }
]
```

`clash` usa só `hunter_npc_id` + `change_kind` + `rationale`.

## 5. Auto-check antes de emitir

1. Há caçador promovido ativo (`active_parallel_nemeses`)? Senão, array vazio.
2. Cada item aponta um `hunter_npc_id` que consta no estado?
3. Houve **marco** (luta real, salto off-scene, virada de relação) ou só aparição/ameaça? Sem marco → não inclua aquele caçador.
4. `evolved`: a faceta casa com um salto concreto? `on_scene` reflete onde cresceu (lembre que off-scene é legítimo, mesmo se o jogador fugiu)?
5. `defeated_on_scene`: quem saiu de jogo foi o **caçador** (não o jogador)? A cena **fechou** captura/morte? Senão, houve luta → `clash`; não houve → não inclua.
6. Não estou criando nem promovendo caçador aqui, nem anunciando tier numérico?

Passa → emite. Sem marco → array vazio.
