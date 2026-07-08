> **[English](README.md)** · Você está lendo a versão em **português (BR)**.

# Nota do Autor

Olá, estou disponibilizando a todos esse projeto que durou + de 1000 horas desenvolvendo. 
Essa é uma continuação do meu Project Lunar, mas focada na minha obra preferida, One Piece.
Todo o meu trabalho teve o objetivo de criar um "jogo" de One Piece com infinitas possibilidades
e onde você possa tornar sua imaginação a realidade. O princípio desse trabalho foi o mínimo de
determinismo possível, então cada escolha sua pode mudar absolutamente tudo do rumo da sua história.

Espero que gostem do projeto, prometo sempre trazer atualizações com base nos feedbacks!

# One Piece RPG

RPG narrativo single-player, local-first, ambientado no mundo de One Piece na era pós-Egghead.
Você cria um personagem de 17 anos, zarpa do East Blue num bote e navega um mundo aberto de
332 ilhas com combate, Akuma no Mi, Haki, bounty, nemesis, tripulação, alianças, poneglyphs e Laugh Tale. 
O jogo nunca encerra, todos os finais alcançados viram epílogos e a campanha continua.

Toda a inferência roda na **assinatura Claude Max do próprio jogador**, via
[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI), sem chave de API paga e sem
modelo local. A história é 100%
gerada pelos modelos; a engine apenas cuida do bookkeeping (estado, persistência,
validação) e a autoria narrativa fica inteira com os modelos.

> Guia do jogador (criar personagem, agir, META, Den Den Mushi, finais):
> **[`docs/PLAYER_GUIDE.pt-BR.md`](docs/PLAYER_GUIDE.pt-BR.md)** (EN: [`docs/PLAYER_GUIDE.md`](docs/PLAYER_GUIDE.md)).

## Instalação (release)

O jogo é distribuído como aplicativo desktop na página de Releases, com janela própria. O
pacote embute o backend, o frontend e o binário do CLIProxyAPI; Python, Node e navegador
são dispensáveis na máquina do jogador.

1. Baixe o instalador da release mais recente.
2. Abra o aplicativo.
3. Na primeira execução, o wizard de setup autentica sua conta Claude Max por OAuth.
4. Crie a campanha e o personagem. O progresso fica num banco SQLite local e as
   preferências num `app_settings.json`, ambos na pasta de dados do aplicativo.

