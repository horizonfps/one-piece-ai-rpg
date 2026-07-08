-- Migration 0010 — vínculo placeholder -> card (FASE 28, Item 5: elenco unificado).
-- Origem: docs/phases/phase-28-plot-slimming-and-cast-unification.md §Item 5.
--
-- O placeholder do plot vira um card preguiçoso: texto barato enquanto ninguém encosta,
-- materializado em npc_agent quando entra em cena (promoção do Diretor no PRE, ou reconciliação
-- do gerador na prosa). O vínculo placeholder_id -> card_id mora no overlay mutável (plot_states),
-- JSON nullable como closure_json. null/ausente = nenhum placeholder instanciado ainda;
-- {"ant_02":"<uuid>"} = ant_02 já virou o card <uuid>, e o gerador para de cunhar gente nova ali.

ALTER TABLE plot_states ADD COLUMN placeholder_card_bindings_json TEXT;
