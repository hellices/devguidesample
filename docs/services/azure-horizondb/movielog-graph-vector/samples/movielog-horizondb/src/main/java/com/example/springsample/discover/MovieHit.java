package com.example.springsample.discover;

import java.util.List;

import org.jspecify.annotations.Nullable;

/** A catalog movie returned by vector search, with cosine similarity to the query (1 = identical). */
public record MovieHit(long tmdbId, String title, @Nullable String originalTitle, @Nullable Integer releaseYear,
		List<String> genres, @Nullable String overview, @Nullable String sourceUrl, double score) {
}
