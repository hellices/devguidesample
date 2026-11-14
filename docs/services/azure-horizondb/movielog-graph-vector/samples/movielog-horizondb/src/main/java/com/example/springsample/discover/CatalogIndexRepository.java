package com.example.springsample.discover;

import java.util.List;

import org.jspecify.annotations.Nullable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Finds movies imported from TMDB after the catalog load ({@code public.movies} rows without a
 * {@code catalog.movie_docs} row) and stores their embedded document. The app role needs INSERT on
 * {@code catalog.movie_docs} ({@code db/10-schema.sql}).
 */
@Repository
class CatalogIndexRepository {

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

	record PendingMovie(long tmdbId, String title, @Nullable String originalTitle, @Nullable Integer year,
			@Nullable String genres, @Nullable String overview) {
	}

}
