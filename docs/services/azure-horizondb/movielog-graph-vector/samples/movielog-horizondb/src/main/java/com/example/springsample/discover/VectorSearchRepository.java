package com.example.springsample.discover;

import java.sql.Date;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import org.jspecify.annotations.Nullable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Nearest-neighbor search over {@code catalog.movie_docs.embedding} by pgvector cosine distance. A DiskANN index
 * exists, but with a few hundred rows the planner usually prefers a sequential scan.
 * <p>
 * A whole-document embedding ranks short title or name queries ("듄", "드니 빌뇌브") poorly, so {@link #search}
 * fuses the vector ranking with a keyword ranking over the document header (title, original title, year, genres,
 * directors, cast; the summary is left to the vector side) by Reciprocal Rank Fusion. A movie enters the keyword
 * ranking only when its header contains at least half of the query words, so a descriptive query ("a shark
 * terrorizes a beach town") is not pulled toward titles that share one word. The returned score stays the cosine
 * similarity.
 */
@Repository
class VectorSearchRepository {

	// The catalog's own summary is shown with its source article; public.movies.overview may later come from TMDB.
	private static final String COLUMNS = """
			d.tmdb_id, m.title, m.original_title, m.release_date, m.genres, coalesce(d.overview, m.overview) AS overview,
			CASE WHEN d.overview IS NOT NULL THEN d.source_url END AS source_url""";

	/** Candidates taken from each ranking before fusion. */
	private static final int POOL = 50;

	/** Reciprocal Rank Fusion constant: score = sum of 1 / (RRF_K + rank). */
	private static final int RRF_K = 60;

	private static final int MAX_KEYWORDS = 8;

	/** Separates keywords in the single text parameter; cannot occur in a keyword. */
	private static final char KEYWORD_SEPARATOR = '\u001f';

	private final JdbcClient jdbc;

	VectorSearchRepository(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	List<MovieHit> search(float[] embedding, String query, int limit) {
		List<String> keywords = keywords(query);
		return jdbc.sql("""
				WITH q AS (SELECT CAST(:v AS vector) AS v),
				vec AS (
					SELECT d.tmdb_id, row_number() OVER (ORDER BY d.embedding <=> q.v) AS r
					FROM catalog.movie_docs d, q
					WHERE d.embedding IS NOT NULL
					ORDER BY d.embedding <=> q.v
					LIMIT :pool),
				lex AS (
					SELECT tmdb_id, row_number() OVER (ORDER BY hits DESC, dist) AS r
					FROM (
						SELECT d.tmdb_id, d.embedding <=> q.v AS dist,
						       (SELECT count(*) FROM unnest(string_to_array(:terms, chr(31))) AS t(term)
						        WHERE t.term <> '' AND strpos(lower(split_part(split_part(d.doc, chr(10) || '줄거리:', 1), chr(10) || 'Summary:', 1)), t.term) > 0) AS hits
						FROM catalog.movie_docs d, q
						WHERE d.embedding IS NOT NULL) x
					WHERE hits > 0 AND hits * 2 >= :keywordCount
					ORDER BY hits DESC, dist
					LIMIT :pool),
				fused AS (
					SELECT tmdb_id, sum(1.0 / (:k + r)) AS rrf
					FROM (SELECT tmdb_id, r FROM vec UNION ALL SELECT tmdb_id, r FROM lex) ranked
					GROUP BY tmdb_id)
				SELECT %s, 1 - (d.embedding <=> q.v) AS score
				FROM fused f
				JOIN catalog.movie_docs d ON d.tmdb_id = f.tmdb_id
				JOIN public.movies m ON m.tmdb_id = d.tmdb_id
				CROSS JOIN q
				ORDER BY f.rrf DESC, d.embedding <=> q.v
				LIMIT :limit""".formatted(COLUMNS))
			.param("v", toLiteral(embedding))
			.param("terms", String.join(String.valueOf(KEYWORD_SEPARATOR), keywords))
			.param("keywordCount", keywords.size())
			.param("pool", POOL)
			.param("k", RRF_K)
			.param("limit", limit)
			.query(VectorSearchRepository::hit)
			.list();
	}

	/**
	 * Lower-cased words of the query for the keyword ranking. Latin words shorter than four letters ("a", "the")
	 * match too many titles and are dropped; Korean words of any length are kept, so "듄" still counts.
	 */
	static List<String> keywords(String query) {
		Set<String> words = new LinkedHashSet<>();
		for (String word : query.toLowerCase(Locale.ROOT).split("[^\\p{L}\\p{N}]+")) {
			boolean latin = word.chars().allMatch(c -> c < 0x80);
			if (!word.isEmpty() && (!latin || word.length() >= 4)) {
				words.add(word);
			}
			if (words.size() == MAX_KEYWORDS) {
				break;
			}
		}
		return List.copyOf(words);
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

	/** The catalog's Wikipedia summary of a movie with its source article, when both are stored. */
	@Nullable CatalogOverview catalogOverview(long tmdbId) {
		return jdbc.sql("""
				SELECT overview, source_url FROM catalog.movie_docs
				WHERE tmdb_id = :tmdbId AND overview IS NOT NULL AND source_url IS NOT NULL""")
			.param("tmdbId", tmdbId)
			.query((rs, row) -> new CatalogOverview(rs.getString("overview"), rs.getString("source_url")))
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
