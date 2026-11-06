package com.example.springsample.review;

/** Business events of reviews, delivered to listeners after the transaction commits. */
public final class ReviewEvents {

	private ReviewEvents() {
	}

	/**
	 * @param rating half stars, 1 (0.5 stars) to 10 (5 stars)
	 */
	public record Created(long reviewId, long tmdbId, int rating) {

		public boolean fresh() {
			return rating >= Review.FRESH_THRESHOLD;
		}

	}

	public record Viewed(long reviewId) {
	}

	public record Deleted(long reviewId) {
	}

}
