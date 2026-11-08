package com.example.springsample.movie.omdb;

import org.jspecify.annotations.Nullable;

/**
 * @param rottenTomatoes Tomatometer in percent
 * @param imdbRating IMDb user rating out of 10
 * @param metascore Metacritic score out of 100
 */
public record ExternalRatings(@Nullable Integer rottenTomatoes, @Nullable Double imdbRating,
		@Nullable Integer metascore) {
}
