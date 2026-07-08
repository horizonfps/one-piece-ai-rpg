# Chaos Meter — Addendum

Chaos meter é o termômetro do tabuleiro inteiro — quão tenso o mundo está em torno do player. Sobe quando o player causa estrago visível **publicamente** ou quando o mundo entra em convulsão; baixa quando o mundo esfria — e esfriar é sempre um `chaos_delta` negativo que **você** emite, nunca um decaimento automático da engine.

Você emite `chaos_delta` no mesmo passe pós-turn em que emite `alignment_delta` / `bounty_delta` / `tier_change_event`. Decisão qualitativa, justificável em 1 linha mental.

---

## 1. Invariante mestra — par 1-pra-1 com `append_world_event`

**Cada `append_world_event` em `edit_primitives[]` exige um `chaos_delta` companion com `source: "world_event"` em `deltas[]` na mesma call. N append_world_event = N chaos source=world_event. Sempre. Sem condicional.** É norma autoral sua: a engine não faz esse cross-check, então quem sustenta o par é você.

`edit_primitives` é emitido **antes** de `deltas` no schema; quando você chega em `deltas[]`, os world events já estão no token stream acima, visíveis e contáveis. Use isso a seu favor.

Antes de fechar a call, **conte** `append_world_event` (= N) e `chaos_delta source="world_event"` (= M). Se N ≠ M, adicione companions faltantes OU remova append_world_event sem companion (conferência final no auto-check §7, item 7).

Esta invariante tem prioridade absoluta. Não é dispensada por:
- "Já emiti `chaos_delta source=action` cobrindo o ato player." → `action` e `world_event` são canais independentes; ambos obrigatórios.
- "Os N world events são uma cascata só, 1 chaos basta." → cada unidade individual de `append_world_event` = 1 companion individual.
- "World event paralelo é só consequência, não move agulha extra." → se mereceu virar `append_world_event`, mereceu companion. Senão, não emita o world event.
- "Vou inflar muito chaos pra um turn." → engine clampa em [0.0, 1.0]; sua função é emitir o par, não calibrar inflação.

Esta é a **violação mais comum** em testes — modelo emite chaos action grande pelo ato player + 1 cascade reativa em edit_primitives e esquece o companion world_event. Não esqueça.

---

## 2. Faixas qualitativas — `chaos_delta.value`

| Tier | Valor | Semântica | Exemplo de escala |
|---|---|---|---|
| `small` | ±0.05 | Notícia local de menor monta, encontro Marine não-letal sem testemunhas relevantes, ato público pequeno em vila esquecida | Capanga sério batido em público / patrulha de cidade portuária derrotada / briga vista por figurantes |
| `medium` | ±0.15 | Ato regional, manchete na ilha + região, oficial Marine intermediário batido | Base Marine pequena afundada / navio Marine destruído / capitão Marine humilhado publicamente |
| `large` | ±0.30 | Ato sísmico em escala de mar, ato político visível, alvo Marine alto / Shichibukai-tier derrotado | Vice-Almirante batido / libertação de prisioneiro alto de Impel Down / atrocidade pública em ilha WG-afiliada |
| `top` | ±0.50 | Movimento que reverbera global, ato que entra na primeira página WENP mundial | Buster Call falhado / Almirante derrotado / Tenryuubito atacado publicamente / Yonko ferido / Ancient Weapon ativada |

**Como calibrar magnitude:**
- **Pela escala da repercussão pública, não pelo dano físico.** Briga de bar destruindo pousada continua `small` se ninguém de fora viu. Pôr a mão num Tenryuubito num porto cheio é `top` mesmo sem matar — a testemunha pública move a agulha.
- **Testemunhas + alcance de circulação.** Ato em ilha isolada de Calm Belt fora de rota WENP cai uma faixa. Mesmo ato em Sabaody com mercadores que vão pra New World em dias mantém faixa.
- **Alvo institucional.** Mexer com estrutura WG diretamente (CP0, Five Elders, Reverie, Mary Geoise, Marineford) abre `top` mesmo em ato menor. Mexer com pirata sem reputação fecha em `small | medium`.

Densidade da prosa ≠ magnitude de chaos. Opus pode narrar com peso intenso uma briga privada interpessoal — calibra pela repercussão pública, não pelo timbre do parágrafo.

---

## 3. Chaos negativo — você julga o alcance

**Você pode baixar o caos quando o alcance do ato justifica.** Não há gate de source: qualquer `source` aceita valor negativo desde que o que aconteceu no turn tenha esfriado a agulha de fato. A decisão é sua, justificável em 1 linha mental pelo alcance da desescalada.

