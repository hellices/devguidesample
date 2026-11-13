package com.example.springsample.discover;

import java.sql.Date;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Arrays;
import java.util.List;

import org.jspecify.annotations.Nullable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Nearest-neighbor search over {@code catalog.movie_docs.embedding} by pgvector cosine distance. A DiskANN index
 * exists, but with a few hundred rows the planner usually prefers a sequential scan.
 */
@Repository
class VectorSearchRepository {

	private static final String COLUMNS = """
			d.tmdb_id, m.title, m.original_title, m.release_date, m.genres, m.overview, d.source_url""";

	private final JdbcClient jdbc;

	VectorSearchRepository(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	List<MovieHit> search(float[] embedding, int limit) {
		return jdbc.sql("""
				SELECT %s, 1 - (d.embedding <=> CAST(:v AS vector)) AS score
				FROM catalog.movie_docs d JOIN public.movies m ON m.tmdb_id = d.tmdb_id
				WHERE d.embedding IS NOT NULL
				ORDER BY d.embedding <=> CAST(:v AS vector)
				LIMIT :limit""".formatted(COLUMNS))
			.param("v", toLiteral(embedding))
			.param("limit", limit)
			.query(VectorSearchRepository::hit)
			.list();
	}

	/** Empty when the movie has no embedding, instead of unrelated movies scored from a NULL distance. */
	List<MovieHit> similar(long tmdbId, int limit) {
		return jdbc.sql("""
				SELECT %s, 1 - (d.embedding <=> (SELECT embedding FROM catalog.movie_docs WHERE tmdb_id = :tmdbId)) AS score
				FROM catalog.movie_docs d JOIN public.movies m ON m.tmdb_id = d.tmdb_id
				WHERE d.tmdb_id <> :tmdbId AND d.embedding IS NOT NULL
				  AND EXISTS (SELECT 1 FROM catalog.movie_docs WHERE tmdb_id = :tmdbId AND embedding IS NOT NULL)
				ORDER BY d.embedding <=> (SELECT embedding FROM catalog.movie_docs WHERE tmdb_id = :tmdbId)
				LIMIT :limit""".formatted(COLUMNS))
			.param("tmdbId", tmdbId)
			.param("limit", limit)
			.query(VectorSearchRepository::hit)
			.list();
	}

	/** Wikipedia article the stored overview of a catalog movie was taken from, for attribution. */
	@Nullable String overviewSource(long tmdbId) {
		return jdbc.sql("SELECT source_url FROM catalog.movie_docs WHERE tmdb_id = :tmdbId")
			.param("tmdbId", tmdbId)
			.query(String.class)
			.optional()
			.orElse(null);
	}

	/** pgvector text form: [0.1,0.2,...]. */
	static String toLiteral(float[] embedding) {
		StringBuilder out = new StringBuilder(embedding.length * 10).append('[');
		for (int i = 0; i < embedding.length; i++) {
			if (i > 0) {
				out.append(',');
			}
			out.append(embedding[i]);
		}
		return out.append(']').toString();
	}

	private static MovieHit hit(ResultSet rs, int row) throws SQLException {
		Date released = rs.getDate("release_date");
		String genres = rs.getString("genres");
		return new MovieHit(rs.getLong("tmdb_id"), rs.getString("title"), rs.getString("original_title"),
				(released == null) ? null : released.toLocalDate().getYear(),
				(genres == null) ? List.of() : Arrays.stream(genres.split(",")).map(String::strip).toList(),
				rs.getString("overview"), rs.getString("source_url"), rs.getDouble("score"));
	}

}
