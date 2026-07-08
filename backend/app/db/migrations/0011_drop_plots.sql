-- Migration 0011 — retire the plot tables (the generated-plot system died in FASE 29).
-- The island is born neutral now; mid-term continuity lives in metadata.foreshadow_pool (threads)
-- and canonical research stays in canonical_briefings. crystals.plot_id had a FK into plots; a
-- bare DROP would leave that FK dangling and every crystal INSERT would fail ("no such table:
-- plots") with foreign_keys=ON. So rebuild crystals without plot_id (post-29 no crystal is tied to
-- a plot), preserving rowids and the external-content FTS index, then drop plot_states + plots.

PRAGMA foreign_keys=OFF;

-- The rebuild runs in one transaction (atomic rollback on failure); the foreign_keys pragmas
-- stay outside it (a no-op inside a transaction).
BEGIN;

-- FTS sync triggers + index are recreated after the rebuild.
DROP TRIGGER IF EXISTS crystals_fts_ai;
DROP TRIGGER IF EXISTS crystals_fts_ad;
DROP TRIGGER IF EXISTS crystals_fts_au;
DROP TABLE IF EXISTS crystals_fts;

ALTER TABLE crystals RENAME TO crystals_old;

CREATE TABLE crystals (
    id                        TEXT PRIMARY KEY,
    campaign_id               TEXT NOT NULL,
    category                  TEXT NOT NULL,
    fact                      TEXT NOT NULL,
    characters_json           TEXT NOT NULL,
    location                  TEXT,
    participants_json         TEXT NOT NULL,
    witnesses_json            TEXT NOT NULL,
    hidden_witnesses_json     TEXT NOT NULL,
    source_turn_index         INTEGER NOT NULL,
    updated_turn_indices_json TEXT NOT NULL,
    created_at                INTEGER NOT NULL,
    updated_at                INTEGER NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

INSERT INTO crystals (rowid, id, campaign_id, category, fact, characters_json, location,
    participants_json, witnesses_json, hidden_witnesses_json, source_turn_index,
    updated_turn_indices_json, created_at, updated_at)
SELECT rowid, id, campaign_id, category, fact, characters_json, location,
    participants_json, witnesses_json, hidden_witnesses_json, source_turn_index,
    updated_turn_indices_json, created_at, updated_at
FROM crystals_old;

DROP TABLE crystals_old;

CREATE INDEX idx_crystals_campaign ON crystals(campaign_id);

CREATE VIRTUAL TABLE crystals_fts USING fts5(
    fact,
    location,
    category,
    content='crystals',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER crystals_fts_ai AFTER INSERT ON crystals BEGIN
    INSERT INTO crystals_fts(rowid, fact, location, category)
    VALUES (new.rowid, new.fact, new.location, new.category);
END;
CREATE TRIGGER crystals_fts_ad AFTER DELETE ON crystals BEGIN
    INSERT INTO crystals_fts(crystals_fts, rowid, fact, location, category)
    VALUES ('delete', old.rowid, old.fact, old.location, old.category);
END;
CREATE TRIGGER crystals_fts_au AFTER UPDATE ON crystals BEGIN
    INSERT INTO crystals_fts(crystals_fts, rowid, fact, location, category)
    VALUES ('delete', old.rowid, old.fact, old.location, old.category);
    INSERT INTO crystals_fts(rowid, fact, location, category)
    VALUES (new.rowid, new.fact, new.location, new.category);
END;

INSERT INTO crystals_fts(crystals_fts) VALUES('rebuild');

DROP TABLE IF EXISTS plot_states;
DROP TABLE IF EXISTS plots;

COMMIT;

PRAGMA foreign_keys=ON;