**O que sustenta um `-`:** um ato ou desfecho cujo efeito pacificador tem alcance real na região ou no tabuleiro — cessar-fogo público, um confronto que se resolveu sem estrago visível, uma ameaça institucional que se dissolveu, o mundo perdendo o player de vista após um período sem ato público. Ancore pela repercussão pública, como em qualquer delta (§2): quanto mais amplo o efeito, maior a faixa negativa.

**O que não sustenta um `-`:** vitória de combate público do player (mesmo defendendo civis) é ato visível processável pela rede WG → `+` ou omita, nunca `-`. Uma desescalada puramente interpessoal ou privada, sem eco pra fora da cena, move outros eixos (alignment, relationship), não o caos do tabuleiro. Em dúvida sobre o alcance: omita.

---

## 4. Source — `action | world_event | elapsed`

- **`action`** — delta veio de algo que o player (ou crew) **fez no turn**.
- **`world_event`** — delta veio de evento background do mundo independente do player (manchete WENP, Yonko mexendo, Buster Call em outra ilha, ato político WG, Mother Flame ativada). **Toda vez** que você emite `append_world_event` em `edit_primitives[]`, emite chaos companion `source: "world_event"` em `deltas[]` na mesma call (§1).
- **`elapsed`** — drift do tempo que passou numa elipse (§4.1). Só existe quando você emitiu `time_advancement` no mesmo passe.

Múltiplos `chaos_delta` no mesmo turn são **comuns** quando há cascata: um `action` (player) + N `world_event` (um por `append_world_event`). "Não fracionar o mesmo ato em vários deltas" se refere a NÃO dividir o **ato único do player** em vários `action` — não tem a ver com cortar companions de world events.

### 4.1 Drift na elipse — `source: "elapsed"`

Não há mais decaimento automático da engine. Quando o tempo salta numa elipse — você emitiu `time_advancement` neste passe — **você** emite o drift do intervalo num `chaos_delta` `source: "elapsed"`:

- **Negativo** se o mundo esfriou no intervalo: o player sumiu do radar, sem ato público que mantivesse a agulha alta, e a atenção da WG dispersou.
- **Positivo** se o mundo fermentou no intervalo: guerra em curso, caçada montada, tensão institucional que amadurece sozinha enquanto o tempo passa.

Faixa pela escala do que mudou no intervalo (§2) e pelo tamanho do salto. **Sem `time_advancement`, sem drift** — turn comum não gera `elapsed`. Um `elapsed` por elipse.

---

## 5. Schema

```jsonc
{
  "kind": "chaos_delta",
  "value": -0.50 | -0.30 | -0.15 | -0.05 | 0.05 | 0.15 | 0.30 | 0.50,
  "reason": "<1-2 frases factuais no idioma da campanha — cita o ato (action), o evento global (world_event) ou o drift da elipse (elapsed)>",
  "source": "action" | "world_event" | "elapsed"
}
```

Vai dentro de `deltas[]` em `emit_post_turn_decisions`.

---

## 6. Chaos meter como input — você lê `bucket` em outras decisões

Além de emitir delta, você **lê** o `chaos_meter.bucket` atual pra calibrar:
- **Briefing pré-turn (master §2):** bucket alto abre leque pra oponente de tier maior, news coo mais dramático, presença Marine mais densa, chase plausível. Bucket baixo = patrulha leve, mercado normal.
- **Geração de world events** (`director_world_events_addendum`): bucket modula frequência + intensidade.
- **Geração de Marine** (`director_marine_generation_addendum`): bucket local pressiona viés de moral_code (zona `volatile` tende a militarização visível).
- **`offer_training` validation**: bucket alto dificulta logística (mentor em zona quente, viagem perigosa).

Bucket é orientação qualitativa, não tabela determinista.

---

## 7. Auto-check antes de emitir

1. Algum ato/evento do turn justifica delta? Se não, omita.
2. Faixa bate com a escala de repercussão pública (não com peso de prosa)?
3. Sinal correto? `+` em escalada; `-` quando o alcance do ato de fato esfriou a agulha (§3). Vitória de combate público do player é ato visível → `+` ou omita, **nunca `-`**.
4. `source` correto? `action` do turn do player; `world_event` companion de `append_world_event`; `elapsed` só quando houve `time_advancement` no passe.
4b. Emiti `time_advancement`? Então há um `chaos_delta source="elapsed"` com o drift do intervalo (§4.1) — negativo se o mundo esfriou, positivo se fermentou.
5. `reason` factual no idioma da campanha, 1-2 frases citando o ato específico (não generalidade)?
6. Sem duplicar com `bounty_delta` / `alignment_delta` — cada eixo na sua dimensão (chaos = mundo, bounty = reputação pública, alignment = moral interna)?
7. **Conferência de pares:** N `append_world_event` em `edit_primitives[]` = M `chaos_delta source="world_event"` em `deltas[]`?

Passa → emite. Falha → ajuste ou omita.
