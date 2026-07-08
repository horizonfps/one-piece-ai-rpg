-- Migration 0007 — snapshot de mundo por turn (Rewind / Regenerar com estado).
-- Origem: revisão pós-FASE 24 (2026-06-10) — a história é do jogador: regenerar um turn
-- deve refazer o MUNDO, não só a prosa. O engine captura o estado completo da campanha
-- ANTES de cada turn DO; rewind = restaurar o snapshot + apagar o turn; regenerar =
-- rewind + re-submeter a mesma ação pelo pipeline inteiro.
--
-- snapshot_json = dump JSON das tabelas mutáveis da campanha (story_cards, crystals,
-- game_clock, game_clock_snapshots, directives, bounty_pending_updates,
-- invented_contexts, plots, plot_states + colunas mutáveis de campaigns). `turns` fica
-- de fora (append-only; o rewind deleta só a linha revertida). Retenção: últimos K
-- snapshots por campanha (poda em world_snapshot.save_snapshot).

CREATE TABLE world_snapshots (
    campaign_id   TEXT NOT NULL,
    turn_index    INTEGER NOT NULL,   -- turn que este snapshot PRECEDE (estado pré-turn)
    snapshot_json TEXT NOT NULL,
    created_at    INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, turn_index),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);
