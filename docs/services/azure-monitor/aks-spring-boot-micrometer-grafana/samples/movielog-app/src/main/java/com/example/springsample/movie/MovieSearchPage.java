package com.example.springsample.movie;

import java.util.List;

import org.jspecify.annotations.Nullable;

/**
 * One page of TMDB search results; pass {@code nextPage} back as {@code page} to continue scrolling.
 */
public record MovieSearchPage(List<Item> items, int page, @Nullable Integer nextPage, boolean hasNext,
		long totalResults) {

	/**
	 * @param reviewCount reviews written on this site
	 * @param averageRating average rating on this site in stars (0.5 to 5), {@code null} without reviews
	 */
	public record Item(Long tmdbId, String title, @Nullable String originalTitle, @Nullable Integer releaseYear,
			@Nullable String posterUrl, @Nullable String overview, long reviewCount, @Nullable Double averageRating) {
	}

}
