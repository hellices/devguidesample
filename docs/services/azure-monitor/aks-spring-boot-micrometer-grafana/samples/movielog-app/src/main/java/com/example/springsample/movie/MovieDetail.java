package com.example.springsample.movie;

import java.time.LocalDate;
import java.util.List;

import org.jspecify.annotations.Nullable;

/**
 * Movie information with critic scores (via OMDb) and this site's audience scores.
 *
 * @param rottenTomatoes Rotten Tomatoes Tomatometer in percent
 * @param imdbRating IMDb rating out of 10
 * @param metascore Metacritic score out of 100
 * @param viewCount page views on this site
 * @param averageRating average rating on this site in stars (0.5 to 5)
 * @param audienceScore share of this site's reviews rated 3.5 stars or more, in percent
 */
public record MovieDetail(Long tmdbId, String title, @Nullable String originalTitle, @Nullable LocalDate releaseDate,
		@Nullable Integer releaseYear, List<String> genres, @Nullable Integer runtime, @Nullable String overview,
		@Nullable String posterUrl, @Nullable String imdbId, @Nullable Integer rottenTomatoes,
		@Nullable Double imdbRating, @Nullable Integer metascore, long viewCount, long reviewCount,
		@Nullable Double averageRating, @Nullable Integer audienceScore) {

	public boolean rottenTomatoesFresh() {
		return rottenTomatoes != null && rottenTomatoes >= 60;
	}

	public boolean audienceFresh() {
		return audienceScore != null && audienceScore >= 60;
	}

	/** Average rounded to the nearest half star, in half stars (1 to 10), for star icons. */
	public @Nullable Integer averageHalfStars() {
		return (averageRating == null) ? null : (int) Math.round(averageRating * 2);
	}

}
