-- 0002: full-text lexemes for hybrid retrieval (ADR-0014).
-- 'simple' config: lowercased words, no stemming or stopwords, diacritics kept, because
-- Postgres has no Vietnamese dictionary and the corpus is bilingual.

ALTER TABLE chunks ADD COLUMN lexemes tsvector;

UPDATE chunks c
SET lexemes = to_tsvector('simple', concat_ws(' ', d.title, c.section, c.text))
FROM documents d
WHERE d.tenant_id = c.tenant_id AND d.id = c.document_id AND d.version = c.document_version;

ALTER TABLE chunks ALTER COLUMN lexemes SET NOT NULL;

CREATE INDEX chunks_lexemes_idx ON chunks USING gin (lexemes);
