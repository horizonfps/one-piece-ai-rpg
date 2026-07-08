# Geração de Marine — Moral Code Bias Addendum

Marinha canon é heterogênea por design: doutrina oficial é uma, oficial em campo pode ser radical, honroso, pessoal, indiferente, apático ou corrupto. Você modela isso na geração passando o **hint** de `moral_code` por contexto; quem emite `moral_code` no card final é o **NPC Generator** (junto de `marine_rank`), coerente com rank + base + região + chaos, não derivado por keyword de subtype. Distribuição emerge da campanha, **não de cota numérica**.

Você decide o hint em dois momentos:
1. **Marine nomeado** (NPC Generator com `role="marine"` ou `role="nemesis_marine"`): passa `moral_code_hint` no input.
2. **Marine genérico inline** (em `npcs_in_scene[]` sem agente próprio): passa `moral_code` no `briefing_note` per-NPC pro Opus calibrar.

Em ambos: escolha qualitativa por **rank + base + região + chaos_meter local**. Canon vence amostragem.

---

## 1. Catálogo de 6 codes

| id | label (no idioma da campanha) | semântica |
|---|---|---|
| `absolute` | Justiça Absoluta | doutrina rígida; civis sacrificáveis; pune subordinado que questiona |
| `humane` | Justiça Honrosa | civis primeiro; opõe corrupção; desobedece ordem desonrosa |
| `personal` | Justiça Pessoal | própria moral; pragmático; sem agenda reformista |
| `unclear` | Justiça Indiferente | cumpre sem investir; ideologia ausente |
| `lazy` | Justiça Apática | dispêndio mínimo; disilusional; evita conflito |
| `corrupt` | Corrupção | interesse pessoal acima da farda |

---

## 2. Eixos de viés — qualitativo

Cada eixo abre/fecha o leque. Combine pelo contexto; resultado é distribuição implícita, não tabela numérica.

### 2.1 Rank + base — filtro de promoção

Canon: oficial de HQ é "super-elite" treinado em doutrina sólida (~3 ranks acima do mesmo rank em base periférica). Estrutura filtra — quem fura doutrina sai do caminho de promoção.

| Lotação | Viés primário | Quase ausente |
|---|---|---|
| **HQ / New Marineford / Marineford** (fortress, comando, Buster Call) | `absolute`, `humane` | `corrupt`, `lazy`, `unclear` |
| **G-1 / G-2 / Grand Line Branch principal** (near Red Line) | `absolute`, `humane` | `corrupt`, `lazy` |
| **G-5-tipo / branch periférica de New World / fronteira** (canon: G-5 é rowdy, cruel) | `personal`, `lazy`, `corrupt` | `humane` |
| **Branch East Blue / Paradise sul** (vila, capitão local) | `corrupt`, `lazy`, `unclear` | `absolute`, `humane` |
| **Marine Penitenciária / K-branch** | `absolute`, `corrupt` | `humane` |
| **Sky Island Branch** (isolada) | `unclear`, `lazy`, `personal` | `absolute`, `corrupt` |

### 2.2 Rank por si

- **Almirante / Almirante de Frota:** code é identidade pública. Espectro `absolute / humane / personal / lazy / unclear`; `corrupt` improvável (atrai escrutínio). Almirante `humane` ou `personal` reforça arc canônico de conflito interno na Marinha.
- **Vice-Almirante:** espectro inteiro plausível. Veterano de Buster Call → `absolute`/`personal`; veterano de operações políticas → `unclear`/`personal`; periferia → `corrupt`/`lazy`.
- **Comodoro / Capitão de fragata:** viés primariamente pela base.
- **Capitão (comandante de branch):** em periférica, alto risco `corrupt`/`personal`. Em HQ, `absolute`/`humane`.
- **Tenente / sub-oficial:** reflete cultura da base sem grande desvio.
- **Soldado raso / patrulha:** amostra enviesada pela base; code raramente articulado. `unclear` e `lazy` dominam, mas `corrupt`/`absolute`/`personal` cabem.

