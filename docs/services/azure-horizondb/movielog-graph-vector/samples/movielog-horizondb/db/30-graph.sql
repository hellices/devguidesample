-- Run as the HorizonDB administrator against the "movielog" database after 20-vector-index.sql.
-- Rebuilds the Apache AGE graph "movie_graph" from the relational catalog:
--   (:Person)-[:DIRECTED]->(:Movie), (:Person)-[:ACTED_IN {position}]->(:Movie),
--   (:Movie)-[:IN_GENRE]->(:Genre), (:Movie)-[:SIMILAR_TO {score}]->(:Movie)
-- SIMILAR_TO links each movie to its 3 nearest neighbors by embedding (cosine). Run it for the first build or to
-- start over; afterwards 40-graph-sync.sql keeps the graph current without dropping it.
\set ON_ERROR_STOP on

SET search_path = ag_catalog, "$user", public;

-- Same lock as catalog.process_graph_queue (40-graph-sync.sql), so the app does not update the graph while it is
-- rebuilt. Changes queued before this point are covered by the rebuild and cleared at the end.
SELECT pg_advisory_lock(30810959134158952);
SELECT clock_timestamp() AS rebuild_started \gset

SELECT drop_graph('movie_graph', true) FROM ag_graph WHERE name = 'movie_graph';
SELECT create_graph('movie_graph');

-- Grant before the label tables exist so the app reads a partial graph during a rebuild
-- instead of failing with "permission denied for schema movie_graph".
GRANT USAGE ON SCHEMA movie_graph TO movielog;
ALTER DEFAULT PRIVILEGES IN SCHEMA movie_graph GRANT SELECT ON TABLES TO movielog;

