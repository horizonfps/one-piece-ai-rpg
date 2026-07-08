-- Migration 0006 — fechamento de plot de ilha (FASE 10).
-- Origem: PLANO.md §FASE 10.6/10.7 + docs/phases/phase-08-island-plots.md
--   §"Plot Closure Detector + resolução emergente" ("Campo `closure` em `plot_states`").
--
-- O overlay de descoberta (revealed_*/achieved) já vive em colunas tipadas na 0001. Falta
-- só o DESCRITOR de fechamento do arco — `closure` (kind + matched_resolution_id + summary +
-- loose_ends + reactivable). Segue o JSON escape-hatch das fases recentes (4/5/6/9): uma
-- coluna JSON nullable, não normalização tipada. `null`/ausente = arco ativo; preenchido =
-- arco fechado (resolved_catalogued/resolved_emergent/obsoleted via detector; abandoned via
-- engine na troca de ilha). O `plots.status` da 0001 (generated|active|resolved|abandoned)
-- carrega o estado grosso; o detalhe do fecho mora aqui.

ALTER TABLE plot_states ADD COLUMN closure_json TEXT;
