package com.example.springsample.movie;

import org.jspecify.annotations.Nullable;

/**
 * A movie ranked by page views on this site.
 *
 * @param averageRating average rating on this site in stars, {@code null} without reviews
 * @param audienceScore share of reviews rated 3.5 stars or more, in percent
 */
public record PopularMovie(int rank, Long tmdbId, String title, @Nullable Integer releaseYear,
		@Nullable String posterUrl, long viewCount, long reviewCount, @Nullable Double averageRating,
		@Nullable Integer audienceScore) {
}