-- Cypher string literal for arbitrary text.
CREATE FUNCTION pg_temp.cy(value text) RETURNS text LANGUAGE sql IMMUTABLE
AS $fn$ SELECT '"' || replace(replace(coalesce(value, ''), '\', '\\'), '"', '\"') || '"' $fn$;

-- Runs one UNWIND statement per batch of 200 map literals. AGE takes the Cypher text only as a dollar-quoted
-- constant, so each batch uses a tag that does not occur in its text; data containing "$cy$" cannot end it early.
CREATE FUNCTION pg_temp.unwind(items text[], statement text) RETURNS integer LANGUAGE plpgsql
AS $fn$
DECLARE
	i integer := 1;
	batches integer := 0;
	body text;
	tag text;
BEGIN
	WHILE i <= coalesce(array_length(items, 1), 0) LOOP
		body := format('UNWIND [%s] AS e %s', array_to_string(items[i:i + 199], ', '), statement);
		LOOP
			tag := '$cy' || substr(md5(random()::text), 1, 12) || '$';
			EXIT WHEN position(tag IN body) = 0;
		END LOOP;
		EXECUTE format('SELECT * FROM ag_catalog.cypher(''movie_graph'', %s%s%s) AS (v ag_catalog.agtype)', tag, body, tag);
		i := i + 200;
		batches := batches + 1;
	END LOOP;
	RETURN batches;
END
$fn$;

SELECT pg_temp.unwind(array_agg(format('{tmdb_id: %s, title: %s, year: %s}', m.tmdb_id, pg_temp.cy(m.title),
		coalesce(extract(year FROM m.release_date)::int::text, 'null'))),
	'CREATE (:Movie {tmdb_id: e.tmdb_id, title: e.title, year: e.year})') AS movie_batches
FROM public.movies m;

SELECT pg_temp.unwind(array_agg(format('{qid: %s, name: %s}', pg_temp.cy(p.qid), pg_temp.cy(p.name))),
	'CREATE (:Person {qid: e.qid, name: e.name})') AS person_batches
FROM catalog.people p
WHERE EXISTS (SELECT 1 FROM catalog.movie_credits c JOIN public.movies m USING (tmdb_id) WHERE c.person_qid = p.qid);

SELECT pg_temp.unwind(array_agg(format('{name: %s}', pg_temp.cy(g.genre))),
	'CREATE (:Genre {name: e.name})') AS genre_batches
FROM (SELECT DISTINCT genre FROM catalog.movie_genres JOIN public.movies USING (tmdb_id)) g;

-- GIN indexes let MATCH (n:Label {key: value}) use containment lookups while edges are created.
CREATE INDEX ON movie_graph."Movie" USING gin (properties);
CREATE INDEX ON movie_graph."Person" USING gin (properties);
CREATE INDEX ON movie_graph."Genre" USING gin (properties);

SELECT pg_temp.unwind(array_agg(format('{p: %s, m: %s}', pg_temp.cy(c.person_qid), c.tmdb_id)),
	'MATCH (p:Person {qid: e.p}), (m:Movie {tmdb_id: e.m}) CREATE (p)-[:DIRECTED]->(m)') AS directed_batches
FROM catalog.movie_credits c JOIN public.movies USING (tmdb_id)
WHERE c.role = 'director';

SELECT pg_temp.unwind(array_agg(format('{p: %s, m: %s, position: %s}', pg_temp.cy(c.person_qid), c.tmdb_id, c.position)),
	'MATCH (p:Person {qid: e.p}), (m:Movie {tmdb_id: e.m}) CREATE (p)-[:ACTED_IN {position: e.position}]->(m)') AS acted_batches
FROM catalog.movie_credits c JOIN public.movies USING (tmdb_id)
WHERE c.role = 'actor';

SELECT pg_temp.unwind(array_agg(format('{m: %s, g: %s}', g.tmdb_id, pg_temp.cy(g.genre))),
	'MATCH (m:Movie {tmdb_id: e.m}), (g:Genre {name: e.g}) CREATE (m)-[:IN_GENRE]->(g)') AS genre_edge_batches
FROM catalog.movie_genres g JOIN public.movies USING (tmdb_id);

-- One undirected pair per neighbor relation, scored by cosine similarity.
WITH knn AS (
	SELECT a.tmdb_id AS a, b.tmdb_id AS b, 1 - (a.embedding <=> b.embedding) AS score
	FROM catalog.movie_docs a
	CROSS JOIN LATERAL (
		SELECT tmdb_id, embedding FROM catalog.movie_docs b
		WHERE b.tmdb_id <> a.tmdb_id AND b.embedding IS NOT NULL
		ORDER BY b.embedding <=> a.embedding
		LIMIT 3
	) b
	WHERE a.embedding IS NOT NULL
), pairs AS (
	SELECT DISTINCT ON (least(a, b), greatest(a, b)) least(a, b) AS a, greatest(a, b) AS b, round(score::numeric, 4) AS score
	FROM knn
	ORDER BY least(a, b), greatest(a, b), score DESC
)
SELECT pg_temp.unwind(array_agg(format('{a: %s, b: %s, score: %s}', a, b, score)),
	'MATCH (a:Movie {tmdb_id: e.a}), (b:Movie {tmdb_id: e.b}) CREATE (a)-[:SIMILAR_TO {score: e.score}]->(b)') AS similar_batches
FROM pairs
WHERE EXISTS (SELECT 1 FROM public.movies m WHERE m.tmdb_id = pairs.a)
	AND EXISTS (SELECT 1 FROM public.movies m WHERE m.tmdb_id = pairs.b);

-- AGE creates btree indexes on start_id and end_id with each edge label table, so traversal needs no extra index.

-- Tables created by create_graph itself (_ag_label_vertex, _ag_label_edge) predate the default privileges.
GRANT SELECT ON ALL TABLES IN SCHEMA movie_graph TO movielog;

SELECT * FROM ag_catalog.cypher('movie_graph', $cy$
	MATCH (n) RETURN label(n), count(*)
$cy$) AS (label ag_catalog.agtype, nodes ag_catalog.agtype);

SELECT * FROM ag_catalog.cypher('movie_graph', $cy$
	MATCH ()-[r]->() RETURN type(r), count(*)
$cy$) AS (type ag_catalog.agtype, edges ag_catalog.agtype);

SELECT set_config('movielog.rebuild_started', :'rebuild_started', false);
DO $do$
BEGIN
	IF to_regclass('catalog.graph_queue') IS NOT NULL THEN
		DELETE FROM catalog.graph_queue WHERE queued_at < current_setting('movielog.rebuild_started')::timestamptz;
	END IF;
END
$do$;
SELECT pg_advisory_unlock(30810959134158952);
