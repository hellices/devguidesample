package com.example.springsample.discover;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.example.springsample.discover.CatalogIndexRepository.PendingMovie;
import com.example.springsample.discover.TmdbCreditsClient.Credit;
import com.example.springsample.discover.TmdbCreditsClient.Credits;
import com.example.springsample.movie.MovieApiUnavailableException;
import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
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
 * directors and leading cast from TMDB credits, and stores the credits and genres in the catalog tables. Each movie
 * is one transaction, so a movie is either fully indexed or retried on the next run. Triggers queue the stored rows
 * for the graph, and {@link MovieGraphSync} applies them right after the run.
 */
@Configuration(proxyBeanMethods = false)
@EnableScheduling
@ConditionalOnBooleanProperty("app.discover.indexer.enabled")
class CatalogIndexer {

	private static final Logger logger = LoggerFactory.getLogger(CatalogIndexer.class);

	private final CatalogIndexRepository repository;

	private final EmbeddingClient embeddings;

	private final TmdbCreditsClient tmdb;

	private final QueryCorrector corrector;

	private final ObjectProvider<MovieGraphSync> graphSync;

	private final TransactionOperations transactions;

	private final int batchSize;

	CatalogIndexer(CatalogIndexRepository repository, EmbeddingClient embeddings, TmdbCreditsClient tmdb,
			QueryCorrector corrector, ObjectProvider<MovieGraphSync> graphSync, TransactionOperations transactions,
			@Value("${app.discover.indexer.batch-size:20}") int batchSize) {
		this.repository = repository;
		this.embeddings = embeddings;
		this.tmdb = tmdb;
		this.corrector = corrector;
		this.graphSync = graphSync;
		this.transactions = transactions;
		this.batchSize = batchSize;
	}

	@Scheduled(initialDelayString = "${app.discover.indexer.initial-delay:PT20S}",
			fixedDelayString = "${app.discover.indexer.interval:PT30S}")
	void run() {
		try {
			List<Long> indexed = indexPending();
			if (!indexed.isEmpty()) {
				logger.info("Indexed {} imported movie(s) for semantic search and the graph: {}", indexed.size(),
						indexed);
			}
		}
		catch (RuntimeException ex) {
			logger.warn("Catalog indexing failed, retrying on the next run: {}", ex.toString());
		}
	}

	/**
	 * Indexes up to one batch of movies without a document, one transaction per movie. Stops at the first TMDB or
	 * embedding failure, keeping the movies indexed before it. Another Pod holding the lock makes this a no-op.
	 * Without a TMDB key the documents have no people.
	 */
	List<Long> indexPending() {
		if (!embeddings.isEnabled()) {
			return List.of();
		}
		List<Long> indexed = new ArrayList<>();
		for (int i = 0; i < batchSize; i++) {
			Long tmdbId = transactions.execute(status -> indexNext());
			if (tmdbId == null) {
				break;
			}
			indexed.add(tmdbId);
		}
		if (!indexed.isEmpty()) {
			// New people and titles become spelling-correction candidates right away.
			corrector.refresh();
			graphSync.ifAvailable(MovieGraphSync::processQueue);
		}
		return indexed;
	}

	/** The indexed movie, or null when there is nothing to do, another Pod holds the lock or a call failed. */
	private @Nullable Long indexNext() {
		if (!repository.tryLock()) {
			return null;
		}
		List<PendingMovie> pending = repository.pending(1);
		if (pending.isEmpty()) {
			return null;
		}
		PendingMovie movie = pending.getFirst();
		Credits credits;
		Map<Long, String> wikidataIds = new HashMap<>();
		String doc;
		float[] vector;
		try {
			credits = tmdb.isEnabled() ? tmdb.credits(movie.tmdbId()) : Credits.NONE;
			for (Credit credit : credits.directors()) {
				tmdb.wikidataId(credit.id()).ifPresent(qid -> wikidataIds.put(credit.id(), qid));
			}
			for (Credit credit : credits.actors()) {
				tmdb.wikidataId(credit.id()).ifPresent(qid -> wikidataIds.put(credit.id(), qid));
			}
			doc = document(movie, credits);
			vector = embeddings.embed(doc);
		}
		catch (MovieApiUnavailableException | EmbeddingUnavailableException ex) {
			logger.warn("Indexing movie {} failed: {}", movie.tmdbId(), ex.getMessage());
			return null;
		}
		repository.insert(movie.tmdbId(), doc, vector);
		repository.saveCredits(movie.tmdbId(), credits, wikidataIds);
		repository.saveGenres(movie.tmdbId(), movie.genres());
		return movie.tmdbId();
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
			parts.add("감독: " + names(credits.directors()));
		}
		if (!credits.actors().isEmpty()) {
			parts.add("출연: " + names(credits.actors()));
		}
		if (movie.overview() != null && !movie.overview().isBlank()) {
			parts.add("줄거리: " + movie.overview());
		}
		return String.join("\n", parts);
	}

	private static String names(List<Credit> credits) {
		return String.join(", ", credits.stream().map(Credit::name).toList());
	}

}
