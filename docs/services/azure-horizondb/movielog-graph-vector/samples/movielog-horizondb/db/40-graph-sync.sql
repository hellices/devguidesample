-- Run as the HorizonDB administrator against the "movielog" database after 30-graph.sql. Re-running is safe.
-- catalog.sync_movie_graph(tmdb_id) rebuilds one movie of the AGE graph "movie_graph" from the relational rows,
-- the same way 30-graph.sql builds every movie: Movie, its Person and Genre neighbors, DIRECTED, ACTED_IN,
-- IN_GENRE and the SIMILAR_TO pairs that touch the movie. The app calls it after it stores a movie that members
-- imported from TMDB, so the movie appears in the graph without a full rebuild (about 1.4 s for 482 movies).
-- The app role gets EXECUTE on this function only; it cannot write movie_graph tables directly.
\set ON_ERROR_STOP on

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

-- The search_path leaves out public so callers cannot shadow functions; pgvector operators are schema-qualified.
CREATE OR REPLACE FUNCTION catalog.sync_movie_graph(p_tmdb_id bigint) RETURNS boolean LANGUAGE plpgsql
SECURITY DEFINER SET search_path = ag_catalog, pg_catalog
AS $fn$
DECLARE
	r record;
BEGIN
	-- Before 30-graph.sql has run there is no graph to update; the next rebuild includes the movie.
	IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'movie_graph') THEN
		RETURN false;
	END IF;
	PERFORM catalog.run_cypher(format('MATCH (m:Movie {tmdb_id: %s}) DETACH DELETE m', p_tmdb_id));
	SELECT m.tmdb_id, m.title, extract(year FROM m.release_date)::int AS year INTO r
	FROM public.movies m WHERE m.tmdb_id = p_tmdb_id;
	IF NOT FOUND THEN
		RETURN false;
	END IF;
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
		PERFORM catalog.run_cypher(format('MERGE (:Person {qid: %s, name: %s})',
			catalog.cypher_literal(r.person_qid), catalog.cypher_literal(r.name)));
		PERFORM catalog.run_cypher(format(
			'MATCH (p:Person {qid: %s}), (m:Movie {tmdb_id: %s}) CREATE (p)-[:%s]->(m)',
			catalog.cypher_literal(r.person_qid), p_tmdb_id,
			CASE WHEN r.role = 'director' THEN 'DIRECTED' ELSE format('ACTED_IN {position: %s}', r.position) END));
	END LOOP;

	-- SIMILAR_TO pairs touching this movie, by the rule of 30-graph.sql: every movie links to its 3 nearest
	-- neighbors, a pair is stored once from the lower to the higher tmdb_id, so a pair where another movie chose
	-- this one is restored as well. DETACH DELETE above removed both directions.
	FOR r IN
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
		), pairs AS (
			SELECT DISTINCT ON (least(a, b), greatest(a, b)) least(a, b) AS a, greatest(a, b) AS b,
				round(score::numeric, 4) AS score
			FROM knn
			WHERE a = p_tmdb_id OR b = p_tmdb_id
			ORDER BY least(a, b), greatest(a, b), score DESC
		)
		SELECT pairs.a, pairs.b, pairs.score FROM pairs
		WHERE EXISTS (SELECT 1 FROM public.movies m WHERE m.tmdb_id = pairs.a)
			AND EXISTS (SELECT 1 FROM public.movies m WHERE m.tmdb_id = pairs.b)
	LOOP
		PERFORM catalog.run_cypher(format(
			'MATCH (a:Movie {tmdb_id: %s}), (b:Movie {tmdb_id: %s}) CREATE (a)-[:SIMILAR_TO {score: %s}]->(b)',
			r.a, r.b, r.score));
	END LOOP;
	RETURN true;
END
$fn$;

-- Functions are executable by PUBLIC by default; only the app role may run the definer function.
REVOKE ALL ON FUNCTION catalog.run_cypher(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION catalog.sync_movie_graph(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION catalog.sync_movie_graph(bigint) TO movielog;
-- The app stores TMDB credits and genres of imported movies next to the catalog's own rows.
GRANT INSERT ON catalog.people, catalog.movie_credits, catalog.movie_genres TO movielog;
