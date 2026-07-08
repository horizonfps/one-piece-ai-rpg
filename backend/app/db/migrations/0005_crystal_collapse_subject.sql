-- Migration 0005 — Cristais por cena: colapsa subject→fact (cristal = uma linha só).
-- Sessão 35 (2026-06-02): o cristalizador passa a disparar por CENA (o narrador sinaliza
-- `scene_status` no turn_meta; o runner acumula a prosa até `fecha` ou o cap de 8 turns) e
-- cada cristal vira UMA frase seca, sem o par redundante subject+fact — o `fact` longo era
-- recap da ação (vício). O `subject` (título conciso) absorve o papel do cristal; a coluna
-- `subject` sai. Ver crystallizer_system_prompt (v8) + docs/phases.
--
-- A FTS5 é external-content e os triggers referenciam `subject`; por isso derruba a FTS +
-- triggers ANTES do DROP COLUMN, e recria sem `subject` depois.

-- 1. Derruba triggers + a tabela FTS (referenciam a coluna subject).
DROP TRIGGER IF EXISTS crystals_fts_ai;
DROP TRIGGER IF EXISTS crystals_fts_ad;
DROP TRIGGER IF EXISTS crystals_fts_au;
DROP TABLE IF EXISTS crystals_fts;

-- 2. Cristais legados: a linha concisa (subject) vira o fact único.
UPDATE crystals SET fact = subject WHERE subject IS NOT NULL AND TRIM(subject) <> '';

-- 3. Remove a coluna redundante (SQLite >= 3.35 suporta DROP COLUMN).
ALTER TABLE crystals DROP COLUMN subject;

-- 4. Recria a FTS sem subject + triggers de sync (mesmo padrão da 0003).
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

-- 5. Reindexa os cristais já existentes.
INSERT INTO crystals_fts(crystals_fts) VALUES ('rebuild');
