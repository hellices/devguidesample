-- Run as the HorizonDB administrator against the "movielog" database after 30-graph.sql. Re-running is safe.
-- Keeps the AGE graph "movie_graph" in step with the relational rows without a full rebuild:
--   1. Triggers on public.movies and the catalog tables queue the tmdb_id of every changed movie
--      in catalog.graph_queue (a person's rename queues all of that person's movies).
--   2. catalog.process_graph_queue() rebuilds the queued movies' Movie node and their DIRECTED, ACTED_IN and
--      IN_GENRE edges by the rules of 30-graph.sql, then reconciles every SIMILAR_TO pair against the embeddings,
--      because one changed movie can change the 3 nearest neighbors of others. All of it is one transaction, so
--      readers never see a half-built graph.
--   3. catalog.enqueue_graph_drift() queues movies that exist on only one side (relational rows or graph).
-- The app calls 2 every 30 seconds and 3 every hour. The app role gets EXECUTE on these two functions only and
-- cannot write the graph tables directly.
\set ON_ERROR_STOP on

-- The per-movie function of the previous version; the queue replaces it.
DROP FUNCTION IF EXISTS catalog.sync_movie_graph(bigint);

CREATE TABLE IF NOT EXISTS catalog.graph_queue (
	tmdb_id bigint PRIMARY KEY,
	queued_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Cypher string literal for arbitrary text.
CREATE OR REPLACE FUNCTION catalog.cypher_literal(value text) RETURNS text LANGUAGE sql IMMUTABLE
AS $fn$ SELECT '"' || replace(replace(coalesce(value, ''), '\', '\\'), '"', '\"') || '"' $fn$;

-- Runs one Cypher statement. AGE takes the Cypher text only as a dollar-quoted constant, so the tag is chosen
-- to not occur in the statement.
CREATE OR REPLACE FUNCTION catalog.run_cypher(statement text) RETURNS void LANGUAGE plpgsql
SET search_path = ag_catalog, pg_catalog
AS $fn$
DECLARE
	tag text;
BEGIN
	LOOP
		tag := '$cy' || substr(md5(random()::text), 1, 12) || '$';
		EXIT WHEN position(tag IN statement) = 0;
	END LOOP;
	EXECUTE format('SELECT * FROM ag_catalog.cypher(''movie_graph'', %s%s%s) AS (v ag_catalog.agtype)', tag, statement, tag);
END
$fn$;

-- Trigger function: queues the movie of the changed row. A later change moves queued_at forward, so a full
-- rebuild (30-graph.sql) clears only entries queued before it started.
CREATE OR REPLACE FUNCTION catalog.queue_graph_change() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog
AS $fn$
DECLARE
	row_data record := CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
BEGIN
	IF TG_TABLE_NAME = 'people' THEN
		INSERT INTO catalog.graph_queue (tmdb_id)
		SELECT DISTINCT tmdb_id FROM catalog.movie_credits WHERE person_qid = row_data.qid
		ON CONFLICT (tmdb_id) DO UPDATE SET queued_at = excluded.queued_at;
	ELSE
		INSERT INTO catalog.graph_queue (tmdb_id) VALUES (row_data.tmdb_id)
		ON CONFLICT (tmdb_id) DO UPDATE SET queued_at = excluded.queued_at;
		IF TG_OP = 'UPDATE' AND OLD.tmdb_id IS DISTINCT FROM NEW.tmdb_id THEN
			INSERT INTO catalog.graph_queue (tmdb_id) VALUES (OLD.tmdb_id)
			ON CONFLICT (tmdb_id) DO UPDATE SET queued_at = excluded.queued_at;
		END IF;
	END IF;
	RETURN NULL;
END
$fn$;

-- Only changes that alter the graph are queued: the app updates other columns of public.movies on every
-- TMDB refresh, and the catalog loader upserts unchanged people.
DROP TRIGGER IF EXISTS graph_queue_change ON public.movies;
CREATE TRIGGER graph_queue_change AFTER INSERT OR DELETE ON public.movies
	FOR EACH ROW EXECUTE FUNCTION catalog.queue_graph_change();
DROP TRIGGER IF EXISTS graph_queue_update ON public.movies;
CREATE TRIGGER graph_queue_update AFTER UPDATE OF tmdb_id, title, release_date ON public.movies
	FOR EACH ROW WHEN (OLD.tmdb_id IS DISTINCT FROM NEW.tmdb_id OR OLD.title IS DISTINCT FROM NEW.title
		OR OLD.release_date IS DISTINCT FROM NEW.release_date)
	EXECUTE FUNCTION catalog.queue_graph_change();
DROP TRIGGER IF EXISTS graph_queue_change ON catalog.movie_docs;
CREATE TRIGGER graph_queue_change AFTER INSERT OR DELETE ON catalog.movie_docs
	FOR EACH ROW EXECUTE FUNCTION catalog.queue_graph_change();
DROP TRIGGER IF EXISTS graph_queue_update ON catalog.movie_docs;
CREATE TRIGGER graph_queue_update AFTER UPDATE OF embedding ON catalog.movie_docs
	FOR EACH ROW WHEN (OLD.embedding IS DISTINCT FROM NEW.embedding)
	EXECUTE FUNCTION catalog.queue_graph_change();
DROP TRIGGER IF EXISTS graph_queue_change ON catalog.movie_credits;
CREATE TRIGGER graph_queue_change AFTER INSERT OR UPDATE OR DELETE ON catalog.movie_credits
	FOR EACH ROW EXECUTE FUNCTION catalog.queue_graph_change();
DROP TRIGGER IF EXISTS graph_queue_change ON catalog.movie_genres;
CREATE TRIGGER graph_queue_change AFTER INSERT OR UPDATE OR DELETE ON catalog.movie_genres
	FOR EACH ROW EXECUTE FUNCTION catalog.queue_graph_change();
DROP TRIGGER IF EXISTS graph_queue_update ON catalog.people;
CREATE TRIGGER graph_queue_update AFTER UPDATE OF name ON catalog.people
	FOR EACH ROW WHEN (OLD.name IS DISTINCT FROM NEW.name)
	EXECUTE FUNCTION catalog.queue_graph_change();

-- Rebuilds one Movie node and its Person and Genre edges like 30-graph.sql. DETACH DELETE also drops the movie's
-- SIMILAR_TO edges; catalog.reconcile_similar_to() restores them. People and genres left without any edge are
-- removed, as 30-graph.sql creates only those with a credit.
CREATE OR REPLACE FUNCTION catalog.sync_movie_node(p_tmdb_id bigint) RETURNS void LANGUAGE plpgsql
SET search_path = ag_catalog, pg_catalog
AS $fn$
DECLARE
	r record;
	old_people text[];
	old_genres text[];
BEGIN
	-- agtype text of a string is a Cypher string literal ("Q548823"), ready for the cleanup lists below.
	EXECUTE format($q$
		SELECT array_agg(key::text) FILTER (WHERE kind::text = '"Person"'),
		       array_agg(key::text) FILTER (WHERE kind::text = '"Genre"')
		FROM ag_catalog.cypher('movie_graph', $cy$
			MATCH (m:Movie {tmdb_id: %s})-[]-(n) WHERE label(n) <> 'Movie' RETURN label(n), coalesce(n.qid, n.name)
		$cy$) AS (kind ag_catalog.agtype, key ag_catalog.agtype)$q$, p_tmdb_id)
	INTO old_people, old_genres;
	PERFORM catalog.run_cypher(format('MATCH (m:Movie {tmdb_id: %s}) DETACH DELETE m', p_tmdb_id));

	SELECT m.tmdb_id, m.title, extract(year FROM m.release_date)::int AS year INTO r
	FROM public.movies m WHERE m.tmdb_id = p_tmdb_id;
	IF FOUND THEN
		PERFORM catalog.run_cypher(format('CREATE (:Movie {tmdb_id: %s, title: %s, year: %s})',
			r.tmdb_id, catalog.cypher_literal(r.title), coalesce(r.year::text, 'null')));
		FOR r IN SELECT DISTINCT genre FROM catalog.movie_genres WHERE tmdb_id = p_tmdb_id LOOP
			PERFORM catalog.run_cypher(format('MERGE (:Genre {name: %s})', catalog.cypher_literal(r.genre)));
			PERFORM catalog.run_cypher(format(
				'MATCH (m:Movie {tmdb_id: %s}), (g:Genre {name: %s}) CREATE (m)-[:IN_GENRE]->(g)',
				p_tmdb_id, catalog.cypher_literal(r.genre)));
		END LOOP;
		FOR r IN
			SELECT c.person_qid, c.role, c.position, p.name
			FROM catalog.movie_credits c JOIN catalog.people p ON p.qid = c.person_qid
			WHERE c.tmdb_id = p_tmdb_id
			ORDER BY c.position
		LOOP
			-- SET keeps a renamed person's single node up to date.
			PERFORM catalog.run_cypher(format('MERGE (p:Person {qid: %s}) SET p.name = %s',
				catalog.cypher_literal(r.person_qid), catalog.cypher_literal(r.name)));
			PERFORM catalog.run_cypher(format(
				'MATCH (p:Person {qid: %s}), (m:Movie {tmdb_id: %s}) CREATE (p)-[:%s]->(m)',
				catalog.cypher_literal(r.person_qid), p_tmdb_id,
				CASE WHEN r.role = 'director' THEN 'DIRECTED' ELSE format('ACTED_IN {position: %s}', r.position) END));
		END LOOP;
	END IF;

	IF old_people IS NOT NULL THEN
		PERFORM catalog.run_cypher(format(
			'UNWIND [%s] AS q MATCH (p:Person {qid: q}) OPTIONAL MATCH (p)-[e]-() WITH p, count(e) AS c WHERE c = 0 DELETE p',
			array_to_string(old_people, ', ')));
	END IF;
	IF old_genres IS NOT NULL THEN
		PERFORM catalog.run_cypher(format(
			'UNWIND [%s] AS q MATCH (g:Genre {name: q}) OPTIONAL MATCH (g)-[e]-() WITH g, count(e) AS c WHERE c = 0 DELETE g',
			array_to_string(old_genres, ', ')));
	END IF;
END
$fn$;

-- Makes the SIMILAR_TO edges equal to the rule of 30-graph.sql: every movie links to its 3 nearest neighbors by
-- cosine distance, one edge per pair from the lower to the higher tmdb_id. Only differing pairs are touched.
-- Returns the number of removed plus created pairs.
CREATE OR REPLACE FUNCTION catalog.reconcile_similar_to() RETURNS integer LANGUAGE plpgsql
SET search_path = ag_catalog, pg_catalog
AS $fn$
DECLARE
	stale text[];
	missing text[];
	i integer := 1;
BEGIN
	WITH knn AS (
		SELECT a.tmdb_id AS a, b.tmdb_id AS b, 1 - (a.embedding OPERATOR(public.<=>) b.embedding) AS score
		FROM catalog.movie_docs a
		CROSS JOIN LATERAL (
			SELECT d.tmdb_id, d.embedding FROM catalog.movie_docs d
			WHERE d.tmdb_id <> a.tmdb_id AND d.embedding IS NOT NULL
			ORDER BY d.embedding OPERATOR(public.<=>) a.embedding
			LIMIT 3
		) b
		WHERE a.embedding IS NOT NULL
	), wanted AS (
		SELECT DISTINCT ON (least(a, b), greatest(a, b)) least(a, b) AS a, greatest(a, b) AS b,
			round(score::numeric, 4) AS score
		FROM knn
		WHERE EXISTS (SELECT 1 FROM public.movies m WHERE m.tmdb_id = knn.a)
			AND EXISTS (SELECT 1 FROM public.movies m WHERE m.tmdb_id = knn.b)
		ORDER BY least(a, b), greatest(a, b), score DESC
	), current AS (
		SELECT a::text::bigint AS a, b::text::bigint AS b, min(s::text::numeric) AS score, count(*) AS edges
		FROM ag_catalog.cypher('movie_graph', $cy$
			MATCH (a:Movie)-[r:SIMILAR_TO]->(b:Movie) RETURN a.tmdb_id, b.tmdb_id, r.score
		$cy$) AS (a ag_catalog.agtype, b ag_catalog.agtype, s ag_catalog.agtype)
		GROUP BY 1, 2
	), kept AS (
		-- A pair stays only as one edge with the wanted direction and score.
		SELECT c.a, c.b FROM current c JOIN wanted w USING (a, b)
		WHERE c.edges = 1 AND c.score = w.score
	)
	SELECT
		(SELECT array_agg(format('{a: %s, b: %s}', c.a, c.b)) FROM current c
		 WHERE NOT EXISTS (SELECT 1 FROM kept k WHERE k.a = c.a AND k.b = c.b)),
		(SELECT array_agg(format('{a: %s, b: %s, score: %s}', w.a, w.b, w.score)) FROM wanted w
		 WHERE NOT EXISTS (SELECT 1 FROM kept k WHERE k.a = w.a AND k.b = w.b))
	INTO stale, missing;

	-- Edges are matched by their end nodes' tmdb_id (GIN index); a list of edge ids in "id(r) IN [...]" fails
	-- with "not a common type" on AGE once it has two or more ids.
	WHILE i <= coalesce(array_length(stale, 1), 0) LOOP
		PERFORM catalog.run_cypher(format(
			'UNWIND [%s] AS e MATCH (:Movie {tmdb_id: e.a})-[r:SIMILAR_TO]->(:Movie {tmdb_id: e.b}) DELETE r',
			array_to_string(stale[i:i + 199], ', ')));
		i := i + 200;
	END LOOP;
	i := 1;
	WHILE i <= coalesce(array_length(missing, 1), 0) LOOP
		PERFORM catalog.run_cypher(format(
			'UNWIND [%s] AS e MATCH (a:Movie {tmdb_id: e.a}), (b:Movie {tmdb_id: e.b}) CREATE (a)-[:SIMILAR_TO {score: e.score}]->(b)',
			array_to_string(missing[i:i + 199], ', ')));
		i := i + 200;
	END LOOP;
	RETURN coalesce(array_length(stale, 1), 0) + coalesce(array_length(missing, 1), 0);
END
$fn$;

-- Applies up to p_limit queued movies, then reconciles SIMILAR_TO (also when p_reconcile is set and nothing was
-- queued). Returns the number of applied movies, or NULL when skipped: another session holds the graph lock
-- (a running process or 30-graph.sql) or the graph does not exist yet.
CREATE OR REPLACE FUNCTION catalog.process_graph_queue(p_limit integer DEFAULT 500, p_reconcile boolean DEFAULT false)
RETURNS integer LANGUAGE plpgsql
SECURITY DEFINER SET search_path = ag_catalog, pg_catalog
AS $fn$
DECLARE
	ids bigint[];
	id bigint;
BEGIN
	-- 30810959134158952 = 'mvgraph'; 30-graph.sql takes the same lock.
	IF NOT pg_try_advisory_xact_lock(30810959134158952)
			OR NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'movie_graph') THEN
		RETURN NULL;
	END IF;
	WITH taken AS (
		DELETE FROM catalog.graph_queue
		WHERE tmdb_id IN (SELECT tmdb_id FROM catalog.graph_queue ORDER BY queued_at LIMIT p_limit)
		RETURNING tmdb_id
	)
	SELECT array_agg(tmdb_id ORDER BY tmdb_id) INTO ids FROM taken;
	FOREACH id IN ARRAY coalesce(ids, '{}') LOOP
		PERFORM catalog.sync_movie_node(id);
	END LOOP;
	IF ids IS NOT NULL OR p_reconcile THEN
		PERFORM catalog.reconcile_similar_to();
	END IF;
	RETURN coalesce(array_length(ids, 1), 0);
END
$fn$;

-- Queues movies that are only in public.movies or only in the graph, for example after a failed run or a manual
-- change to the graph. Returns the number of queued movies.
CREATE OR REPLACE FUNCTION catalog.enqueue_graph_drift() RETURNS integer LANGUAGE plpgsql
SECURITY DEFINER SET search_path = ag_catalog, pg_catalog
AS $fn$
DECLARE
	queued integer;
BEGIN
	IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'movie_graph') THEN
		RETURN 0;
	END IF;
	WITH graph AS (
		SELECT t::text::bigint AS tmdb_id
		FROM ag_catalog.cypher('movie_graph', $cy$ MATCH (m:Movie) RETURN m.tmdb_id $cy$) AS (t ag_catalog.agtype)
	), drift AS (
		(SELECT tmdb_id FROM public.movies EXCEPT SELECT tmdb_id FROM graph)
		UNION
		(SELECT tmdb_id FROM graph EXCEPT SELECT tmdb_id FROM public.movies)
	), ins AS (
		INSERT INTO catalog.graph_queue (tmdb_id) SELECT tmdb_id FROM drift
		ON CONFLICT (tmdb_id) DO UPDATE SET queued_at = excluded.queued_at
		RETURNING 1
	)
	SELECT count(*) INTO queued FROM ins;
	RETURN queued;
END
$fn$;

-- Functions are executable by PUBLIC by default; the app role may run only the two entry points.
REVOKE ALL ON FUNCTION catalog.run_cypher(text), catalog.sync_movie_node(bigint), catalog.reconcile_similar_to(),
	catalog.process_graph_queue(integer, boolean), catalog.enqueue_graph_drift(), catalog.queue_graph_change()
	FROM PUBLIC;
GRANT EXECUTE ON FUNCTION catalog.process_graph_queue(integer, boolean), catalog.enqueue_graph_drift() TO movielog;
-- The app stores TMDB credits and genres of imported movies next to the catalog's own rows.
GRANT INSERT ON catalog.people, catalog.movie_credits, catalog.movie_genres TO movielog;
