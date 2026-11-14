package com.example.springsample.discover;

import java.util.List;
import java.util.function.Predicate;
import java.util.function.Supplier;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;

/**
 * Semantic search (query embedded in the app with Azure OpenAI, pgvector cosine distance in HorizonDB) and graph
 * exploration (Apache AGE).
 * Each call is timed as {@code movielog.discover.*} with an {@code outcome} tag so the AKS
 * Application Insights agent exports it to customMetrics next to the other movielog meters.
 */
@Service
public class DiscoverService {

	private static final Logger logger = LoggerFactory.getLogger(DiscoverService.class);

	public static final int MAX_RESULTS = 30;

	public static final int MAX_QUERY_LENGTH = 200;

	private static final int GRAPH_CO_CREDITS = 60;

	private final EmbeddingClient embeddings;

	private final VectorSearchRepository vectors;

	private final MovieGraphRepository graph;

	private final MeterRegistry registry;

	private final DiscoverRateLimiter rateLimiter;

	private final Counter rejected;

	private final QueryCorrector corrector;

	private final Counter corrected;

	public DiscoverService(EmbeddingClient embeddings, VectorSearchRepository vectors, MovieGraphRepository graph,
			MeterRegistry registry, DiscoverRateLimiter rateLimiter, QueryCorrector corrector) {
		this.embeddings = embeddings;
		this.vectors = vectors;
		this.graph = graph;
		this.registry = registry;
		this.rateLimiter = rateLimiter;
		this.rejected = Counter.builder("movielog.discover.rejected")
			.description("Semantic searches refused by the rate cap before calling Azure OpenAI")
			.register(registry);
		this.corrector = corrector;
		this.corrected = Counter.builder("movielog.discover.corrected")
			.description("Semantic searches whose misspelled name or title was corrected before embedding")
			.register(registry);
	}

	/**
	 * @param client address of the caller (after forwarded headers), used for the per-client rate cap
	 */
	public List<MovieHit> search(String query, int limit, String client) {
		return searchWithCorrection(query, limit, client).hits();
	}

	/**
	 * Like {@link #search}, and reports a corrected person name or title. The corrected query is embedded and
	 * matched by keywords; the web page shows which words were replaced.
	 */
	public DiscoverSearch searchWithCorrection(String query, int limit, String client) {
		if (!rateLimiter.tryAcquire(client)) {
			rejected.increment();
			throw new DiscoverRateLimitedException("Too many semantic searches; try again in a minute");
		}
		String typed = truncate(query.strip(), MAX_QUERY_LENGTH);
		QueryCorrection correction = corrector.correct(typed).orElse(null);
		if (correction != null) {
			corrected.increment();
		}
		String input = (correction == null) ? typed : correction.query();
		float[] embedding = timed("movielog.discover.embedding", "query", () -> embeddings.embed(input), v -> false);
		List<MovieHit> hits = timed("movielog.discover.search", "vector",
				() -> vectors.search(embedding, input, Math.clamp(limit, 1, MAX_RESULTS)), List::isEmpty);
		return new DiscoverSearch(hits, correction);
	}

	/** Search results and, when the query was corrected, the replaced words. */
	public record DiscoverSearch(List<MovieHit> hits, @Nullable QueryCorrection correction) {
	}

	public List<MovieHit> similar(long tmdbId, int limit) {
		return timed("movielog.discover.similar", "vector",
				() -> vectors.similar(tmdbId, Math.clamp(limit, 1, MAX_RESULTS)), List::isEmpty);
	}

	/** The catalog's attributed summary of the movie, or null when there is none or the catalog cannot be read. */
	public @Nullable CatalogOverview catalogOverview(long tmdbId) {
		try {
			return vectors.catalogOverview(tmdbId);
		}
		catch (DataAccessException ex) {
			logger.warn("catalog overview lookup failed: {}", ex.getMostSpecificCause().getMessage());
			return null;
		}
	}

	public GraphView movieGraph(long tmdbId) {
		return timed("movielog.discover.graph", "movie", () -> graph.neighborhood(tmdbId, GRAPH_CO_CREDITS),
				view -> view.nodes().isEmpty());
	}

	public GraphView graphAmong(List<Long> tmdbIds) {
		List<Long> ids = tmdbIds.stream().distinct().limit(MAX_RESULTS).toList();
		return timed("movielog.discover.graph", "results", () -> graph.among(ids), view -> view.nodes().isEmpty());
	}

	/** Cuts at a code point boundary so a surrogate pair is never split. */
	static String truncate(String text, int maxCodePoints) {
		if (text.codePointCount(0, text.length()) <= maxCodePoints) {
			return text;
		}
		return text.substring(0, text.offsetByCodePoints(0, maxCodePoints));
	}

	private <T> T timed(String name, String kind, Supplier<T> call, Predicate<T> empty) {
		Timer.Sample sample = Timer.start(registry);
		String outcome = "error";
		try {
			T result = call.get();
			outcome = empty.test(result) ? "empty" : "found";
			return result;
		}
		catch (DataAccessException ex) {
			logger.warn("{} ({}) failed: {}", name, kind, ex.getMostSpecificCause().getMessage());
			throw new DiscoverUnavailableException("Catalog search is not available", ex);
		}
		catch (EmbeddingUnavailableException ex) {
			logger.warn("{} ({}) failed: {}", name, kind, ex.getMessage());
			throw new DiscoverUnavailableException("Query embedding is not available", ex);
		}
		finally {
			sample.stop(registry.timer(name, "kind", kind, "outcome", outcome));
		}
	}

}