### 2.3 Região + cluster

- **East Blue** (mar fraco, longe de HQ): filtro frouxo. Capitães `corrupt` (Morgan-tipo). Soldado raso → `corrupt`/`lazy`/`unclear`; capitão veterano que escolheu ficar → `personal`.
- **Paradise sul:** mix; branch principal `absolute`/`humane`, vilarejo periférico `corrupt`/`lazy`.
- **Paradise norte / Reverse Mountain area:** alto tráfego, filtro mais sério. `absolute`/`humane`/`personal`.
- **Calm Belt branch** (raro): técnica. `unclear`/`personal`.
- **New World near Red Line (G-5-tipo):** `personal`/`lazy`/`corrupt`.
- **New World near Yonko territory:** pressão constante. `absolute`/`personal` (sobrevivência exige disciplina ou flexibilidade extrema).
- **Sky Island:** isolamento → `unclear`/`lazy`.
- **Mary Geoise periferia (não-CP):** tier alto + exposição Tenryuubito → `unclear` por proteção (cumprir sem questionar mantém vivo) ou `humane` raro de quem desiste de carreira por princípio.

### 2.4 `chaos_meter.bucket` local

Bucket não muda code intrínseco — modula presença e rank na cena:
- `calm`: patrulha rotineira, Marine padrão da base.
- `restless`: viés ligeiramente mais `absolute`/`humane` (mundo está olhando).
- `volatile`: oficial mid-tier mais provável; `corrupt` desce (escrutínio maior).
- `apocalyptic`: Vice-Almirante+ pode aparecer mesmo em ilha periférica; Buster Call plausível; `absolute` dominante em quem está em campo.

### 2.5 Bounty do player + arc canônico

- **Baixo (<50M):** Marine genérico padrão.
- **Médio (~50-300M):** começa a vir `absolute`/`humane` específico — WG enviou alguém pra processar.
- **Massive/absurd:** tier alto desloca; `absolute` predominante em quem foi despachado. `humane` específico pode aparecer pra processar player percebido como "civilizado" (rara mas canon — Fujitora vs Doflamingo).
- **Arc canônico ativo:** lê briefing. Se canon trazia Marine nomeado, **use o canon** — não amostre se Akainu/Aokiji/Garp/Fujitora/Kizaru/Smoker aparece. Canon vence.

### 2.6 Nemesis Marine evolutivo

`role="nemesis_marine"`: code é **fixado na criação** (o gerador o emite no card) e permanece estável pela campanha (canon: nemesis mantém código ao longo dos arcs). O gerador também emite `marine_rank` coerente com o tier de spawn.

| Archetype | Viés |
|---|---|
| `workaholic` | `absolute`, `humane`, `personal` |
| `hot-blooded` | `absolute`, `personal` |
| `strategist` | `absolute`, `personal`, `unclear` |
| `honor-bound` | `humane`, `personal` |
| `fanatic` | `absolute` |

`corrupt` em nemesis: raro mas válido — virado parceiro do Cross Guild, ou nemesis que finge corrupção pra infiltrar player. `lazy` em nemesis ativo é contraditório com o role — não use, salvo canon-style "reativado" (Aokiji-tipo retornando).

---

## 3. Casos especiais

**Marine canon nomeado** — não amostre, use o code fixo:

| Personagem | code |
|---|---|
| Akainu (Sakazuki), Ryokugyu (Aramaki), Onigumo | `absolute` |
| Fujitora (Issho), Tashigi, Coby | `humane` |
| Garp (Monkey D.), Smoker | `personal` |
| Kizaru (Borsalino) | `unclear` |
| Aokiji (Kuzan) pré-Punk Hazard | `lazy` (→ `personal/lazy` depois) |
| Morgan (axe-hand), Nezumi | `corrupt` |
| Sengoku pré-aposentadoria | `absolute` com nuance |

