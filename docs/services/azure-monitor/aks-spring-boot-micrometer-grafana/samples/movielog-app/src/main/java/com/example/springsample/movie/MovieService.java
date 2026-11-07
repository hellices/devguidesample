package com.example.springsample.movie;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import com.example.springsample.common.ResourceNotFoundException;
import com.example.springsample.movie.omdb.ExternalRatings;
import com.example.springsample.movie.omdb.OmdbClient;
import com.example.springsample.movie.tmdb.TmdbClient;
import com.example.springsample.movie.tmdb.TmdbDtos;
import com.example.springsample.review.ReviewRepository;
import com.example.springsample.review.ReviewStats;
import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.Limit;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Movies come from TMDB and are stored locally the first time they are opened, so reviews can reference them.
 * External calls run outside database transactions; the snapshot is refreshed after {@code app.movies.sync-ttl}.
 */
@Service
public class MovieService {

	private static final Logger logger = LoggerFactory.getLogger(MovieService.class);

	public static final int MAX_SEARCH_PAGE = 500;

	public static final int MAX_POPULAR = 50;

	private final TmdbClient tmdb;

	private final OmdbClient omdb;

	private final MovieRepository movies;

	private final ReviewRepository reviews;

	private final MovieApiProperties properties;

	private final Clock clock;

	private final ApplicationEventPublisher events;

	private final TransactionTemplate transactionTemplate;

	public MovieService(TmdbClient tmdb, OmdbClient omdb, MovieRepository movies, ReviewRepository reviews,
			MovieApiProperties properties, Clock clock, ApplicationEventPublisher events,
			TransactionTemplate transactionTemplate) {
		this.tmdb = tmdb;
		this.omdb = omdb;
		this.movies = movies;
		this.reviews = reviews;
		this.properties = properties;
		this.clock = clock;
		this.events = events;
		this.transactionTemplate = transactionTemplate;
	}

	public boolean isSearchAvailable() {
		return tmdb.isEnabled();
	}

	public MovieSearchPage search(String query, int page) {
		int safePage = Math.clamp(page, 1, MAX_SEARCH_PAGE);
		if (!tmdb.isEnabled()) {
			events.publishEvent(new MovieEvents.Searched(MovieEvents.SearchOutcome.DISABLED, safePage, 0));
			throw new MovieApiUnavailableException("TMDB API key is not configured (TMDB_API_KEY)");
		}
		TmdbDtos.SearchPage result;
		try {
			result = tmdb.search(query.strip(), safePage);
		}
		catch (MovieApiUnavailableException ex) {
			events.publishEvent(new MovieEvents.Searched(MovieEvents.SearchOutcome.ERROR, safePage, 0));
			throw ex;
		}
		List<TmdbDtos.SearchItem> results = (result.results() == null) ? List.of() : result.results();

		Map<Long, ReviewStats> statsByTmdbId = localStats(results.stream().map(TmdbDtos.SearchItem::id).toList());
		List<MovieSearchPage.Item> items = results.stream().map(item -> {
			ReviewStats stats = statsByTmdbId.get(item.id());
			var date = TmdbDtos.parseDate(item.releaseDate());
			return new MovieSearchPage.Item(item.id(), item.title(), item.originalTitle(),
					(date == null) ? null : date.getYear(), posterUrl(item.posterPath(), "w342"), item.overview(),
					(stats == null) ? 0 : stats.reviewCount(), (stats == null) ? null : stats.averageStars());
		}).toList();

		boolean hasNext = result.page() < Math.min(result.totalPages(), MAX_SEARCH_PAGE);
		events.publishEvent(new MovieEvents.Searched(
				items.isEmpty() ? MovieEvents.SearchOutcome.EMPTY : MovieEvents.SearchOutcome.FOUND, safePage,
				result.totalResults()));
		return new MovieSearchPage(items, result.page(), hasNext ? result.page() + 1 : null, hasNext,
				result.totalResults());
	}

	/** Movie information for internal use (review forms); does not count as a view. */
	public MovieDetail getMovie(long tmdbId) {
		Movie movie = sync(tmdbId);
		return toDetail(movie, movie.getViewCount());
	}

	/** A user opened the movie page: counts the view per movie and publishes {@link MovieEvents.Viewed}. */
	public MovieDetail viewMovie(long tmdbId) {
		Movie movie = sync(tmdbId);
		Long views = transactionTemplate.execute(status -> {
			movies.incrementViewCount(movie.getId());
			// Listeners are @TransactionalEventListener, so they run only after this transaction commits.
			events.publishEvent(new MovieEvents.Viewed(tmdbId));
			return movies.findViewCountById(movie.getId());
		});
		return toDetail(movie, (views == null) ? movie.getViewCount() : views);
	}

