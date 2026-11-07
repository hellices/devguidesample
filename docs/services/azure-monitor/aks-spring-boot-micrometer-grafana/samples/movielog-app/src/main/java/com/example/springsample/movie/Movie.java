package com.example.springsample.movie;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;

import com.example.springsample.movie.omdb.ExternalRatings;
import com.example.springsample.movie.tmdb.TmdbDtos;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EntityListeners;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.ColumnDefault;
import org.jspecify.annotations.Nullable;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

/** Local snapshot of a TMDB movie, created the first time the movie is opened. */
@Entity
@Table(name = "movies")
@EntityListeners(AuditingEntityListener.class)
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Movie {

	private static final int OVERVIEW_MAX_LENGTH = 4_000;

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(nullable = false, unique = true)
	private Long tmdbId;

	@Column(length = 20)
	private @Nullable String imdbId;

	@Column(nullable = false, length = 300)
	private String title;

	@Column(length = 300)
	private @Nullable String originalTitle;

	private @Nullable LocalDate releaseDate;

	@Column(length = 200)
	private @Nullable String posterPath;

	@Column(length = OVERVIEW_MAX_LENGTH)
	private @Nullable String overview;

	private @Nullable Integer runtime;

	@Column(length = 300)
	private @Nullable String genres;

	private @Nullable Integer rottenTomatoes;

	private @Nullable Double imdbRating;

	private @Nullable Integer metascore;

	@Column(nullable = false)
	private Instant syncedAt;

	/** Page views, changed only through {@link MovieRepository#incrementViewCount} so syncs never overwrite it. */
	@ColumnDefault("0")
	@Column(nullable = false, insertable = false, updatable = false)
	private long viewCount;

	@CreatedDate
	@Column(nullable = false, updatable = false)
	private Instant createdAt;

	public Movie(TmdbDtos.MovieDetails details, @Nullable ExternalRatings ratings, Instant now) {
		this.tmdbId = details.id();
		sync(details, ratings, now);
	}

	public void sync(TmdbDtos.MovieDetails details, @Nullable ExternalRatings ratings, Instant now) {
		this.imdbId = blankToNull(details.imdbId());
		this.title = truncate(details.title(), 300);
		this.originalTitle = truncate(details.originalTitle(), 300);
		this.releaseDate = TmdbDtos.parseDate(details.releaseDate());
		this.posterPath = blankToNull(details.posterPath());
		this.overview = truncate(blankToNull(details.overview()), OVERVIEW_MAX_LENGTH);
		this.runtime = (details.runtime() == null || details.runtime() == 0) ? null : details.runtime();
		this.genres = (details.genres() == null || details.genres().isEmpty()) ? null
				: truncate(String.join(", ", details.genres().stream().map(TmdbDtos.Genre::name).toList()), 300);
		if (ratings != null) {
			this.rottenTomatoes = ratings.rottenTomatoes();
			this.imdbRating = ratings.imdbRating();
			this.metascore = ratings.metascore();
		}
		this.syncedAt = now;
	}

	public boolean isStale(Instant now, Duration ttl) {
		return !now.isBefore(syncedAt.plus(ttl));
	}

	public @Nullable Integer getReleaseYear() {
		return (releaseDate == null) ? null : releaseDate.getYear();
	}

	private static @Nullable String blankToNull(@Nullable String value) {
		return (value == null || value.isBlank()) ? null : value;
	}

	/** Cuts at a code point boundary so a surrogate pair is never split. */
	private static @Nullable String truncate(@Nullable String value, int max) {
		if (value == null || value.length() <= max) {
			return value;
		}
		int end = max;
		if (Character.isHighSurrogate(value.charAt(end - 1)) && Character.isLowSurrogate(value.charAt(end))) {
			end--;
		}
		return value.substring(0, end);
	}

}
