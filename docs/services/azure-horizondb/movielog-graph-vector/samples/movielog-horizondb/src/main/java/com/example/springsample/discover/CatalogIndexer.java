package com.example.springsample.discover;

import java.util.ArrayList;
import java.util.List;

import com.example.springsample.discover.CatalogIndexRepository.PendingMovie;
import com.example.springsample.discover.TmdbCreditsClient.Credits;
import com.example.springsample.movie.MovieApiUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBooleanProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.support.TransactionOperations;

/**
 * Makes movies that members import from TMDB searchable. The catalog load embeds only the movies it knows, so a
 * movie first opened through TMDB search has no {@code catalog.movie_docs} row and never appears in semantic search.
 * This job embeds such movies with the same deployment and document layout as {@code data/build_catalog.py}, taking
 * directors and leading cast from TMDB credits. Graph nodes and edges still come from {@code db/30-graph.sql}.
 */
@Configuration(proxyBeanMethods = false)
@EnableScheduling
@ConditionalOnBooleanProperty("app.discover.indexer.enabled")
class CatalogIndexer {

	private static final Logger logger = LoggerFactory.getLogger(CatalogIndexer.class);

	private final CatalogIndexRepository repository;

	private final EmbeddingClient embeddings;

	private final TmdbCreditsClient tmdb;

	private final TransactionOperations transactions;

	private final int batchSize;

	CatalogIndexer(CatalogIndexRepository repository, EmbeddingClient embeddings, TmdbCreditsClient tmdb,
			TransactionOperations transactions, @Value("${app.discover.indexer.batch-size:20}") int batchSize) {
		this.repository = repository;
		this.embeddings = embeddings;
		this.tmdb = tmdb;
		this.transactions = transactions;
		this.batchSize = batchSize;
	}

	@Scheduled(initialDelayString = "${app.discover.indexer.initial-delay:PT20S}",
			fixedDelayString = "${app.discover.indexer.interval:PT30S}")
	void run() {
		try {
			List<Long> indexed = indexPending();
			if (!indexed.isEmpty()) {
				logger.info("Embedded {} imported movie(s) for semantic search: {}", indexed.size(), indexed);
			}
		}
		catch (RuntimeException ex) {
			logger.warn("Catalog indexing failed, retrying on the next run: {}", ex.toString());
		}
	}

	/**
	 * Embeds up to one batch of movies without a document. Stops at the first TMDB or embedding failure and keeps
	 * the movies stored before it, so a later run indexes the rest with their credits. Another Pod holding the lock
	 * makes this a no-op. Without a TMDB key the documents have no people.
	 */
	List<Long> indexPending() {
		if (!embeddings.isEnabled()) {
			return List.of();
		}
		List<Long> indexed = new ArrayList<>();
		transactions.executeWithoutResult(status -> {
			if (!repository.tryLock()) {
				return;
			}
			for (PendingMovie movie : repository.pending(batchSize)) {
				String doc;
				float[] vector;
				try {
					doc = document(movie, tmdb.isEnabled() ? tmdb.credits(movie.tmdbId()) : Credits.NONE);
					vector = embeddings.embed(doc);
				}
				catch (MovieApiUnavailableException | EmbeddingUnavailableException ex) {
					logger.warn("Indexing movie {} failed: {}", movie.tmdbId(), ex.getMessage());
					return;
				}
				repository.insert(movie.tmdbId(), doc, vector);
				indexed.add(movie.tmdbId());
			}
		});
		return indexed;
	}

	/** Same layout as {@code document()} in {@code data/build_catalog.py}. */
	static String document(PendingMovie movie, Credits credits) {
		List<String> parts = new ArrayList<>();
		parts.add("제목: " + movie.title());
		if (movie.originalTitle() != null && !movie.originalTitle().isBlank()
				&& !movie.originalTitle().equals(movie.title())) {
			parts.add("원제: " + movie.originalTitle());
		}
		if (movie.year() != null) {
			parts.add("개봉: " + movie.year());
		}
		if (movie.genres() != null && !movie.genres().isBlank()) {
			parts.add("장르: " + movie.genres());
		}
		if (!credits.directors().isEmpty()) {
			parts.add("감독: " + String.join(", ", credits.directors()));
		}
		if (!credits.actors().isEmpty()) {
			parts.add("출연: " + String.join(", ", credits.actors()));
		}
		if (movie.overview() != null && !movie.overview().isBlank()) {
			parts.add("줄거리: " + movie.overview());
		}
		return String.join("\n", parts);
	}

}
