package com.example.springsample.movie;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;

import com.example.springsample.IntegrationTest;
import com.example.springsample.common.ResourceNotFoundException;
import com.example.springsample.movie.omdb.ExternalRatings;
import com.example.springsample.movie.tmdb.TmdbDtos;
import com.example.springsample.review.ReviewService;
import jakarta.persistence.EntityManager;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;

class MovieServiceTests extends IntegrationTest {

	@Autowired
	private MovieService movieService;

	@Autowired
	private ReviewService reviewService;

	@Autowired
	private JdbcTemplate jdbc;

	@Autowired
	private EntityManager entityManager;

	/** Backdates the snapshot; clears the persistence context so the test transaction sees the change. */
	private void makeStale(long tmdbId) {
		jdbc.update("update movies set synced_at = ? where tmdb_id = ?",
				Timestamp.from(Instant.now().minus(8, ChronoUnit.DAYS)), tmdbId);
		entityManager.clear();
	}

	@Test
	void importsMovieOnceWithCriticRatings() {
		stubMovie(496243, "기생충", "tt6751668", 99);

		MovieDetail first = movieService.getMovie(496243);
		MovieDetail second = movieService.getMovie(496243);

		assertThat(first.title()).isEqualTo("기생충");
		assertThat(first.posterUrl()).isEqualTo("https://image.tmdb.org/t/p/w500/poster496243.jpg");
		assertThat(first.rottenTomatoes()).isEqualTo(99);
		assertThat(first.rottenTomatoesFresh()).isTrue();
		assertThat(first.imdbRating()).isEqualTo(8.5);
		assertThat(first.genres()).containsExactly("드라마");
		assertThat(second).isEqualTo(first);
		verify(tmdb, times(1)).details(496243);
	}

	@Test
	void refreshesStaleSnapshot() {
		stubMovie(1, "옛 제목", "tt1", 50);
		movieService.getMovie(1);
		makeStale(1);
		stubMovie(1, "새 제목", "tt1", 75);

		MovieDetail refreshed = movieService.getMovie(1);

		assertThat(refreshed.title()).isEqualTo("새 제목");
		assertThat(refreshed.rottenTomatoes()).isEqualTo(75);
	}

	@Test
	void keepsStaleSnapshotWhenTmdbIsDown() {
		stubMovie(2, "제목", "tt2", null);
		movieService.getMovie(2);
		makeStale(2);
		given(tmdb.details(2)).willThrow(new MovieApiUnavailableException("down"));

		assertThat(movieService.getMovie(2).title()).isEqualTo("제목");
		verify(tmdb, times(2)).details(2);
	}

	@Test
	void unknownMovieIsNotFound() {
		given(tmdb.details(anyLong())).willReturn(Optional.empty());

		assertThatThrownBy(() -> movieService.getMovie(404)).isInstanceOf(ResourceNotFoundException.class);
		verify(tmdb).details(404);
	}

	@Test
	void movieWithoutImdbIdSkipsOmdb() {
		stubMovie(3, "독립영화", null, null);

		assertThat(movieService.getMovie(3).rottenTomatoes()).isNull();
		verifyNoInteractions(omdb);
	}

	@Test
	void searchAddsPostersPagingAndLocalAudienceScores() {
		stubMovie(10, "리뷰된 영화", "tt10", null);
		register("alice");
		register("bob");
		reviewService.create(10, "alice", 8, "좋아요", "내용");
		reviewService.create(10, "bob", 5, "그저 그래요", "내용");
		given(tmdb.search("영화", 1)).willReturn(new TmdbDtos.SearchPage(1, 3, 45, List.of(
				new TmdbDtos.SearchItem(10, "리뷰된 영화", "Reviewed", "2020-01-01", "/p10.jpg", "줄거리"),
				new TmdbDtos.SearchItem(11, "새 영화", null, "", null, null))));

		MovieSearchPage page = movieService.search("  영화 ", 1);

		assertThat(page.hasNext()).isTrue();
		assertThat(page.nextPage()).isEqualTo(2);
		assertThat(page.items()).hasSize(2);
		assertThat(page.items().get(0)).satisfies(item -> {
			assertThat(item.posterUrl()).isEqualTo("https://image.tmdb.org/t/p/w342/p10.jpg");
			assertThat(item.releaseYear()).isEqualTo(2020);
			assertThat(item.reviewCount()).isEqualTo(2);
			assertThat(item.averageRating()).isEqualTo(3.3);
		});
		assertThat(page.items().get(1)).satisfies(item -> {
			assertThat(item.posterUrl()).isNull();
			assertThat(item.releaseYear()).isNull();
			assertThat(item.reviewCount()).isZero();
		});

		MovieDetail detail = movieService.getMovie(10);
		assertThat(detail.reviewCount()).isEqualTo(2);
		assertThat(detail.averageRating()).isEqualTo(3.3);
		assertThat(detail.audienceScore()).isEqualTo(50);
	}

	@Test
	void ratingsAreOptional() {
		stubMovie(4, "제목", "tt4", null);
		given(omdb.ratings("tt4")).willReturn(Optional.of(new ExternalRatings(null, 7.1, null)));

		MovieDetail detail = movieService.getMovie(4);

		assertThat(detail.rottenTomatoes()).isNull();
		assertThat(detail.imdbRating()).isEqualTo(7.1);
	}

}
