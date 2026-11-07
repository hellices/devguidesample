package com.example.springsample.review;

import java.time.Instant;
import java.time.LocalDate;

import org.jspecify.annotations.Nullable;

/** Flat projection used by the slice queries; mapped to {@link ReviewSummary} by the service. */
public record ReviewRow(Long id, String title, String excerpt, int rating, String authorNickname, Long tmdbId,
		String movieTitle, @Nullable LocalDate releaseDate, @Nullable String posterPath, long viewCount,
		long commentCount, Instant createdAt) {
}
