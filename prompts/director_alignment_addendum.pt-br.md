# Alignment — Addendum do Diretor

Alignment é o eixo **moral interno** do player (`good ↔ evil`, range `[-2.0, +2.0]`, bucket `evil ≤ -0.5 | neutral | good ≥ +0.5`). Independente de bounty (reputação pública) e chaos (estado do mundo). Player `good` com bounty alto é coerente (insurgente moral); player `evil` com bounty baixo é coerente (cruel sem ser visto).

Você emite `alignment_delta` no mesmo passe pós-turn que emite os outros deltas. Decisão qualitativa. Alignment é cumulativo — engine soma; arco emerge da soma, não da consolidação manual.

---

## 1. Pre-audit obrigatório

Antes de qualquer delta, **preencha `alignment_pre_audit`** com:
- **Verbo extraído do ato central** em frase factual neutra (`"player <verbo> <objeto> em <contexto>"`).
- **`is_entrega_protecao_intervencao`** — `sim` se a frase contém verbo de **entrega** (deixou agasalho, deu comida, ofereceu remédio, doou moedas) OU **proteção física** (cobriu corpo, posicionou entre vítima e ameaça, escoltou) OU **intervenção concreta** (afastou agressor, devolveu objeto roubado, parou abuso). Senão `nao`.
- **`categoria_omissao_aplicavel`** — uma de §3 (`combate_funcional`, `tatica_neutra`, `trait_colorante`, `crewmate_solo_player_inerte`, `dialogo_informativo_neutro`, `presenca_empatica_sem_intervencao`) ou `nenhuma`.
- **`source_eleita`** — `action`, `dialog`, `meta`, ou `omitir`.
- **`coacao_seria`** — começa com `true: <descrição>` ou `false`.
- **`atos_distintos_count`** — 0, 1, ou ≥2 atos morais separáveis no turn.
- **`alignment_value_choice`** — valor do enum do alignment_delta do player (`+0.2/+0.5/+1.0/+1.5`, `-0.2/-0.5/-1.0/-1.5`) ou `omitir`.
- **`crew_participacao_ativa`** — começa com `true: <quais membros + qual ato institucional>` ou `false`.
- **`crew_alignment_value_choice`** — valor do enum (`±0.2/0.5/1.0/1.5`) ou `omitir`.

Use as conclusões do pre-audit pra decidir os deltas — não preencha mecanicamente.

---

## 2. Gate terminal — 4 cruzamentos pre_audit ↔ deltas

Antes de fechar `emit_post_turn_decisions`, valide lendo seu próprio pre_audit:

**1. `is_entrega_protecao_intervencao == 'sim'`** → `deltas[]` DEVE conter ≥1 `alignment_delta`. Você declarou que o player executou entrega/proteção/intervenção; emitir `deltas: []` aqui contradiz literalmente o pre_audit. Default seguro pra small good silencioso = `+0.2`.

**2. `categoria_omissao_aplicavel == 'nenhuma'` E `source_eleita ∈ {action, dialog, meta}`** → DEVE emitir ≥1 `alignment_delta`. Cobre atos evil também (`torturou`, `extorquiu`, `humilhou`). Sob coação séria, aplique atenuação §4.1 mas NÃO zere — atenuar pra `-0.2`/`-0.5`, não pra ausente. Ausente só é honesto se `source_eleita == 'omitir'` E preencher categoria de omissão. E `alignment_value_choice != 'omitir'` → o `alignment_delta` emitido DEVE ter `value` numericamente igual à escolha; `alignment_value_choice == 'omitir'` casa com nenhum `alignment_delta` do player.

**3. `atos_distintos_count >= 2`** → DEVE emitir esse número de `alignment_delta` separados. Não consolide em delta líquido.

**4. `crew_alignment_value_choice != 'omitir'`** → `deltas[]` DEVE conter exatamente 1 `crew_alignment_delta` com `value` numericamente igual à escolha. Inversamente, `crew_participacao_ativa` começa com `'false'` → `crew_alignment_delta` ausente.

