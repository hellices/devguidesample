package com.example.springsample.movie;

/**
 * Business events of the movie catalog. Published by {@link MovieService}; listeners such as the metrics
 * recorder receive them after the surrounding transaction commits (or immediately without one).
 */
public final class MovieEvents {

	private MovieEvents() {
	}

	/** A user opened a movie page ("movie click"). */
	public record Viewed(long tmdbId) {
	}

	/**
	 * A movie search page was requested; {@code page} 1 is a new search, higher pages are infinite scrolling.
	 */
	public record Searched(SearchOutcome outcome, int page, long totalResults) {
	}

	public enum SearchOutcome {

		/** At least one result. */
		FOUND,
		/** The search worked but found nothing. */
		EMPTY,
		/** TMDB failed or timed out. */
		ERROR,
		/** No TMDB key configured. */
		DISABLED

	}

	/** How a movie request was served from the local snapshot or TMDB. */
	public record Synced(SyncOutcome outcome) {
	}

	public enum SyncOutcome {

		/** Fresh local snapshot, no external call. */
		CACHE_HIT,
		/** First time: fetched from TMDB and stored. */
		IMPORTED,
		/** Stale snapshot refreshed from TMDB. */
		REFRESHED,
		/** Stale snapshot kept because TMDB was unavailable. */
		STALE_FALLBACK,
		/** TMDB does not know the movie. */
		NOT_FOUND

	}

}
