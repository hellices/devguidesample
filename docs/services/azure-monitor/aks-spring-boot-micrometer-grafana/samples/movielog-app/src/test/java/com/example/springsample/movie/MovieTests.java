package com.example.springsample.movie;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.time.Instant;
import java.util.List;

import com.example.springsample.movie.omdb.ExternalRatings;
import com.example.springsample.movie.tmdb.TmdbDtos;
import org.junit.jupiter.api.Test;

class MovieTests {

	@Test
	void isStaleOnceTheTtlHasFullyElapsed() {
		Instant synced = Instant.parse("2026-11-01T00:00:00Z");
		Duration ttl = Duration.ofDays(7);
		Movie movie = new Movie(new TmdbDtos.MovieDetails(1L, "제목", "Title", "2020-01-01", null, null, 100,
				List.of(), null), null, synced);

		assertThat(movie.isStale(synced.plus(ttl).minusMillis(1), ttl)).isFalse();
		assertThat(movie.isStale(synced.plus(ttl), ttl)).isTrue();
	}

	@Test
	void keepsCachedRatingsWhenOmdbHasNoAnswerForTheSameTitle() {
		Instant now = Instant.parse("2026-11-01T00:00:00Z");
		Movie movie = new Movie(details("tt1"), new ExternalRatings(90, 8.1, 75), now);

		movie.sync(details("tt1"), null, now.plusSeconds(60));

		assertThat(movie.getRottenTomatoes()).isEqualTo(90);
		assertThat(movie.getImdbRating()).isEqualTo(8.1);
		assertThat(movie.getMetascore()).isEqualTo(75);
	}

	@Test
	void dropsCachedRatingsWhenTheImdbTitleChangesWithoutNewRatings() {
		Instant now = Instant.parse("2026-11-01T00:00:00Z");
		Movie movie = new Movie(details("tt1"), new ExternalRatings(90, 8.1, 75), now);

		movie.sync(details("tt2"), null, now.plusSeconds(60));

		assertThat(movie.getImdbId()).isEqualTo("tt2");
		assertThat(movie.getRottenTomatoes()).isNull();
		assertThat(movie.getImdbRating()).isNull();
		assertThat(movie.getMetascore()).isNull();
	}

	private static TmdbDtos.MovieDetails details(String imdbId) {
		return new TmdbDtos.MovieDetails(1L, "제목", "Title", "2020-01-01", null, null, 100, List.of(), imdbId);
	}

}