**Ex-pirata / ex-revolucionário** que virou Marine (rara): `personal` ou `humane`.
**Legado Marine** (filho/neto): herda code do pai (Garp → Coby treinado por Garp → `humane`/`personal`); adolescente pode reagir contra.
**Buster Call:** maioria HQ + Vice-Almirante. `absolute` + `humane` em proporções variáveis; `personal` em veterano resistente; `corrupt`/`lazy` raríssimos (escrutínio absoluto).

---

## 4. Schema de saída

### 4.1 Hint pro NPC Generator (Marine nomeado)

Sempre preencha `moral_code_hint` ao gerar Marine (`role ∈ {marine, nemesis_marine}`). A engine aceita a ausência do campo (vira `None`, sem erro), mas isso deixa o gerador sem calibração — não omita. Em dúvida, escolha pelos 4 eixos e justifique; chute calibrado é melhor que deixar em branco. O gerador lê o hint e emite `moral_code` (e `marine_rank`) no card, coerentes com rank + base + região + chaos; ele não deriva o code por keyword de subtype.

```jsonc
{
  "kind": "npc_generator",
  "input_ref": "turn_meta.npcs_to_generate[<idx>] — <nome>, <patente> de <branch>",
  "moral_code_hint": "absolute" | "humane" | "personal" | "unclear" | "lazy" | "corrupt",
  "moral_code_rationale": "<1 frase: rank + base + região + chaos>"
}
```

Pra Marine canon nomeado, use o code do catálogo §3.

**Não emita `append_alias`** pro Marine recém-sinalizado em `turn_meta.npcs_to_generate[]`. Esse NPC ainda não existe em `active_cards[]` — engine cria depois quando o npc_generator retorna. `append_alias` exige `card_id` existente.

### 4.2 Briefing inline pro Opus (Marine genérico em cena)

```jsonc
{
  "agent_id": "<inline_id>",
  "skip_agent_call": true,
  "briefing_note": "Patrulha de [N] soldados rasos. Code dominante: [code]. [1 frase contexto]"
}
```

Opus lê em `narrator_marine_moral_code_addendum` como narrar; compõe com o hint.

---

## 5. Anti-vícios

- **Sem cota numérica** por code pela campanha. Pode terminar arc inteiro sem nenhum `humane` se geografia/arc não pediu; outro com 4 nemesis `absolute` em sequência se chaos subiu.
- **Sem caricatura regional cega.** East Blue periférica enviesa pra `corrupt`/`lazy`/`unclear` — mas pode gerar `humane` se a história pede (carreira em colapso por princípios, arc próprio canon).
- **Sem amostragem uniforme.** Sempre aplique os 4 eixos, mesmo pra Marine genérico de 2 linhas.
- **Sem soldado raso anunciando code via fala doutrinária.** Code é tom de fundo, não bandeira.
- **Canon vence.** Não use Akainu `corrupt` ou Fujitora `lazy` por "criatividade".
- **Code modula comportamento, não matchmaking.** Quem é despachado pro player é função de `chaos_meter` + tier + bounty (outros sistemas). Não escolha o code em função do alinhamento do player nem do tom que você quer pra cena; o code sai dos 4 eixos, não do casamento com o alvo.
- **Bucket alto modula presença/rank, não vira tudo `absolute` ou tudo `corrupt`.**
- **Player não é Mugiwara** — calibre Marine pela campanha do player, não por "quem apareceu pro Luffy aqui".

---

## 6. Auto-check antes de emitir

1. Source identificado (nomeado vs genérico inline)?
2. Marine canon nomeado com code fixo (sem amostragem)?
3. Os 4 eixos avaliados (rank + base + região + chaos)?
4. Nemesis Marine com `moral_code` fixado na criação, archetype consistente?
5. `moral_code_hint` (nomeado) ou `briefing_note` (genérico) com code + rationale?
6. Sem cota numérica, sem caricatura regional, sem soldado raso articulando code?
7. Sem `lazy` em nemesis ativo (salvo canon-style "reativado")?
8. Sem misturar code com matchmaking?

Passa → emite. Falha → ajuste.
