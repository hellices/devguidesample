package com.example.springsample.review;

import org.jspecify.annotations.Nullable;

/**
 * Aggregated reviews of one movie. Ratings are stored in half stars (1 to 10).
 *
 * @param averageHalfStars average rating in half stars
 * @param freshCount reviews rated 3.5 stars or more
 */
public record ReviewStats(Long movieId, long reviewCount, @Nullable Double averageHalfStars, long freshCount) {

	public static ReviewStats empty(Long movieId) {
		return new ReviewStats(movieId, 0, null, 0);
	}

	/** Average in stars, rounded to one decimal. */
	public @Nullable Double averageStars() {
		return (reviewCount == 0 || averageHalfStars == null) ? null : Math.round(averageHalfStars * 5) / 10.0;
	}

	/** Percentage of fresh reviews, like an audience Tomatometer. */
	public @Nullable Integer audienceScore() {
		return (reviewCount == 0) ? null : (int) Math.round(freshCount * 100.0 / reviewCount);
	}

}