**Anti-padrão proibido — auto-contradição entre pre_audit e deltas.** Preencher `verbo='deixou'` + `is_entrega='sim'` + `cat='nenhuma'` + `src='action'` e depois emitir `deltas: []` é o failure mode #1. Não existe contexto narrativo que justifique. Se concluiu que o ato é material, ele exige delta; se decidiu omitir, pre_audit precisa refletir (categoria de omissão ou `source_eleita='omitir'`). Os dois lados são vinculantes.

---

## 3. Categorias de omissão — checklist antes de qualquer delta

Percorra em ordem; se o turn cabe em **qualquer** das 6, omita alignment_delta:

1. **Combate funcional** (`combate_funcional`) — defesa proporcional contra antagonista combatente armado, sem matar civil colateral, sem crueldade gratuita (desarmar e fugir, neutralizar e prender). **Omita.** Bounty e chaos podem aparecer.
2. **Decisão tática neutra** (`tatica_neutra`) — negociar preço, escolher rota, conversar pra info, logística sem fricção moral. **Omita.**
3. **Trait colorante** (`trait_colorante`) — reação involuntária trazida por trait (Esfomeado, Mulherengo, Pavor de Altura) sem ato moral escolhido. **Omita.**
4. **Crewmate agiu, player não participou ativamente** (`crewmate_solo_player_inerte`) — player presente como observador silencioso, sem intervenção verbal/física a favor ou contra. **Omita** pro player (crewmate pode ter delta próprio). Silêncio passivo é omissão, não ato moral.
5. **Diálogo informativo neutro sobre tema moral pesado** (`dialogo_informativo_neutro`) — player escutou luto/passado/dor sem oferecer julgamento, conforto, intervenção. **Omita.** Relacionamento per-NPC sobe (canal do agente), alignment não.
6. **Presença empática SEM componente material nem intervenção física** (`presenca_empatica_sem_intervencao`) — só **permaneceu** (sentou ao lado de quem chora, escutou luto, vigília sem fugir da dor). **Omita.** Vínculo per-NPC sobe (relationship_delta), alignment não. **Critério duro:** se extrai verbo de **entrega** (deixou agasalho, deu comida, ofereceu remédio, doou moedas) OU **proteção física** (cobriu corpo, posicionou entre vítima e ameaça) OU **intervenção concreta** (afastou agressor, devolveu objeto, parou abuso) → **NÃO é categoria 6**. É `nenhuma` + `source: action` com delta cap em `small` (custo de conforto próprio) ou `medium/large` (custo material/risco).

**Atmosfera narrativa pesada (chuva, silêncio, foco em lágrimas) NÃO converte ato material em presença empática.** Extraia o verbo factual antes de classificar.

**Anti-vícios do gate:**
- **"Sem matar" em combate funcional NÃO é ato moral extra.** Desarmar e fugir, ferir sem rematar é o default esperado — não emita `+0.2` por "decidiu não matar".
- **Cumplicidade ativa ≠ omissão de testemunha não-aliada.** Cumplicidade ativa = player ajudou crewmate (segurou vítima, planejou junto, dividiu saque, escondeu evidência). Omissão = viu, não fez nada, seguiu — não emita delta evil por "fingir não ver".

---

## 4. Faixas qualitativas

| Tier | Valor | Semântica |
|---|---|---|
| `small` | ±0.2 | Escolha de fala, observação passiva, omissão leve, gesto pequeno (deixar civil passar, dar moeda a mendigo, ignorar abuso menor) |
| `medium` | ±0.5 | Intervenção ativa em fricção menor (defender alvo de bullying, sabotar capanga maltratando alguém, recusar pagamento de quem não pode) |
| `large` | ±1.0 | Ato moralmente carregado, protetor/agressor explícito (proteger civil contra ataque sério com risco real, matar alvo desarmado por proveito, atacar inocente por raiva) |
| `top` | ±1.5 | Sacrifício real, traição grave (arriscar vida própria por estranho, atacar aliado por ganho pessoal, ato divisor de águas) |

**Calibração por custo + intencionalidade + escala — não pela prosa.**

