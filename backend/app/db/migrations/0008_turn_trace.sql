-- Devtools LLM trace persisted per turn (was live-WS only). Each call's input/output
-- so the panel survives reload and the trace can be inspected offline.
ALTER TABLE turns ADD COLUMN trace_json TEXT;
