-- Migration 0013 — English overlay columns for the creation catalogs (traits/classes/fruits).
-- The player-visible name/description show on the creation screen and are baked into the player
-- card, so they must follow the UI/campaign language. Populated from docs/{traits,classes,fruits}/
-- catalog.en.md at boot (db/catalog.py, idempotent overlay UPDATE); NULL falls back to the PT-BR
-- column. Catalogs are global to the instance, so both languages live side by side.
ALTER TABLE trait_catalog ADD COLUMN name_en TEXT;
ALTER TABLE trait_catalog ADD COLUMN description_en TEXT;
ALTER TABLE class_catalog ADD COLUMN name_en TEXT;
ALTER TABLE class_catalog ADD COLUMN description_en TEXT;
ALTER TABLE fruit_catalog ADD COLUMN name_en TEXT;
