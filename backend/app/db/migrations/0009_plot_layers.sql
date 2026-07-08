-- Migration 0009 — geração de plot incremental por camadas + plots de mar (FASE 25).
-- Origem: docs/phases/phase-25-layered-plot-generation.md §Modelo de dados.
--
-- plot_json deixa de ser one-shot imutável e vira APPEND-ONLY por camada (quebra controlada:
-- append_plot_layer só estende arrays e grava layers[], nunca reescreve id existente). A chave
-- de lookup deixa de ser só island_slug: anchor_json ancora ilha OU mar com o mesmo motor.
--   locality:    island | sea_self_contained | sea_leads_to_island | sea_multi_location
--   anchor_json: {"kind":"island","slug":...} | {"kind":"sea","crossing_id":...} (+climax_anchor)
--   layers_count: bookkeeping de quantas camadas já foram emitidas (camada 0 = superfície).
-- Backfill legado: plots existentes são esqueletos one-shot de ilha => locality=island,
-- anchor={kind:island,slug=island_slug}, layers_count=1. island_slug fica preenchido ('' p/ mar)
-- pra não quebrar o lookup legado.

ALTER TABLE plots ADD COLUMN locality TEXT NOT NULL DEFAULT 'island';
ALTER TABLE plots ADD COLUMN anchor_json TEXT;
ALTER TABLE plots ADD COLUMN layers_count INTEGER NOT NULL DEFAULT 1;

UPDATE plots
   SET locality = 'island',
       anchor_json = json_object('kind', 'island', 'slug', island_slug)
 WHERE anchor_json IS NULL;
