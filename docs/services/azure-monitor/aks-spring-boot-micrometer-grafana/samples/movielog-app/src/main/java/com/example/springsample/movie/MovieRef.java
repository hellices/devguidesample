package com.example.springsample.movie;

import org.jspecify.annotations.Nullable;

/** Compact movie reference embedded in review responses. */
public record MovieRef(Long tmdbId, String title, @Nullable Integer releaseYear, @Nullable String posterUrl) {
}
