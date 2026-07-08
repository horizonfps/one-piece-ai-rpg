-- Migration 0001 — schema base.
-- Origem: docs/phases/phase-00-foundation.md §"Schema base do banco" (sessão 5),
-- com os deltas das sessões 10 (plots/briefings) e 15 (endgame) já incorporados,
-- e a tabela `directives` do fechamento da phase-04.
--
-- Princípio: campos lista/aninhados ficam como `_json TEXT` (não normalizar agora);
-- IDs = TEXT (UUID v4); timestamps = INTEGER epoch seconds.
--
-- NOTA: NÃO há virtual table de embeddings/sqlite-vec. Decisão GDD #4 (2026-06-01)
-- dropou vector search do design — a busca de memória/cards (Memory Inspector,
-- phase-06) usa FTS5 nativo, sem embedder. A migration da phase-06 cria `crystals_fts`
-- (FTS5 external-content); NÃO recriar `vec0` aqui nem lá. Ver `docs/phases/decisions.md
-- §Busca & recall de memória`. Hot path não usa busca ("inject all" vence).

-- Pais primeiro (FK aponta pra tabelas já criadas).

CREATE TABLE campaigns (
    id                              TEXT PRIMARY KEY,   -- UUID
    name                            TEXT NOT NULL,
    created_at                      INTEGER NOT NULL,   -- epoch seconds
    current_arc                     TEXT,
    metadata_json                   TEXT,               -- escape hatch
    -- endgame (sessão 15) — nullable = campanha em curso
    campaign_ended_kind             TEXT,               -- pirate_king|yonko|fleet_admiral|revolutionary|conqueror|legendary_vanishing|other
    campaign_ended_at_turn_index    INTEGER,
    campaign_ended_epilogue_summary TEXT
);

-- arcos gerados on-the-fly por ilha (plot_json imutável)
CREATE TABLE plots (
    id               TEXT PRIMARY KEY,
    campaign_id      TEXT NOT NULL,
    island_slug      TEXT NOT NULL,
    generated_at     INTEGER NOT NULL,
    plot_json        TEXT NOT NULL,   -- output cru do Agente Gerador de Arco (imutável)
    status           TEXT NOT NULL,   -- generated | active | resolved | abandoned
    briefing_quality TEXT NOT NULL,   -- ok | degraded (degraded = WebSearch falhou no research)
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- estado mutável por plot (overlay de descoberta + milestones), separado pra manter plot_json imutável
CREATE TABLE plot_states (
    plot_id                  TEXT PRIMARY KEY,
    revealed_placeholders_json TEXT NOT NULL,
    revealed_milestones_json   TEXT NOT NULL,
    revealed_resolutions_json  TEXT NOT NULL,
    planted_hooks_json         TEXT NOT NULL,
    achieved_milestones_json   TEXT NOT NULL,   -- distinto de revealed: evento ocorreu (player pode não ter percebido)
    updated_at_turn_index      INTEGER NOT NULL,
    FOREIGN KEY (plot_id) REFERENCES plots(id)
);

-- append-only por turno
CREATE TABLE turns (
    campaign_id          TEXT NOT NULL,
    turn_index           INTEGER NOT NULL,
    player_input         TEXT NOT NULL,
    narrator_prose       TEXT NOT NULL,
    agent_decisions_json TEXT NOT NULL,   -- turn_state que foi pro narrador
    scene_yaml_snapshot  TEXT,            -- briefing da cena (debug/forense)
    created_at           INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, turn_index),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- cristais (NEW/UPDATED extraídos do narrador)
CREATE TABLE crystals (
    id                        TEXT PRIMARY KEY,   -- UUID, estável entre updates
    campaign_id               TEXT NOT NULL,
    category                  TEXT NOT NULL,      -- character_trait | relationship | event | ...
    subject                   TEXT NOT NULL,
    fact                      TEXT NOT NULL,
    characters_json           TEXT NOT NULL,
    location                  TEXT,
    participants_json         TEXT NOT NULL,
    witnesses_json            TEXT NOT NULL,
    hidden_witnesses_json     TEXT NOT NULL,
    source_turn_index         INTEGER NOT NULL,
    updated_turn_indices_json TEXT NOT NULL,      -- [int, int, ...]
    plot_id                   TEXT,               -- nullable; cristal gerado durante arco aponta pro plot
    created_at                INTEGER NOT NULL,
    updated_at                INTEGER NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
    FOREIGN KEY (plot_id) REFERENCES plots(id)
);

-- game clock estado corrente (1 linha por campanha)
CREATE TABLE game_clock (
    campaign_id                  TEXT PRIMARY KEY,
    campaign_day                 INTEGER NOT NULL,
    current_player_age           INTEGER NOT NULL,
    current_arc                  TEXT,
    active_characters_by_age_json TEXT NOT NULL,
    player_birth_day             INTEGER NOT NULL,
    last_updated_at_turn_index   INTEGER NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- snapshots append-only por turno
CREATE TABLE game_clock_snapshots (
    campaign_id   TEXT NOT NULL,
    turn_index    INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    PRIMARY KEY (campaign_id, turn_index),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- briefing canônico por ilha (GLOBAL — canon é canon, não muda por campanha)
CREATE TABLE canonical_briefings (
    island_slug   TEXT NOT NULL,
    canon_version TEXT NOT NULL,   -- ex: "post-egghead-2026-05"
    briefing_md   TEXT NOT NULL,   -- markdown estruturado (NPCs / eventos / terminologia / conflitos)
    generated_at  INTEGER NOT NULL,
    PRIMARY KEY (island_slug, canon_version)
);

-- contexto de ilha inventada Grand Line (POR CAMPANHA — varia entre runs)
CREATE TABLE invented_contexts (
    campaign_id  TEXT NOT NULL,
    island_slug  TEXT NOT NULL,
    context_json TEXT NOT NULL,   -- {climate_paradigm, geography_hint, fauna_flora_hint, inhabitants_hint, civilization_level}
    generated_at INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, island_slug),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- base do "tudo editável no frontend"
CREATE TABLE story_cards (
    id          TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    kind        TEXT NOT NULL,   -- npc | place | object | skill | ...
    data_json   TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- diretivas META persistentes (fechamento da phase-04)
CREATE TABLE directives (
    id                TEXT PRIMARY KEY,
    campaign_id       TEXT NOT NULL,
    text              TEXT NOT NULL,
    active            INTEGER NOT NULL DEFAULT 1,
    source_turn_index INTEGER,
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- Índices secundários óbvios (os mais quentes; refinar quando a query exigir).
CREATE INDEX idx_turns_campaign        ON turns(campaign_id);
CREATE INDEX idx_crystals_campaign     ON crystals(campaign_id);
CREATE INDEX idx_crystals_plot         ON crystals(plot_id);
CREATE INDEX idx_plots_campaign        ON plots(campaign_id);
CREATE INDEX idx_story_cards_campaign  ON story_cards(campaign_id, kind);
CREATE INDEX idx_directives_campaign   ON directives(campaign_id, active);
