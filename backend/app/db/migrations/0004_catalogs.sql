-- Migration 0004 — catálogos de criação de personagem (FASE 7.1).
-- Origem: PLANO.md §FASE 7.1 + decisão de impl 2026-06-01 ("catálogos importados pro SQLite no boot
-- a partir dos YAMLs"). Os três catálogos são curados em docs/{traits,classes,fruits}/catalog.md
-- (bloco "## Catálogo (YAML — importável)"); o importador (db/catalog.py) faz upsert por id no boot.
--
-- Rótulo: o PLANO chama de "0006" (alvo nominal), mas o número real é o próximo .sql na pasta = 0004.
-- O runner (migrate.py) tolera buracos (só roda versão > user_version) → aplicar bumpa user_version 3 → 4.
-- (Não há 0004/0005 antigos: FASE 5/6 usaram JSON escape-hatch; o player da FASE 7 idem — sem coluna
-- tipada pro player, só estas tabelas de catálogo, globais à instância, não por campanha.)
--
-- Listas (state_hooks, starting_loadout, starting_techniques) ficam em colunas *_json TEXT, igual ao
-- padrão da 0001. Catálogos são read-mostly; edição via frontend (FASE 23) reescreve a linha.

-- ── traits (53) ──
CREATE TABLE trait_catalog (
    id                 TEXT PRIMARY KEY,           -- slug snake_case, estável
    name               TEXT NOT NULL,              -- display PT-BR
    bucket             TEXT NOT NULL,              -- lineage|personality|body|constitution|luck|sensory|health
    polarity           TEXT NOT NULL,              -- positive|negative
    rarity             TEXT NOT NULL,              -- common|rare|epic|legendary
    stacking_exclusion TEXT,                       -- group id (ex: genio_haki) ou NULL
    canon_anchor       TEXT,                       -- nota ou NULL
    description        TEXT NOT NULL,
    state_hooks_json   TEXT NOT NULL DEFAULT '[]'
);

-- ── classes (15) ──
CREATE TABLE class_catalog (
    id                       TEXT PRIMARY KEY,      -- kebab-case
    name                     TEXT NOT NULL,
    archetype                TEXT NOT NULL,         -- combat|support|hybrid|none
    description              TEXT NOT NULL,
    starting_loadout_json    TEXT NOT NULL DEFAULT '[]',
    starting_techniques_json TEXT NOT NULL DEFAULT '[]',
    progression_vector       TEXT,
    fruit_dependency         TEXT NOT NULL,         -- none|bonus|central
    notes                    TEXT
);

-- ── frutas (28) ── ("Sem Fruta" NÃO é linha: corresponde a devil_fruit = null na ficha) ──
CREATE TABLE fruit_catalog (
    id           TEXT PRIMARY KEY,                  -- kebab-case
    name_jp      TEXT NOT NULL,
    name_pt      TEXT,
    type         TEXT NOT NULL,                     -- Logia|Paramecia|Zoan|Mythical Zoan|...
    canon_owner  TEXT,
    tier         TEXT NOT NULL,                     -- S|A|B
    removal_hook TEXT,                              -- injetado no Narrador SÓ se a fruta for escolhida
    arc_unlock   TEXT
);
