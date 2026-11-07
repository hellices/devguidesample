package com.example.springsample.movie.tmdb;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import org.jspecify.annotations.Nullable;

/** Wire types of the TMDB v3 API (only the fields this application reads). */
public final class TmdbDtos {

	private TmdbDtos() {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record SearchPage(int page, @JsonProperty("total_pages") int totalPages,
			@JsonProperty("total_results") long totalResults, List<SearchItem> results) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record SearchItem(long id, String title, @JsonProperty("original_title") @Nullable String originalTitle,
			@JsonProperty("release_date") @Nullable String releaseDate,
			@JsonProperty("poster_path") @Nullable String posterPath, @Nullable String overview) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record MovieDetails(long id, String title, @JsonProperty("original_title") @Nullable String originalTitle,
			@JsonProperty("release_date") @Nullable String releaseDate,
			@JsonProperty("poster_path") @Nullable String posterPath, @Nullable String overview,
			@Nullable Integer runtime, @Nullable List<Genre> genres,
			@JsonProperty("imdb_id") @Nullable String imdbId) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record Genre(long id, String name) {
	}

	/** TMDB sends {@code ""} for unknown dates. */
	public static @Nullable LocalDate parseDate(@Nullable String value) {
		if (value == null || value.isBlank()) {
			return null;
		}
		try {
			return LocalDate.parse(value);
		}
		catch (DateTimeParseException ex) {
			return null;
		}
	}

}