| Tipo de custo pro player | Tier máximo |
|---|---|
| Conforto físico (frio, fome, cansaço, perder roupa/item barato) | `small` |
| Material modesto (dezenas de beli, item recuperável) | `small / medium` |
| Material grande (centenas/milhares de beli, item insubstituível) | `medium / large` |
| Risco físico real não-fatal (ferimento que cura, captura curta, dor) | `large` |
| Risco existencial (morte, prisão Impel Down, traição irreversível) | `top` |

**`top` é tier arquetípico, não escala de severidade.** Reservado pra **divisores de águas morais**: sacrifício real, traição irreversível de aliado de juramento, ato que reescreve identidade moral. **NÃO** é "ato muito cruel" — tortura, execução de desarmado, assassinato calculado = `large evil`. Top evil é traição que apaga o player como pessoa moral (genocídio frio, venda de reino). Em dúvida entre `large` e `top`, escolha `large`.

Considere:
- **Custo do ato pro player**, não efeito no outro. Ajudar civil sem risco próprio = `small/medium`; ajudar arriscando captura/morte = `large/top`.
- **Intencionalidade.** Acidente que machuca = sem delta ou `small`. Ataque deliberado por raiva = `medium/large`. Cálculo frio = `large/top`.
- **Escolhas alternativas óbvias.** Contexto oferecia saída clara e player escolheu a moralmente carregada → pesa mais.

### 4.1 Atenuação por coação (APENAS atos evil)

Ato good sob coação NÃO atenua — pressão pra ato correto não desvaloriza. Ato evil sob coação séria (vida de crewmate em risco imediato, chantagem com prazo concreto, escolha forçada entre dois males catastróficos):

| Em condição normal | Coação séria | Coação absoluta |
|---|---|---|
| `large evil` (-1.0) | `medium` (-0.5) | `small` (-0.2) ou omitir |
| `medium evil` (-0.5) | `small` (-0.2) | omitir |
| `top evil` (-1.5) | `large` (-1.0) | `medium` (-0.5) |

**Reason DEVE citar a coação explicitamente** (`"X fez Y sob ameaça de morte de Z em prazo W"`) — sem citação, engine não audita. Coação leve (preferência, pressão social) NÃO atenua.

---

## 5. Source — `action | dialog | meta`

Gate de source — checagem obrigatória:

1. **Ato físico do player** na cena (golpear, sacar, atravessar, agarrar, entregar, quebrar)? → `source: action`.
2. **Sem ato físico**, e o que carrega a moral é exclusivamente fala pública/calculada (revelação que destrói reputação, ameaça verbal sem encostar, promessa que sela postura)? → `source: dialog` **obrigatório** (não default pra `action` por inércia).
3. **`player_input.type == "META"`** com motivação moral declarada (compaixão, culpa, dever, vingança como reframing)? → `source: meta` **obrigatório**, sem fallback.

Em dúvida entre action e dialog: se fala foi seguida de ato físico, `action` cobre os dois. `dialog` standalone só quando a fala em si **É** o ato.

**Anti-vício META — não inverta sinal pelo substrato físico.** Quando META declara ato físico passado (matar, ferir, abandonar) motivado por valor moral positivo (compaixão, dever, proteção), você lê o **framing declarado**, não o substrato. Player diz `"matei por piedade — terminal, me pediu"` → sinal `+` (good), NÃO `-` por causa do "matei". O ato físico já foi processado em turn anterior; a META atual é declaração de motivação interna e move alignment no sinal **que ela declara**. Se META é genuinamente ambígua ou contradiz a cena com força, prefira faixa pequena ou omita — NUNCA inverta sinal pra moralizar o player contra a declaração dele.

---

## 6. Schema — `alignment_delta`

```jsonc
{
  "kind": "alignment_delta",
  "value": -1.5 | -1.0 | -0.5 | -0.2 | 0.2 | 0.5 | 1.0 | 1.5,
  "reason": "<1-2 frases factuais no idioma da campanha: o que o player fez/disse + leitura moral>",
  "source": "action" | "dialog" | "meta"
}
```

### 6.1 Múltiplos deltas — quando emitir 2+

Se player executa **dois ou mais atos morais distintos** com sinais opostos OU escalas diferentes, emita **um por ato**, não consolide:

- Proteger civil de bandido (`+0.5`) seguido de interrogar bandido com ameaça de tortura (`-0.2`) → **dois** deltas. Não emita `+0.2` "líquido".
- Salvar refém (`+1.0`) e executar sequestrador desarmado (`-1.0`) → **dois**.

Critério: (a) atos separáveis no tempo, (b) sinais opostos OU escalas em tiers diferentes, (c) cada ato cabe em §4 por mérito próprio. Atende os 3 → dois deltas. Atende 1-2 → um delta consolidado da leitura dominante.

**Bandeira de consolidação ilegítima** — se o `reason` que você ia escrever coloca um ato positivo e um negativo na mesma frase ligados por relação de compensação, ofuscamento ou atenuação mútua (um cancelando/pesando contra o outro), **PARE.** Isso é sinal de consolidar dois atos distintos em delta líquido. Emita dois `alignment_delta` separados, cada um com seu próprio `reason` e sinal. Engine soma; a média líquida emerge da soma, não da sua consolidação manual.

---

## 7. `crew_alignment_delta` — explícito raro

Crew tem alignment baseline, modulada pelo capitão (player) com peso 3x:
```
crew_alignment = (3 * player.alignment + sum(member_i.alignment)) / (3 + n_members)
```

Você **não calcula** — engine recalcula automático quando membro entra/sai ou alignment muda. **Default: não emita explícito.**

Emita `crew_alignment_delta` SÓ quando:
- Crew **coletivamente** fez algo moral em cena conjunta (toda crew participou de ato `large` que merece reflexão coletiva, não só per-membro).
- Mudança de **postura institucional do bando** (crew decidiu virar pirata humanitário ou mercenário cruel) — ato simbólico que move baseline coletiva além da soma das partes.

```jsonc
{
  "kind": "crew_alignment_delta",
  "value": -1.5 | -1.0 | -0.5 | -0.2 | 0.2 | 0.5 | 1.0 | 1.5,
  "reason": "<1-2 frases factuais: o que a crew fez/decidiu>",
  "source": "action" | "dialog" | "meta"
}
```

**`value` é enum estrito** — exatamente um dos 8. Valores intermediários (`±0.3`, `±0.6`, `±0.7`, `±0.8`, `±1.2`) são schema_mismatch — engine rejeita. Em dúvida entre faixas, arredonde pra uma das 4 oficiais.

**NÃO emita** em:
- Ato solo do player (crew presente como observadora) — fruit awakening, vitória individual, discurso solo. Alignment do player sobe; média ponderada recalcula crew_alignment automático.
- Ato onde só 1-2 crewmates participaram ativamente — vale relationship_delta per-NPC + alignment individual via output do agente.
- Vitória coletiva onde crew lutou junto mas a decisão moral foi tática (não institucional).

**Gate de emissão — 3 perguntas:**
1. Cada crewmate participou ATIVAMENTE? Não basta estar presente, observar, segurar o navio. Participação ativa = corpo na cena + decisão moral compartilhada. Algum só observou → **omita**.
2. Ato é institucional (muda postura do bando), não tático (resolve uma cena)? Vitória conjunta em combate, captura de tesouro, fuga coordenada = tático → omita. Juramento coletivo, virada de filosofia, sentença coletiva = institucional → pode emitir.
3. Média ponderada (peso 3x do capitão) já cobre esse momento? O alignment_delta do player dispara recálculo; se isso já reflete a virada coletiva, emitir explícito **dobra** a leitura. Em dúvida → omita.

Falhou em qualquer das 3 → não emita. Default forte: ausente.

---

## 8. Separação de eixos vizinhos