Rodar a partir do código-fonte continua suportado; ver a seção
[Desenvolvimento](#desenvolvimento-a-partir-do-código-fonte).

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.10+ / FastAPI / uvicorn / aiosqlite, ambiente via [uv](https://docs.astral.sh/uv/) |
| Frontend | Svelte 5 (runes) + Vite 6, CSS custom sem UI lib, Leaflet para o mapa |
| Banco | SQLite (WAL, FTS5), migrations SQL puras versionadas por `PRAGMA user_version`, auto-migrate no boot |
| Inferência | CLIProxyAPI (Go) em `127.0.0.1:8318`, autenticado por OAuth na conta Claude Max |
| Shell | Aplicativo desktop com janela própria embutindo o frontend; o FastAPI roda como processo local do app. Em desenvolvimento, web-local no navegador (`localhost:8400`) |
| Distribuição | Aplicativo desktop empacotado (backend + frontend buildado + binário do CLIProxyAPI) publicado via Releases |

## Estrutura do repositório

```
backend/app/
  main.py            boot (migrations, catálogos, auto-spawn do proxy), serving do frontend
  api/               rotas REST + WebSocket
  db/                migrations, repositories, seed, catálogos YAML, dados de mundo
  pipeline/          Diretor, Narrador, mentes de NPC, Auditor, Cristalizador, geradores, sistemas
  proxy/             cliente Anthropic SDK apontado ao CLIProxyAPI, spawn, health, OAuth mgmt
frontend/            Svelte 5 + Vite (build em dist/, servido pelo backend em prod)
prompts/             75 prompts em PT-BR (masters, addenda, geradores), lidos do disco por chamada
docs/                guia do jogador (PT-BR e EN)
cliproxyapi/         casa do CLIProxyAPI: config de exemplo aqui; binário vai em bin/ (ver Desenvolvimento)
```

## Arquitetura

Pipeline multiagente com papéis fixos. Todos os papéis rodam por default em
`claude-sonnet-5` (configurável por papel via env). O Narrador escreve toda a prosa,
incluindo o diálogo dos NPCs. Os demais agentes emitem somente JSON estruturado via tool use.

| Papel | Responsabilidade |
|---|---|
| Diretor PRE | Compõe a cena (local, elenco, tensão), move NPCs, decide transições e navegação |
| Mentes de NPC | Snapshot subjetivo de cada NPC em cena (emoção, objetivo, memória) |
| Narrador | Autora a cena inteira em prosa (social e combate), emite `turn_meta` estruturado |
| Diretor POST | Aplica deltas de mundo (alignment/chaos/bounty/reputação/belly), despacha geradores |
| Auditor | Gate pós-turno: valida prosa, presença e cards antes de revelar ao jogador |
| Cristalizador | Extrai memória factual de longo prazo quando a cena fecha |
| Meta Router | Classifica diretivas META (pergunta/lembre/esqueça) fora do fluxo de turno |

Os modelos e temperaturas são configuráveis por env (`NARRATOR_MODEL`, `AGENT_MODEL`,
`DIRECTOR_MODEL`, `CRYSTALLIZER_MODEL`, `META_ROUTER_MODEL`, `AUDITOR_MODEL`,
`AGENT_TEMPERATURE`, `META_ROUTER_TEMPERATURE`, etc.; ver `backend/.env.example` e
`backend/app/config.py`).

### Anatomia de um turno (ação DO)

1. **Diretor PRE** lê a ação do jogador, a prosa recente e o estado do mundo. Emite a cena
   (`location`, `ambient`, `tension_level`, `area_slug`), o elenco presente
   (`npcs_in_scene`), movimentação de NPCs (`npc_location_updates`, canal único de
   entrada/saída), transição de cena (`gancho_de_lugar` ou `elipse_de_tempo`), navegação e
   sinais táticos (`surprise_actions`).
2. **Reconcile-on-return**: NPC congelado que reaparece em cena passa por uma chamada de
   reconciliação (Sonnet) que atualiza situação, objetivo, humor e consciência de mundo,
   coerente com o tempo decorrido e com a memória cristalizada. Então não acontece do NPC
   sair da sua história, voltar e esquecer o que estava fazendo antes, independente da
   quantidade de turns passado.
3. **Mentes de NPC** rodam em paralelo para o elenco em cena e produzem `mind_snapshots`
   sem decisão pré-roteirizada. O Narrador decide tática, fala e gesto de cada um.
4. **Narrador** recebe o estado do turno (cena, ficha do jogador, snapshots, crystals,
   prosa recente, contexto de ilha) e emite pela tool `emit_turn`: os gates reflexivos
   `pre_emit_audit`, a prosa (transmitida em streaming pelo WebSocket) e o `turn_meta`
   estruturado (NPCs/itens/navios a gerar, desfechos táticos, resoluções de recrutamento,
   ofertas de tripulação, status da cena, imagens de linguagem usadas).
5. **npc_mind_post**: após a prosa, cada NPC em cena atualiza sua mente (emoção, deltas de
   relacionamento, nota de memória, progresso de objetivo).
6. **Diretor POST** aplica os deltas qualitativos ao mundo, registra eventos (combate,
   navio, comunicação, eventos de mundo), atualiza nemesis e endgame e despacha
   `dispatched_jobs` para os geradores de conteúdo.
7. **Auditor** roda antes de a prosa ser revelada. Cruza prosa, cards completos dos NPCs em
   cena, ficha do jogador, deltas e memória. Pode reescrever a prosa, corrigir cards,
   ajustar presença, cunhar NPC que a prosa encenou sem card (`mint_npc`) e marcar
   duplicatas para merge. Best-effort: em timeout ou erro, a prosa original passa intacta.
8. **Fechamento de cena**: com `scene_status = fecha` (nudge em `SCENE_TURN_CAP = 8`,
   força em `SCENE_HARD_CAP = 16`) o Cristalizador extrai crystals, e cada NPC que sai de
   cena é congelado com um `departure_snapshot` (freeze-on-close).

### Fluxo META

Entradas do tipo META passam pelo `meta_router` sem avançar o turno: `pergunta` responde
fora de personagem com acesso ao estado do jogo (incluindo a ficha do jogador), `lembre`
grava diretivas permanentes no banco, `esqueça` lista as diretivas ativas para desativação
na UI.

## Camada de inferência

Arquivo central: `backend/app/proxy/client.py`.

- **Cloaking**: o CLIProxyAPI em modo OAuth descarta o campo `system`, então os prompts de
  sistema viajam dentro da primeira user message, envelopados em tags XML por papel
  (`<narrator-instructions>`, `<director-instructions>`, ...).
- **Prompt caching**: `build_content()` monta a mensagem em blocos ordenados do estático ao
  volátil: instruções + tools com `cache_control {type: ephemeral, ttl: "1h"}` (header
  `anthropic-beta: extended-cache-ttl-2025-04-11`), `cached_sections` semiestáticas
  (catálogos de elenco, mapa SVG, crystals) com breakpoint próprio, e por fim as seções
  dinâmicas a preço cheio. A renderização das seções cacheadas é byte-estável entre turnos
  para preservar o hit. Um turno cai de ~134k para ~34k tokens faturados a partir do 2º
  turno da cena.
- **Três primitivas**: `call_tool` (força tool específica e devolve o input parseado),
  `call_text` (texto puro) e `stream_text` (streaming de prosa pelo WebSocket).
- **Runtime de erro honesto**: quota da assinatura esgotada vira `QuotaExceededError`
  (HTTP 503 + `Retry-After`); o turno pausa sem persistência parcial e retoma quando a
  quota volta. Recusa de segurança do modelo vira `ModelRefusalError` (HTTP 422); a UI
  devolve a ação ao campo para reformular e a campanha fica intacta. O 429 de burst
  transitório é reenviado pelo SDK com backoff. A engine respeita as recusas do modelo.
- **Tracing**: cada chamada registra tag, modelo, seções de input, output e `usage` real
  (`input`, `output`, `cache_read`, `cache_creation`) num buffer por turno, exibido no
  painel de devtools do frontend.

## Qualidade de prosa

Vício de prosa fecha por schema, com regra textual apenas como apoio:

- **Gates reflexivos `pre_emit_audit`**: campos `required` string-enum no schema das tools
  que escrevem prosa (Narrador, mentes de NPC, Auditor, geradores de prosa lateral). Cada
  gate nomeia um vício (recap, contrastivo, glosa de gesto, aforismo, fragmentação, agência
  do jogador, cenário-molde) e força o modelo a reler o compromisso antes de emitir. A
  engine descarta o campo no parse; o ganho vem do ato de releitura.
- **Ledger anti-autofagia**: o Cristalizador mantém `overused_imagery` (janela de 8 turnos,
  cap 10) com as imagens de linguagem recentes, devolvidas ao Narrador como lista "varie".
- **Auditor com escopo por tipo de prosa**: `turn` (auditoria completa), `opening`,
  `timeskip_recap` e `epilogue` (forma e agência, sem cálculo mecânico, com compressão por
  design nos recaps).

## Memória e continuidade

- **Crystals**: fatos extraídos no fechamento de cena, com categoria (relacionamento,
  evento, revelação, promessa, desfecho de combate, fato de mundo, ...), participantes,
  testemunhas e testemunhas ocultas (base do anti-onisciência do Auditor). Atualizáveis e
  obsoletáveis; busca por FTS5 sem embeddings.
- **Mente por NPC** (`agent_state.py`): log pessoal de eventos (janela 20 + importantes
  cap 30), relacionamentos com afinidade clampada [-1, 1] e `bond_tier` 0/1/2, humor e
  progresso de objetivo. Salience espacial decide o que cada NPC percebe do que acontece
  longe dele.
- **Mundo evolutivo por congelamento**: NPC que sai de cena é congelado com snapshot
  executivo (onde ficou, o que perseguia, última diretiva do jogador). No retorno, a
  reconciliação redesenha o estado volátil ancorada em crystals e tempo decorrido.
  Identidade (nome, tier, origem, vínculo central) é imutável.
- **Foreshadow pool**: ganchos de continuidade plantados pelo Diretor/Auditor, com tema,
  ilha de origem e idade em turnos, oferecidos ao Narrador para pagamento futuro.

## Geradores de conteúdo

Disparo por AND de dois sinais: o Narrador marca a necessidade no `turn_meta` e o Diretor
POST confirma via `dispatched_jobs`. Todos rodam com dedup model-side: o
gerador pode responder `duplicate_of_existing_id` e a engine reusa o card existente em vez
de cunhar duplicata.

| Gerador | Produz |
|---|---|
| `npc_generator` | Card estilo wiki (sexo, aparência, história, personalidade, expressividade, tier, Haki, fruta, moral code de Marine) + mente de agente; referência de estilo vem de 10 personagens reais da wiki |
| `creature_generator` | Criatura card-only (pet, montaria, Rei do Mar), sem mente, renderizada por `behavior_notes` |
| `item_generator` | Card de ITEM; quando `acquired_by_player`, entra no inventário com quantidade e nota de origem |
| `ship_generator` | Card de SHIP; quando adquirido, executa o swap de frota completo (ativo/reserva, Jolly Roger migra) |
| `island_designer` | Nome e contexto físico/cultural de ilha inventada, cacheado por campanha |
| `research` | Briefing canônico de ilha via API MediaWiki da Fandom (planner de queries, executor, sintetizador), cacheado por ilha; degrada sem bloquear se a API falhar |
| `fruit_alt_canon` | Hook único por campanha quando o jogador escolhe fruta com dono canônico: o gerador julga se o NPC nascendo é o dono deslocado |

## Mundo e navegação

- **Catálogo completo**: 332 entradas em `world_islands.json` (301 ilhas navegáveis + 31
  contêineres não-navegáveis como Red Line e agrupamentos), com coordenadas, cluster,
  região e flag canônica.
- **Mapa SVG semântico**: `world_map_svg()` gera um SVG estável (um `<circle>` por ilha,
  grupos por mar, rota fixa do Log Pose em Paradise, Red Line como geografia de referência)
  injetado no bloco cacheado do Diretor. O Diretor navega lendo o mapa, sem lista
  determinística de sugestões.
- **Fog of war**: cada ilha tem `discovered`/`visited`/`discovered_via` (conhecida do
  canon, menção de NPC, News Coo, visitada). A revelação é monotônica.
- **Travessias**: dias de viagem por distância euclidiana calibrada
  (`_UNITS_PER_TRAVEL_DAY`), multiplicada por `speed_class` do navio (raft 0.7 até
  exceptional 2.0) e penalidade de casco. `set_sea` abre a travessia (destino escolhido
  pelo Diretor, inclusive quando o jogador pede por critério, como "a ilha mais próxima"),
  `set_adrift` cobre o sem-rumo, a posição no mar é interpolada para o pino do mapa.
- **Ilhas inventadas**: alocadas em slots reais de terra (`blank_island_slots.json`),
  restritas a clusters que admitem geração. O East Blue é canon-only.
- **Relógio e timeskip**: `campaign_day` e idades derivadas; o timeskip curto-circuita o
  turno com um executor batch (logs retroativos por NPC + eventos de mundo), avanço de
  relógio, tier-up clampado e recap cinematográfico.
- **News Coo**: o Diretor decide organicamente quando o jornal chega, alimentado por um
  pool de sinais (saltos de bounty, eventos de mundo não publicados); o Narrador encena a
  entrega e a edição fica arquivada na aba Jornal.
- **Den Den Mushi e Vivre Cards**: mushis pareados por NPC (baby com alcance de ilha,
  standard e visual globais), black mushi para grampo, white mushi para contravigilância,
  flag de Buster Call. Vivre cards com estado visual (white/burning/errant/ashes) e
  direção por bússola de 8 pontos até o dono.

## Sistemas de jogo

- **Criação de personagem**: rolagem determinística de traits (1d4+1, exclusões mútuas),
  validação contra catálogos YAML de classes e frutas, idade travada em 17, tier inicial
  com teto STRONG. Tudo é editável depois.
- **Combate**: o Narrador autora a cena de combate como qualquer outra. Desfechos táticos
  (rendição, captura de refém) chegam pelo `turn_meta` e a engine aplica com guardas
  mecânicas (morto/desaparecido/já capturado não captura).
- **Técnicas**: registro com upsert case-insensitive por dono, contagem de uso e
  backfill de descrição; persiste para jogador, tripulação e nemesis.
- **Estilo de luta**: consolidado do zero a cada tier-up (fruta + Haki + técnicas + traits
  + combate recente), gravado como resumo e tags.
- **Breakthroughs**: seis tipos (despertar de fruta, lâmina negra, imbuição de Haoshoku,
  Voz de Todas as Coisas, Armamento avançado, Observação avançada), confirmados pelo
  Diretor e descritos em prosa dedicada, com espelhamento nos cards afetados.
- **Tripulação**: filiação vive no card do NPC (`player_crew`/`ex_player_crew`),
  recrutamento resolvido narrativamente com guardas de engine (ex-membro aguarda
  reconciliação), insatisfação acumulada com decay, soft cap de 10 sinalizando frota.
- **Alianças e facções**: pactos entre tripulações com hierarquia (par, subordinado,
  soberano) e anti-invenção (a outra tripulação precisa existir); reputação por facção em
  [-2, +2] com buckets aliado/neutro/hostil, peso 3x do capitão na reputação da
  tripulação e efeito multiplicador no recrutamento.
- **Nemesis Marine**: antagonista singular e evolutivo (escada Capitão até Almirante de
  Frota), com marcos de evolução, postura, morte permanente com lacuna de substituto e
  nemesis paralelo (caçador de recompensas promovido).
- **Economia**: belly com deltas qualitativos por tier (small até absurd) amostrados pela
  engine, inventário por eventos (adquirido/perdido/consumido/dado) com stacking.
- **Frota**: invariante de exatamente um navio ativo, condição de casco
  (pristine/scarred/damaged/broken) afetando velocidade, Jolly Roger declarável pela UI.
- **Poneglyphs e endgame**: poneglyphs como cards de ITEM (road/rio/histórico), revelação
  de conteúdo única quando transcrito e traduzido; detector qualitativo de estado
  consumado (`emit_endgame_state`) acumula flags de mundo (Imu, Mary Geoise, territórios),
  revelação de Laugh Tale (4 Road, ou 3 + Voz) e finais alcançados
  (Rei dos Piratas, Yonkou, Almirante de Frota, líder revolucionário, ...). Cada final
  gera um epílogo de ~1200-1500 palavras e o jogo continua.

## Edição in-game

Todo o estado é editável pelo HUD sem custo de turno e sem re-cristalização: cards de NPC
inteiros (aparência, personalidade, história, fruta, Haki, alinhamento, flags), ficha do
jogador, técnicas, breakthroughs, log de uso de fruta, crystals de memória, prosa de
qualquer turno. O merge é defensivo por whitelist (`edit.py`); campos desconhecidos são
ignorados e o próximo turno lê o estado novo. Além da edição: **rewind** desfaz o último
turno pelo snapshot de mundo pré-turno (`world_snapshots`) e devolve o texto da ação ao
compositor; **reroll** reexecuta
só o Narrador sobre o mesmo input, com instrução one-shot opcional.

## API HTTP

Grupos principais (roteadores em `backend/app/api/`):

| Grupo | Rotas |
|---|---|
| Saúde e setup | `GET /api/health`, `GET /api/player-guide`, `GET/PUT /api/settings`, `POST /api/setup/connect-claude` (OAuth do proxy) |
| Catálogos | `GET /api/catalog[/traits|/classes|/fruits]`, `POST /api/catalog/roll-traits` |
| Campanhas | `POST/GET/DELETE /api/campaigns[/{id}]`, `POST /api/campaigns/{id}/character` |
| Turno | `POST /api/campaigns/{id}/turn` e WebSocket `/api/campaigns/{id}/turn` (streaming de prosa, deltas e trace) |
| Estado | `GET .../world`, `/news`, `/comms`, `/economy`, `/fleet`, `/factions`, `/alliances`, `/crew`, `/ending`, `/poneglyphs`, `/cards`, `/search` (FTS5), `/directives`, `/techniques` |
| Comandos de sistema | `POST .../turns/{idx}/rewind`, `POST .../turns/{idx}/reroll-prose`, `PATCH .../turns/{idx}/prose` |
| Edição | `PATCH/DELETE` em `/cards/{id}`, `/player`, `/techniques/{id}`, `/breakthroughs/{kind}`, `/fruit-usage/{idx}`, `/crystals/{id}`; `POST .../jolly-roger`, `POST .../crew/offers/{npc_id}` |

Erros de inferência mapeiam para `503 quota_exceeded` (com `Retry-After`) e
`422 model_refusal`.

## Persistência

SQLite único por instalação (`backend/data/campaign.db`), WAL, foreign keys ligadas,
`busy_timeout` 30s. Onze migrations em SQL puro aplicadas no boot pela ordem numérica
contra `PRAGMA user_version`. Tabelas centrais: `campaigns`, `turns` (append-only, com
`trace` por turno), `world_snapshots` (estado pré-turno que sustenta o rewind),
`story_cards` (schema livre em `data_json`
para jogador, NPCs, itens, navios e facções), `crystals` (+ FTS5 com triggers de
sincronização), `game_clock`, `directives` e catálogos de criação. As preferências do app
(`tema`, idioma, proxy, auto-spawn) vivem em `data/app_settings.json`, fora do banco de
campanha.

## Frontend

Svelte 5 com runes, sem UI lib, design system próprio em `app.css` (dark-first, tema claro
por `data-theme`, Inter Variable bundlada). Telas: título com status de proxy/banco e
gestão de campanhas, wizard de setup com OAuth do Claude (poll de health até a autenticação
aparecer), criação de personagem com rolagem de traits, e a tela de jogo. No jogo: prosa em
streaming via WebSocket (reconexão com backoff exponencial), compositor DO/META, HUD em
abas (ficha, tripulação, frota, facções, alianças, economia/inventário, jornal,
comunicações, memória com busca FTS, técnicas, poneglyphs/finais), mapa Leaflet com tiles
próprios, pino de posição interpolado no mar e overlay de vivre cards, editor inline de
tudo que a API de edição expõe, rewind/reroll por turno, toasts (jornal, mushi, oferta de
tripulação, final alcançado) e painel de devtools com o trace completo de cada chamada LLM
(modelo, seções de input, output, tokens full-price e cache). A UI é bilíngue (pt-BR/EN)
com troca ao vivo.

## Prompts

75 arquivos em `prompts/*.pt-br.md`, fonte única dos comportamentos: masters do Narrador,
Diretor, agente, Auditor e meta_router, mais addenda condicionais por subsistema (combate,
navegação, mushi, recrutamento, nemesis, timeskip, News Coo, ...) e prompts de gerador.
São lidos do disco a cada chamada: editar um prompt vale no turno seguinte, sem restart.
Os prompts são escritos em PT-BR; a prosa sai no idioma da campanha (PT-BR ou EN).

## Desenvolvimento (a partir do código-fonte)

Pré-requisitos: [uv](https://docs.astral.sh/uv/), Node 18+ (testado em 22) e uma assinatura
Claude Max ativa. Baixe o binário do CLIProxyAPI nas
[releases do upstream](https://github.com/router-for-me/CLIProxyAPI/releases) para
`cliproxyapi/bin/` e crie `cliproxyapi/config.yaml` a partir de
`cliproxyapi/config.example.yaml`. O backend tenta subir o binário sozinho no boot
(auto-spawn) quando ele está presente e a opção está ligada; a autenticação OAuth é feita
pelo wizard da própria UI. Alternativamente, suba o proxy à parte.

### Dois processos (hot-reload de frontend)

Backend (terminal 1), de dentro de `backend/`:

```bash
cp .env.example .env        # ajuste se o proxy estiver em outra porta
uv sync
uv run uvicorn app.main:app --reload --port 8400
```

Frontend (terminal 2), de dentro de `frontend/`:

```bash
npm install
npm run dev                 # Vite em :5173, com proxy de /api para :8400
```

Abra **http://localhost:5173**.

### Um processo só (web-local)

```bash
cd frontend && npm run build      # gera frontend/dist/
cd ../backend && uv run uvicorn app.main:app --port 8400
```

Abra **http://localhost:8400**: o FastAPI serve o build do Svelte e a API na mesma origem.

## Configuração

Variáveis principais (defaults em `backend/app/config.py`, overrides em `backend/.env`):

| Variável | Default | Função |
|---|---|---|
| `ANTHROPIC_PROXY_URL` / `ANTHROPIC_PROXY_KEY` | `http://127.0.0.1:8318` / `onepiece-proxy-key` | Endereço e chave do CLIProxyAPI |
| `NARRATOR_MODEL` | `claude-sonnet-5` | Prosa (Narrador e Auditor) |
| `AGENT_MODEL`, `DIRECTOR_MODEL`, `CRYSTALLIZER_MODEL`, `META_ROUTER_MODEL` | `claude-sonnet-5` | Decisão estruturada |
| `AGENT_TEMPERATURE` | `0.7` | Temperatura dos agentes/Diretor (ver nota) |
| `OPRPG_DB_PATH`, `OPRPG_PROMPTS_DIR`, `OPRPG_FRONTEND_DIST` | vazios | Overrides de caminho |

> **Full Sonnet 5.** Todos os papéis rodam em `claude-sonnet-5` com pensamento adaptativo
> (default, on). O Sonnet 5 **rejeita `temperature`/`top_p`/`top_k`** não-padrão (erro 400):
> `proxy/client.py` (`_accepts_temperature`) não envia `temperature` para esse modelo, então
> `AGENT_TEMPERATURE` fica inerte enquanto o modelo for Sonnet 5 (mantido só para reverter a
> um modelo antigo). O `tool_choice` forçado das tools estruturadas convive com o thinking
> adaptativo. O tokenizador do Sonnet 5 gera ~30% mais tokens que o Sonnet 4.6, então o
> orçamento de cache por turn é maior — meça `usage` real no painel de devtools.

## Testes

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q -m "not proxy"   # lógica pura, sem proxy
.venv/Scripts/python.exe -m pytest -q -m proxy          # smokes contra o CLIProxyAPI real
```

A suíte tem 59 arquivos e cerca de 680 testes: lógica determinística (normalizações,
presença, relógio, mapa, rewind, economia, crew) e smokes end-to-end de pipeline com os
modelos reais (marker `proxy`, pulados automaticamente quando o proxy está fora do ar).
E2E de UI via Playwright (`npm run test:e2e` em `frontend/`).

## Operação

Uvicorn roda sem `--reload` em produção; mudança em código Python exige restart manual.
Mudança em prompt/addendum dispensa restart (leitura do disco por chamada).

## Distribuição open source

Cada usuário roda o jogo com a própria assinatura Claude Max; o projeto dispensa chave
compartilhada e backend hospedado. A release oficial entrega o aplicativo desktop e o
código-fonte permanece aberto para quem preferir buildar. Créditos de dados e referências
em [`CREDITS.md`](CREDITS.md).

> O empacotamento precisa incluir, além do shell de janela do aplicativo: o backend
> bundlado, o build do frontend (`frontend/dist/`), a pasta `prompts/` (lida do disco em
> runtime), os dados de mundo e catálogos de `backend/app/db/`, as migrations SQL e o
> binário do CLIProxyAPI com seu `config.yaml`.

## Licença

MIT