	/** Most viewed movies on this site. */
	@Transactional(readOnly = true)
	public List<PopularMovie> popular(int limit) {
		List<Movie> ranked = movies.findByViewCountGreaterThanOrderByViewCountDescIdAsc(0,
				Limit.of(Math.clamp(limit, 1, MAX_POPULAR)));
		Map<Long, ReviewStats> statsByMovieId = ranked.isEmpty() ? Map.of()
				: reviews.statsByMovieIds(ranked.stream().map(Movie::getId).toList()).stream()
					.collect(Collectors.toMap(ReviewStats::movieId, Function.identity()));
		List<PopularMovie> result = new ArrayList<>(ranked.size());
		for (Movie movie : ranked) {
			ReviewStats stats = statsByMovieId.getOrDefault(movie.getId(), ReviewStats.empty(movie.getId()));
			result.add(new PopularMovie(result.size() + 1, movie.getTmdbId(), movie.getTitle(),
					movie.getReleaseYear(), posterUrl(movie.getPosterPath(), "w185"), movie.getViewCount(),
					stats.reviewCount(), stats.averageStars(), stats.audienceScore()));
		}
		return result;
	}

	private MovieDetail toDetail(Movie movie, long viewCount) {
		ReviewStats stats = reviews.statsByMovieIds(List.of(movie.getId())).stream()
			.findFirst()
			.orElseGet(() -> ReviewStats.empty(movie.getId()));
		return new MovieDetail(movie.getTmdbId(), movie.getTitle(), movie.getOriginalTitle(), movie.getReleaseDate(),
				movie.getReleaseYear(), splitGenres(movie.getGenres()), movie.getRuntime(), movie.getOverview(),
				posterUrl(movie.getPosterPath(), "w500"), movie.getImdbId(), movie.getRottenTomatoes(),
				movie.getImdbRating(), movie.getMetascore(), viewCount, stats.reviewCount(), stats.averageStars(),
				stats.audienceScore());
	}

	/** Returns the local movie, importing it from TMDB first if needed, and reports how it was served. */
	public Movie sync(long tmdbId) {
		SyncResult result = doSync(tmdbId);
		events.publishEvent(new MovieEvents.Synced(result.outcome()));
		return result.movie();
	}

	private record SyncResult(Movie movie, MovieEvents.SyncOutcome outcome) {
	}

	private SyncResult doSync(long tmdbId) {
		Movie existing = movies.findByTmdbId(tmdbId).orElse(null);
		Instant now = clock.instant();
		if (existing != null && !existing.isStale(now, properties.syncTtl())) {
			return new SyncResult(existing, MovieEvents.SyncOutcome.CACHE_HIT);
		}
		if (existing != null && !tmdb.isEnabled()) {
			return new SyncResult(existing, MovieEvents.SyncOutcome.STALE_FALLBACK);
		}
		TmdbDtos.MovieDetails details;
		try {
			details = tmdb.details(tmdbId).orElse(null);
		}
		catch (MovieApiUnavailableException ex) {
			if (existing != null) {
				logger.warn("Keeping stale movie {}: {}", tmdbId, ex.getMessage());
				return new SyncResult(existing, MovieEvents.SyncOutcome.STALE_FALLBACK);
			}
			throw ex;
		}
		if (details == null) {
			if (existing != null) {
				return new SyncResult(existing, MovieEvents.SyncOutcome.STALE_FALLBACK);
			}
			events.publishEvent(new MovieEvents.Synced(MovieEvents.SyncOutcome.NOT_FOUND));
			throw new ResourceNotFoundException("Movie", tmdbId);
		}
		ExternalRatings ratings = (details.imdbId() == null || details.imdbId().isBlank()) ? null
				: omdb.ratings(details.imdbId()).orElse(null);

		if (existing != null) {
			existing.sync(details, ratings, now);
			return new SyncResult(movies.save(existing), MovieEvents.SyncOutcome.REFRESHED);
		}
		try {
			return new SyncResult(movies.saveAndFlush(new Movie(details, ratings, now)),
					MovieEvents.SyncOutcome.IMPORTED);
		}
		catch (DataIntegrityViolationException ex) {
			// Another request imported the same movie concurrently.
			return new SyncResult(movies.findByTmdbId(tmdbId).orElseThrow(() -> ex), MovieEvents.SyncOutcome.CACHE_HIT);
		}
	}

	public MovieRef toRef(Long tmdbId, String title, @Nullable Integer releaseYear, @Nullable String posterPath) {
		return new MovieRef(tmdbId, title, releaseYear, posterUrl(posterPath, "w185"));
	}

	public @Nullable String posterUrl(@Nullable String posterPath, String size) {
		return (posterPath == null || posterPath.isBlank()) ? null
				: properties.tmdb().imageBaseUrl() + "/" + size + posterPath;
	}

	private Map<Long, ReviewStats> localStats(List<Long> tmdbIds) {
		if (tmdbIds.isEmpty()) {
			return Map.of();
		}
		Map<Long, Long> tmdbIdByMovieId = movies.findByTmdbIdIn(tmdbIds).stream()
			.collect(Collectors.toMap(Movie::getId, Movie::getTmdbId));
		if (tmdbIdByMovieId.isEmpty()) {
			return Map.of();
		}
		return reviews.statsByMovieIds(tmdbIdByMovieId.keySet()).stream()
			.collect(Collectors.toMap(stats -> tmdbIdByMovieId.get(stats.movieId()), Function.identity()));
	}

	private static List<String> splitGenres(@Nullable String genres) {
		return (genres == null) ? List.of() : Arrays.stream(genres.split(",")).map(String::strip).toList();
	}

}
