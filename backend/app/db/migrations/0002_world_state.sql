-- Migration 0002 — estado de mundo do post-turn (FASE 3).
-- Origem: PLANO.md §FASE 3.1 + docs/phases/decisions.md §"Diretor — Post-turn".
--
-- Decisão (sessão 23, 2026-05-30): alignment/bounty vivem no `player_snapshot` do
-- story_card 'player'; chaos_meter/crew_alignment/events_background vivem no
-- `campaigns.metadata_json`; day_counter já vive em `game_clock.campaign_day`. Tudo
-- JSON escape-hatch (princípio "não normalizar agora" da 0001). A camada de acesso
-- (`repositories.get_world_state`) normaliza defaults no read — campanhas antigas
-- não precisam de backfill SQL.
--
-- A ÚNICA estrutura nova é `bounty_pending_updates`: bounty sobe com delay narrativo
-- (1-3 dias, decisions.md §"Sem heroísmo de mundo" + director_bounty_addendum §4).
-- O Diretor emite `bounty_delta { tier }`; o engine sorteia o número no range da
-- faixa e AGENDA aqui; o avanço de `day_counter` (FASE 9) aplica quando vence.

CREATE TABLE bounty_pending_updates (
    id                TEXT PRIMARY KEY,   -- UUID hex
    campaign_id       TEXT NOT NULL,
    target            TEXT NOT NULL,      -- 'player' | char_id de crewmate
    tier              TEXT NOT NULL,      -- small | medium | large | massive | absurd
    delta             INTEGER NOT NULL,   -- número sorteado no range da tier (beli)
    reason            TEXT NOT NULL,
    source            TEXT NOT NULL,      -- 'action' (raro: 'world_event')
    source_turn_index INTEGER NOT NULL,
    scheduled_day     INTEGER NOT NULL,   -- day_counter alvo (= dia da emissão + uniform(1,3))
    applied           INTEGER NOT NULL DEFAULT 0,   -- 0 pendente, 1 aplicado
    applied_at_day    INTEGER,
    created_at        INTEGER NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- Hot path: "quais updates desta campanha venceram e ainda não aplicaram".
CREATE INDEX idx_bounty_pending_due
    ON bounty_pending_updates(campaign_id, applied, scheduled_day);

-- Output cru do post-turn por turno (deltas/eventos/jobs/warnings + report do executor).
-- Durável pra replay/inspector e pra fases futuras consumirem dispatched_jobs/edit_primitives
-- que a FASE 3 ainda não executa. nullable = turns anteriores ao post-turn.
ALTER TABLE turns ADD COLUMN post_turn_json TEXT;
