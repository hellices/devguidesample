package com.example.springsample.review;

import java.time.Instant;

import com.example.springsample.movie.MovieRef;

/**
 * @param rating half stars, 1 (0.5 stars) to 10 (5 stars)
 */
public record ReviewDetail(Long id, String title, String content, int rating, String authorUsername,
		String authorNickname, MovieRef movie, long viewCount, long commentCount, Instant createdAt,
		Instant updatedAt) {
}
