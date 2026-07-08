-- Migration 0003 — busca textual FTS5 (FASE 6.5).
-- Origem: PLANO.md §FASE 6.5 + docs/phases/decisions.md §"Busca & recall de memória" (Decisão GDD #4,
-- 2026-06-01). Vector search (`sqlite-vec`/embeddings) saiu do stack; a busca de cristais (Memory
-- Inspector) e o recall de cards usam FTS5 NATIVO — keyword + filtros, sem embedder.
--
-- Rótulo: o PLANO chama de "0005" (alvo nominal), mas o número real é o próximo .sql na pasta = 0003.
-- O runner (migrate.py) tolera buracos (só roda versão > user_version), então aplicar este bumpa
-- user_version de 2 → 3. (Não há 0003/0004 antigos: FASE 4/5 usaram JSON escape-hatch.)
--
-- Padrão: FTS5 external-content (content='<tabela>', content_rowid='rowid') + triggers de sync.
-- Não copia o texto (só o índice invertido); a query faz JOIN no rowid pra trazer a linha real.
-- Tokenizer `unicode61 remove_diacritics 2` → busca PT-BR insensível a acento ("joao" acha "João").

-- ── crystals: indexa as colunas de texto livre (filtros estruturados ficam no WHERE do JOIN) ──
CREATE VIRTUAL TABLE crystals_fts USING fts5(
    subject,
    fact,
    location,
    category,
    content='crystals',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER crystals_fts_ai AFTER INSERT ON crystals BEGIN
    INSERT INTO crystals_fts(rowid, subject, fact, location, category)
    VALUES (new.rowid, new.subject, new.fact, new.location, new.category);
END;

CREATE TRIGGER crystals_fts_ad AFTER DELETE ON crystals BEGIN
    INSERT INTO crystals_fts(crystals_fts, rowid, subject, fact, location, category)
    VALUES ('delete', old.rowid, old.subject, old.fact, old.location, old.category);
END;

CREATE TRIGGER crystals_fts_au AFTER UPDATE ON crystals BEGIN
    INSERT INTO crystals_fts(crystals_fts, rowid, subject, fact, location, category)
    VALUES ('delete', old.rowid, old.subject, old.fact, old.location, old.category);
    INSERT INTO crystals_fts(rowid, subject, fact, location, category)
    VALUES (new.rowid, new.subject, new.fact, new.location, new.category);
END;

-- ── story_cards: o texto buscável (name/aliases/description/summary) vive no data_json (escape-hatch
-- da 0001), então indexamos o JSON inteiro. Keyword acha os campos; chaves do JSON viram ruído leve
-- aceitável pro inspector (Decisão GDD #4: busca não é hot path). Filtro por kind fica no WHERE. ──
CREATE VIRTUAL TABLE cards_fts USING fts5(
    data_json,
    content='story_cards',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER cards_fts_ai AFTER INSERT ON story_cards BEGIN
    INSERT INTO cards_fts(rowid, data_json) VALUES (new.rowid, new.data_json);
END;

CREATE TRIGGER cards_fts_ad AFTER DELETE ON story_cards BEGIN
    INSERT INTO cards_fts(cards_fts, rowid, data_json) VALUES ('delete', old.rowid, old.data_json);
END;

CREATE TRIGGER cards_fts_au AFTER UPDATE ON story_cards BEGIN
    INSERT INTO cards_fts(cards_fts, rowid, data_json) VALUES ('delete', old.rowid, old.data_json);
    INSERT INTO cards_fts(rowid, data_json) VALUES (new.rowid, new.data_json);
END;

-- Indexa o que já existe (campanhas/cristais criados antes desta migration).
INSERT INTO crystals_fts(crystals_fts) VALUES ('rebuild');
INSERT INTO cards_fts(cards_fts) VALUES ('rebuild');
