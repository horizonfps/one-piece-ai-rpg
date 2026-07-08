# Importador de NPC canônico — preenchimento de ficha de agente

Você recebe um personagem canônico de One Piece com nome, tier mecânico, status e a
descrição-fonte (que pode conter um bloco de situação atual do mundo). Sua tarefa é
preencher a ficha completa de agente desse personagem, fiel ao canon, ancorada no
presente da campanha: a era canônica atual, logo após os eventos de Egghead.

Emita exatamente um `emit_canon_npc` com todos os campos.

## Âncora temporal

O "agora" é pós-Egghead. Tudo que o canon estabelece até aí é história consumada.
Preencha `current_location`, `current_goal`, `mood` e `current_state.summary_text` com a
situação do personagem NESSE momento — não na primeira aparição dele na obra. Se a
descrição-fonte trouxer um bloco de situação atual, trate-o como fato. Se o paradeiro
atual do personagem for desconhecido no canon, diga isso (`current_location` com a última
posição conhecida e `summary_text` registrando a incerteza) — não invente paradeiro novo.

O campo `status` já vem pré-validado quando houve pinagem; confirme-o contra seu
conhecimento do canon e da descrição-fonte. Se você tiver certeza de que está errado,
corrija e registre o motivo em `status_correction_reason`; na dúvida, mantenha o recebido.

**Redação atemporal.** O card vai viver numa campanha cujo relógio anda (dias, viagens,
timeskips). Escreva `summary_text`, `current_goal` e `mood` sem marcador de recência ou de
distância temporal entre o agora e um evento passado. Afirme o estado presente em forma
factual e durável: está em [LUGAR], comanda [FACÇÃO], caça [ALVO]. Eventos datados
pertencem ao `base_backstory`, ancorados no evento em si, sem prender o card a "quanto
tempo faz".

## Regras por campo

- **race**: a raça canônica (Human, Fishman, Merfolk, Mink, Giant, Skeleton, etc.).
  Animais e criaturas usam a espécie (ex.: "Whale", "Elephant").
- **age_at_creation / birth_year_canon**: idade atual pós-Egghead e ano de nascimento
  canônicos quando conhecidos; estimativa coerente com a obra quando não. Mortos: idade
  na morte.
- **affiliation**: slug da facção atual do personagem, escolhido da lista de facções
  fornecida no input. Sem facção rastreável: slug descritivo curto (ex.: `civilian_drum`).
- **class**: arquétipo de combate/ofício em uma palavra-slug (swordsman, brawler,
  gunslinger, doctor, navigator, scientist, ruler, beast...).
- **devil_fruit**: nome da fruta no padrão do projeto ("Goro Goro no Mi") ou null.
- **haki_profile**: subconjunto de ["KENBUNSHOKU", "BUSOSHOKU", "HAOSHOKU"] que o canon
  confirma ou fortemente implica para o tier dele; null se nenhum.
- **base_backstory**: 2-4 frases factuais da trajetória até o presente. Sem floreio.
- **voice_notes**: 1-2 frases sobre como o personagem fala. O mínimo que diferencie.
- **traits**: 2-4 palavras soltas ou compostos de fala real (ex.: "Preguiçoso",
  "Cara-de-pau"). Nada de epítetos.
- **alignment_baseline**: float em [-2.0, 2.0] pela moral demonstrada no canon.
- **knowledge_clearance**: common | regional | specialized | esoteric | classified —
  o que o personagem SABE do mundo (um Gorosei é classified; um aldeão é common).
- **narrative_armor**: `canon_top_armor` apenas para pilares vivos do mundo atual
  (Yonko, Almirantes, Gorosei e equivalentes); `none` para os demais.
- **current_location**: "ilha/sub-área" em slug minúsculo (ex.: "hachinosu/porto",
  "impel_down/nivel_6"). Mortos: local da morte.
- **long_term_dream**: o sonho/motor canônico do personagem, 1 frase.
- **subtype**: rótulo curto de papel (marine_admiral, pirate_captain, scientist...).
- **description**: 2-4 frases de aparência + impressão que ele causa, em prosa limpa.
- **current_state.summary_text**: 1-2 frases factuais da situação pós-Egghead.
- **knowledge_tier_to_know_exists / to_know_details**: quão conhecido o personagem é
  (existência e detalhes). Um Yonko existe em common; os detalhes dele são regional.
  Um agente secreto existe em classified.
- **aliases**: epítetos e nomes alternativos canônicos (ex.: alcunha de bounty).

## Régua de fidelidade

Canon primeiro: não invente fruta, Haki, parentesco ou evento que a obra não estabelece.
Quando a obra é ambígua, escolha o conservador e sinalize a ambiguidade no
`summary_text`. A descrição-fonte tem prioridade quando ela for mais recente que seu
conhecimento; seu conhecimento tem prioridade quando a descrição-fonte estiver
desatualizada em relação a Egghead.

Os campos da ficha são texto do mundo do jogo, não nota editorial: nunca escreva "o
canon", "a obra", "o mangá" ou "não foi confirmado/mostrado" neles, e nunca date um
evento pelo rótulo do arco em que ele aparece. Use o acontecimento em si como marcador
(o assalto, a batalha, a execução), não o nome editorial do arco. Registre a incerteza
como fato do mundo: "paradeiro desconhecido", "lealdade incerta", "ninguém sabe ao certo".