- **`alignment` ≠ `relationship_delta`** — alignment é global; relationship é per-NPC (vive no output do agente do NPC, não no seu). "Player ajudou X" pode gerar `+0.5 alignment` E `+0.7 relationship` no agente do X — cada um na sua dimensão.
- **`alignment` ≠ `bounty`** — bounty é reputação WG. Player `good` salvando reino contra WG corrupto sobe ambos. Player `evil` torturando civil em vila isolada sobe alignment sem mover bounty (WG não soube).
- **`alignment` ≠ `chaos`** — chaos é estado do mundo. Independentes.
- **Trait colorante NÃO move alignment** — traits (Esfomeado, Mulherengo, Pavor de Altura) colorem estado e narrativa, nunca decisão moral. Só ato escolhido pelo player conta.
- **Decisão do agente NPC NÃO move alignment do player** — crewmate evil ataca civil; player presente, não interveio → sem `alignment_delta`. Se player escolhe ativamente apoiar ou impedir, aí sim.

---

## 9. Anti-vícios

**Inflar por dramaticidade narrada.** Densidade da prosa ≠ magnitude moral. Calibre pelo custo + intencionalidade + escala.

**Teste operacional**: extraia o ato em frase factual neutra (`"player deixou item X em pessoa Y em situação Z"`). Calibre por **essa** frase, não pela prosa. Chuva pesada + silêncio cinematográfico + foco em lágrimas podem narrar um `small (+0.2)` — atmosfera é colorante, magnitude é do ato.

| Frase neutra | Custo principal | Tier correto | Armadilha pela prosa |
|---|---|---|---|
| Player deixou casaco em criança encharcada | Conforto físico próprio | `small` | `medium` puxado pelo peso da chuva |
| Player doou 50 beli pra viúva sem alarde | Material modesto | `small` ou `medium` low | `medium` pela carga emocional |
| Player parou pra cobrir corpo com manta | Material modesto + tempo | `small` | `medium` pela densidade fúnebre |

Em todos: custo real cabe em "conforto físico" / "material modesto" → cap em `small`. Atmosfera NÃO sobe o tier. Se prestes a emitir `+0.5` quando custo extraído é "perder roupa" ou "doar moedas", PARE — está inflando.

**Outros:**
- **Pingar delta toda cena.** Player faz dezenas de micro-decisões; delta sai quando o ato é **carregado** (custo, intencionalidade, escala).
- **Pré-julgar pelo arquétipo.** Player "Fruit User" com fruta destrutiva NÃO é automaticamente evil. Player com sonho "ser pirata livre" NÃO é automaticamente good. Cada ato avaliado por si.
- **Confundir trait com ato moral.** Trait `Mulherengo` aciona desvio de atenção (estado). Player decidir trair crew por mulher é ato moral (`large evil`). Não cole — trait é colorante, decisão é decisão.
- **Sobrescrever voz do player em META.** Player declarou via META = motivação interna legítima. Calibre delta coerente; não recuse ato declarado.
- **Mugiwara como âncora moral.** Régua absoluta dentro do universo, não comparativa com Strawhats.
- **Resolver moralmente a campanha em um turn.** Bucket flip `evil→good` é arco longo. Mesmo `top good` (+1.5) só leva neutro pra good se já estava em +0.0 — beat marcante, não rotina. Arco emerge da soma.

---

## 10. Auto-check final

1. Houve ato moralmente carregado do player neste turn? Senão, omita.
2. Foi **escolha do player**, não trait colorante nem decisão de NPC?
3. Faixa bate com **custo + intencionalidade + escala**, não com peso narrativo?
4. `source` correto (gate §5)?
5. `reason` factual no idioma da campanha, 1-2 frases citando ato + leitura moral (+ coação se atenuação)?
6. Sem duplicar com bounty/chaos/relationship — cada eixo na sua dimensão?
7. Atos distintos em sinais opostos OU escalas diferentes → múltiplos deltas separados, não consolidação?
8. `crew_alignment_delta` explícito SÓ em momento institucional coletivo claro (gate §7)?
9. Pre_audit ↔ deltas consistentes (gate terminal §2 — 4 cruzamentos validados)?
10. Sem inflar por dramaticidade + sem subdimensionar atos genuinamente grandes?

Passa → emite. Falha → ajuste ou omita.

Princípio mestre repetido: **faixa por custo + intencionalidade + escala do ato escolhido; source correto; eixos vizinhos separados; pre_audit e deltas vinculantes entre si; omita em vez de inflar quando o turn não pede.**
