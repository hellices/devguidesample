package com.example.springsample.discover;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import com.example.springsample.discover.TmdbCreditsClient.Credit;
import com.example.springsample.discover.TmdbCreditsClient.Credits;
import org.jspecify.annotations.Nullable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Finds movies imported from TMDB after the catalog load ({@code public.movies} rows without a
 * {@code catalog.movie_docs} row) and stores their embedded document, credits and genres in the catalog tables,
 * then updates the AGE graph for that movie. The app role needs INSERT on {@code catalog.movie_docs}
 * ({@code db/10-schema.sql}), on {@code people}, {@code movie_credits} and {@code movie_genres}, and EXECUTE on
 * {@code catalog.sync_movie_graph} ({@code db/40-graph-sync.sql}).
 */
@Repository
class CatalogIndexRepository {

	/** Same limit as MAX_GENRES in {@code data/build_catalog.py}. */
	static final int MAX_GENRES = 4;

	/** Advisory lock key, so only one Pod indexes at a time. */
	private static final long LOCK_KEY = 0x6d6f7669656c6f67L;

	private final JdbcClient jdbc;

	CatalogIndexRepository(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	/** Must run inside a transaction; the lock is released when it ends. */
	boolean tryLock() {
		return jdbc.sql("SELECT pg_try_advisory_xact_lock(:key)").param("key", LOCK_KEY).query(Boolean.class).single();
	}

	List<PendingMovie> pending(int limit) {
		return jdbc.sql("""
				SELECT m.tmdb_id, m.title, m.original_title, extract(year FROM m.release_date)::int AS year,
				       m.genres, m.overview
				FROM public.movies m
				WHERE NOT EXISTS (SELECT 1 FROM catalog.movie_docs d WHERE d.tmdb_id = m.tmdb_id)
				ORDER BY m.created_at DESC
				LIMIT :limit""")
			.param("limit", limit)
			.query((rs, row) -> new PendingMovie(rs.getLong("tmdb_id"), rs.getString("title"),
					rs.getString("original_title"), (Integer) rs.getObject("year"), rs.getString("genres"),
					rs.getString("overview")))
			.list();
	}

	/**
	 * Without {@code overview} and {@code source_url} the movie page keeps showing the TMDB overview instead of a
	 * Wikipedia attribution. A later catalog load replaces the row and clears the embedding when the text differs.
	 */
	void insert(long tmdbId, String doc, float[] embedding) {
		jdbc.sql("""
				INSERT INTO catalog.movie_docs (tmdb_id, doc, embedding, embedded_at)
				VALUES (:tmdbId, :doc, CAST(:v AS vector), now())
				ON CONFLICT (tmdb_id) DO NOTHING""")
			.param("tmdbId", tmdbId)
			.param("doc", doc)
			.param("v", VectorSearchRepository.toLiteral(embedding))
			.update();
	}

	/**
	 * Stores directors, then actors, with positions counted across both like {@code data/build_catalog.py}.
	 * A person is keyed by the Wikidata id TMDB knows ({@code wikidataIds}, TMDB person id to QID), so the graph
	 * links the movie to the catalog's node for that person. Without one, a name that belongs to exactly one
	 * catalog person reuses that id, and anyone else is stored as {@code tmdb:<person id>}.
	 */
	void saveCredits(long tmdbId, Credits credits, Map<Long, String> wikidataIds) {
		List<Credit> people = new ArrayList<>(credits.directors());
		people.addAll(credits.actors());
		for (int position = 0; position < people.size(); position++) {
			jdbc.sql("""
					INSERT INTO catalog.movie_credits (tmdb_id, person_qid, role, position)
					VALUES (:tmdbId, :qid, :role, :position)
					ON CONFLICT DO NOTHING""")
				.param("tmdbId", tmdbId)
				.param("qid", personQid(people.get(position), wikidataIds.get(people.get(position).id())))
				.param("role", (position < credits.directors().size()) ? "director" : "actor")
				.param("position", position)
				.update();
		}
	}

	private String personQid(Credit credit, @Nullable String wikidataId) {
		if (wikidataId != null) {
			// The catalog's name stays when the person is already there.
			jdbc.sql("INSERT INTO catalog.people (qid, name, sitelinks) VALUES (:qid, :name, 0) ON CONFLICT DO NOTHING")
				.param("qid", wikidataId)
				.param("name", credit.name())
				.update();
			return wikidataId;
		}
		List<String> known = jdbc.sql("SELECT qid FROM catalog.people WHERE name = :name LIMIT 2")
			.param("name", credit.name())
			.query(String.class)
			.list();
		if (known.size() == 1) {
			return known.getFirst();
		}
		String qid = "tmdb:" + credit.id();
		jdbc.sql("INSERT INTO catalog.people (qid, name, sitelinks) VALUES (:qid, :name, 0) ON CONFLICT DO NOTHING")
			.param("qid", qid)
			.param("name", credit.name())
			.update();
		return qid;
	}

	/** {@code public.movies.genres} holds the TMDB genre names joined by commas. */
	void saveGenres(long tmdbId, @Nullable String genres) {
		if (genres == null) {
			return;
		}
		List<String> names = Arrays.stream(genres.split(","))
			.map(String::strip)
			.filter(genre -> !genre.isEmpty())
			.distinct()
			.limit(MAX_GENRES)
			.toList();
		for (String genre : names) {
			jdbc.sql("""
					INSERT INTO catalog.movie_genres (tmdb_id, genre) VALUES (:tmdbId, :genre)
					ON CONFLICT DO NOTHING""")
				.param("tmdbId", tmdbId)
				.param("genre", genre)
				.update();
		}
	}

	/** False when the graph does not exist yet; {@code db/30-graph.sql} then includes the movie. */
	boolean syncGraph(long tmdbId) {
		return jdbc.sql("SELECT catalog.sync_movie_graph(:tmdbId)")
			.param("tmdbId", tmdbId)
			.query(Boolean.class)
			.single();
	}

	record PendingMovie(long tmdbId, String title, @Nullable String originalTitle, @Nullable Integer year,
			@Nullable String genres, @Nullable String overview) {
	}

}
