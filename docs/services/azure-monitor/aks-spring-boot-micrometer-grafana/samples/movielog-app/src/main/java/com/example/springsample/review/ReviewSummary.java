package com.example.springsample.review;

import java.time.Instant;

import com.example.springsample.movie.MovieRef;

/**
 * @param rating half stars, 1 (0.5 stars) to 10 (5 stars)
 * @param excerpt the first characters of the review
 */
public record ReviewSummary(Long id, String title, String excerpt, int rating, String authorNickname, MovieRef movie,
		long viewCount, long commentCount, Instant createdAt) {
}
