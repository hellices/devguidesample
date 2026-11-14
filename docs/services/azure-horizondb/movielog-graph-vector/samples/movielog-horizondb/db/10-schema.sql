-- Run as the HorizonDB administrator against the "movielog" database.
-- The parameter group must allow these extensions (azure.extensions=vector,pg_diskann,age) and
-- preload AGE (shared_preload_libraries=age) before this script runs.
\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_diskann;
CREATE EXTENSION IF NOT EXISTS age;

-- Hibernate (ddl-auto=update) creates the application tables in public as the app role.
GRANT USAGE, CREATE ON SCHEMA public TO movielog;

CREATE SCHEMA IF NOT EXISTS catalog;

CREATE TABLE IF NOT EXISTS catalog.people (
	qid text PRIMARY KEY,
	name text NOT NULL,
	name_en text,
	sitelinks integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS catalog.movie_credits (
	tmdb_id bigint NOT NULL,
	person_qid text NOT NULL REFERENCES catalog.people (qid),
	role text NOT NULL CHECK (role IN ('director', 'actor')),
	position integer NOT NULL,
	PRIMARY KEY (tmdb_id, person_qid, role)
);

CREATE TABLE IF NOT EXISTS catalog.movie_genres (
	tmdb_id bigint NOT NULL,
	genre text NOT NULL,
	PRIMARY KEY (tmdb_id, genre)
);

-- One embedded document per movie: text-embedding-3-large shortened to 1,536 dimensions;
-- data/embed_catalog.py fills embedding for rows where it is NULL.
CREATE TABLE IF NOT EXISTS catalog.movie_docs (
	tmdb_id bigint PRIMARY KEY,
	wikidata_qid text,
	doc text NOT NULL,
	overview text,
	source_url text,
	summary_en_source text,
	embedding vector(1536),
	embedded_at timestamptz
);
-- Databases created before the English lead source was recorded.
ALTER TABLE catalog.movie_docs ADD COLUMN IF NOT EXISTS summary_en_source text;
-- The shown Wikipedia summary next to its source_url, so attribution stays with this text even after the app
-- refreshes public.movies.overview from TMDB.
ALTER TABLE catalog.movie_docs ADD COLUMN IF NOT EXISTS overview text;

GRANT USAGE ON SCHEMA catalog TO movielog;
GRANT SELECT ON ALL TABLES IN SCHEMA catalog TO movielog;
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT SELECT ON TABLES TO movielog;
-- The app embeds movies that members import from TMDB after the catalog load (CatalogIndexer).
GRANT INSERT ON catalog.movie_docs TO movielog;

-- openCypher queries through ag_catalog.cypher().
GRANT USAGE ON SCHEMA ag_catalog TO movielog;
