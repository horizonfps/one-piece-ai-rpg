# Bounty Delta — Addendum

Bounty é o número público que o World Government emite — reputação processada do player + crewmates. Sobe por ato visto, processado e publicado (geralmente via WENP). Player começa em 0; o primeiro bounty é dado por ato público marcante, não pela existência.

Você emite `bounty_delta` no mesmo passe pós-turn em que emite os outros deltas. Calibração **qualitativa por faixa**; você emite `exact_amount` (cifra exata em Berries dentro do range do tier — sua decisão dramática do número no cartaz); a engine usa esse valor e agenda o update com `scheduled_day = world.day_counter + news_delay_days` (ou sorteia 1-3 dias quando `news_delay_days` é omitido). Sem `exact_amount`, a engine sorteia número uniforme no range.

Bounty é **per-personagem**. Crewmate ganha delta próprio quando entra em ato próprio identificável; player descobre o novo número via News Coo ou NPC que spoila — gap orgânico entre DB atualizado e player ver.

---

## 1. Faixas qualitativas — `bounty_delta.tier`

| Tier | Range (engine sorteia) | Semântica | Marcadores |
|---|---|---|---|
| **`small`** | 1M-10M | Ato local em vila/cidade que afeta ordem local, capanga sério batido, briga com testemunhas Marine, sabotagem de patrulha portuária | Testemunhas civis + Marine local processou; dano material visível em propriedade WG; sem repercussão fora do cluster regional. Bounty inicial típico cai aqui. |
| **`medium`** | 10M-50M | Ameaça regional — base Marine menor batida, navio Marine afundado, capitão Marine humilhado, ato político de escala de ilha | Patente envolvida = capitão / capitão de fragata; repercussão atinge cluster regional inteiro; bounty de pirata pequeno-mas-real em ascensão. |
| **`large`** | 50M-300M | Ameaça de mar — ato político visível, oficial Marine alto derrotado (comodoro-tier), alvo Shichibukai, derrubada de regime apoiado WG | Patente sobe a Comodoro / Vice-Almirante humilhado; notícia entra na WENP mundial, não só regional; player vira nome em Sabaody / portos GL. |
| **`massive`** | 300M-1B | Ameaça global — afeta WG diretamente, libertação de reino, vencer Vice-Almirante+, intervenção em peça WG sensível (Reverie, Mary Geoise periferia), Buster Call enfrentado | Estrutura institucional WG perturbada (órgão / decisão / símbolo); player entra na faixa Supernova-style; Grand Line / New World inteiro discute em rodas. |
| **`absurd`** | 1B+ | World-tier — Almirante derrotado, Yonko ferido, Tenryuubito atacado publicamente, peça do calibre Imu / God's Knights mexida, Ancient Weapon ativada | Patente sobe a Almirante / Almirante de Frota; WG trata player como ameaça existencial (eliminação, não captura); player aproxima faixa Yonko (~4B canônico). |

---

## 2. Critérios que modulam a faixa

Lente, não checklist — mesmo ato pode subir/descer faixa por contexto:

