-- Migration 0012 — per-campaign prose language, frozen at creation.
ALTER TABLE campaigns ADD COLUMN language TEXT NOT NULL DEFAULT 'pt-br';