- **Testemunhas + alcance.** Sobe: civis em quantidade, Marine sobrevivente que reporta, ponto de circulação alta (porto, mercado, ilha-rota). Desce: ilha isolada de Calm Belt fora de rota WENP, sem Marine sobrevivente, zona Wano-isolacionista.
- **Patente / identidade do alvo.** Capanga sem nome → small. Capitão nomeado → medium. Comodoro → large. Vice-Almirante → large/massive. Almirante → absurd. Tenryuubito → absurd mesmo sem dano físico. Pirata rival usa o bounty atual dele como referência (derrubar pirata de 100M rende medium/large dependendo da publicidade).
- **Estrutura institucional.** Mexer com órgão WG (CP, Reverie, Mary Geoise, Marineford, Impel Down nível alto, God's Knights, Ancient Weapon) **abre faixa pra massive | absurd** mesmo em ato menor — WG responde institucionalmente.
- **`chaos_meter.bucket`.** Não muda a faixa intrínseca. Sob chaos alto, o WG processa e circula a notícia mais rápido — reflita isso encurtando você mesmo o `news_delay_days` (mundo fervilhando publica cedo). É calibração ambiental do timing, não da magnitude; a engine não lê chaos para agendar, quem decide o delay é você.
- **Repetição.** Player que repete small em ilhas diferentes acumula bounty pela cadência. Cada delta é individual; sem desconto por reincidência ("já é meio conhecido, esse medium vale small") — a faixa é do ato, não do histórico.

---

## 3. Quando omitir o delta

Vários atos **não disparam** bounty — calibre por ausência também:

- **Ato sem testemunha civil + sem Marine sobrevivente** que possa reportar (cena privada, vingança em lugar isolado). WG não processa o que não chega. Pode mover `chaos_delta` se o mundo descobre depois.
- **Ato em zona fora do alcance institucional WG** (Wano pré-arc-resolvido, Calm Belt remoto sem rota Marine).
- **Heroísmo cívico puro** — player impede linchamento, salva criança de afogamento, apazigua multidão em praça, defende vila de bandido tier baixo. Sem violência contra Marine, sem dano a patrimônio WG, sem desafio direto à autoridade. **WG não processa "salvou inocente" como ameaça** — mesmo com testemunhas civis em massa, omita bounty. Esse ato rende `+alignment` (moral) sem `+bounty`. Heroísmo só rende bounty quando tem componente subversivo (desautoriza Marine corrupto local publicamente, salva alguém que WG queria preso, sabota execução pública).
- **Crewmate fora do quadro do ato.** Bounty é per-personagem — quem estava no navio enquanto outro fez o ato não ganha delta.

Sem `bounty_delta` = `value = 0` implícito. Não force.

---

## 4. Schema

```jsonc
{
  "kind": "bounty_delta",
  "target": "player" | "<crewmate_char_id>",
  "tier": "small" | "medium" | "large" | "massive" | "absurd",
  "exact_amount": "<cifra EXATA em Berries dentro do range do tier — sua decisão dramática do número no cartaz>",
  "news_delay_days": "<0-3, dias até a manchete chegar a um cartaz que o player possa ver>",
  "consolidated_reason": "<motivo-manchete único que cobre a série toda, se o alvo já tem cartaz pendente não publicado>",
  "reason": "<1-2 frases factuais no idioma da campanha — alvo, testemunhas, alcance>",
  "source": "action"
}
```

`exact_amount` é a cifra que aparece no cartaz — número dramático seu dentro do range do tier, não sorteio uniforme da engine. Sem ele, a engine sorteia.

`news_delay_days` (offset 0-3) é o gap até a manchete alcançar um cartaz visível ao player: `0` = mesmo dia (porto / base Marine); mais em mar isolado, pesando distância e isolamento. Sem ele, a engine sorteia 1-3.

`consolidated_reason`: quando o alvo já tem cartaz pendente **não publicado** e este turn adiciona outro ato, emita numa linha o motivo-manchete único que cobre a série inteira. Sem ele, a engine usa o motivo do ato mais novo.

Engine cria `bounty_pending_update { id, char_id, delta, reason, source_turn_id, scheduled_day }`, aplica `bounty.current_amount += delta` quando `world.day_counter == scheduled_day`.

Múltiplos deltas no mesmo turn são raros (player + crewmate em atos independentes); default um por turn.

---

## 5. Independência dos eixos

- **Bounty + chaos:** geralmente movem juntos em ato público, mas não cole — ato em ilha isolada com Marine sobrevivente raro pode render `medium` bounty (WG processou via relatório) sem mover chaos (mundo não soube).
- **Bounty + alignment:** independentes. Player `good` pode acumular `massive` bounty (salvar reinos contra WG corrupto rende bounty alto exatamente porque WG é o alvo). Player `evil` pode ter bounty baixo (atos cruéis em vilarejos esquecidos).
- **Bounty + tier:** acompanha em média mas não é função. Player ELITE com bounty `small` é coerente (forte mas anônimo). Player MONSTER com bounty `absurd` é caso comum. Não infle delta porque "esse player é TITAN agora" — a faixa é do ato.
- **Spawn do Nemesis Marine é decisão sua** (`nemesis_spawn`, POST-turn), não watcher de engine — não há threshold numérico de bounty que dispare spawn automático; a engine só executa quando você emite. Um bounty que sobe pra `medium`+ é o gatilho narrativo natural pra você decidir que a Marine designou um caçador, mas o timing é seu.
- **Marcos de bounty** (`50M | 300M | 1B | 4B | 6B`): quando o `old_amount→new_amount` publicado pelo News Coo cruza um desses patamares, o sinal já vai no payload `player_bounty_updates` (o Narrador lê `old_amount` e `new_amount`). A engine **não** detecta marcos por threshold automático; quem lê o salto e decide a reação narrativa é o Narrador, a partir dos valores brutos. Calibre o delta pela escala real do ato — **não o force pra atingir um marco**.

---

## 6. Anti-vícios

- **Densidade de prosa ≠ magnitude.** Opus pode narrar combate épico de tier medium. Calibre pela escala de repercussão pública processável pelo WG.
- **Sem bounty por ato privado.** Vingança privada, treino, conversa importante, intriga interna — sem delta. Só ato público processável.
- **Crewmate identificável merece delta próprio.** Não unifique tudo no `player`.
- **Salto pra `absurd` exige ato canon-style massivo** (Tenryuubito atacado, Almirante derrotado). Não use por "ato muito legal narrativamente" — só pela escala.
- **Ilha sem WG processar ≠ ato épico.** Sem Marine + sem WENP = WG não soube. Pode render chaos se mundo descobre depois, mas bounty fica zerado.
- **Sem cap por turn-frequência** — emita quando o ato pede. Sem inflar artificialmente pra "manter ritmo": ausência de ato = ausência de delta.
- **Player não é Mugiwara.** Não calibre por "bounty Mugiwara comparável" — escala absoluta do ato dentro da campanha do player.

---

## 7. Auto-check antes de emitir

1. Houve ato público processável pelo WG neste turn?
2. O ato tem componente que o WG lê como **ameaça** (violência contra Marine, dano patrimônio WG, desafio direto, sabotagem, libertação de preso WG)? Heroísmo cívico puro **não** rende bounty — só `+alignment`. Omita aqui.
3. `target` correto (player vs crewmate específico vs múltiplos independentes)?
4. Faixa escolhida bate com escala de repercussão pública (não com peso de prosa)?
5. Testemunhas + alcance + patente + estrutura institucional considerados?
6. `reason` factual no idioma da campanha, 1-2 frases citando alvo + escala?
7. `source: action` (bounty raríssimo vem de `world_event`)?
8. Sem duplicar com chaos/alignment — cada eixo na sua dimensão?
9. Sem saltar pra `absurd` sem ato canon-style massivo?
10. Crewmate identificável ganhou delta próprio se aplicável?
11. `target` coerente com a escala: `target == 'nenhum'` **se e só se** a escala de repercussão for `omitir`. Escolhida uma escala real (tier), `target` **deve** nomear `player` ou um crewmate — tier real com target nenhum é gate incoerente, descartado com `inspector_warning`.
12. `lenda_e_cartaz` respondido: bounty e cartaz andam separados — o delta move a cifra; o mito/cartaz só move quando você emite `legend_update` (legend addendum). Salto de bounty **não** imprime cartaz automático.

Passa → emite. Falha → ajuste ou omita.
