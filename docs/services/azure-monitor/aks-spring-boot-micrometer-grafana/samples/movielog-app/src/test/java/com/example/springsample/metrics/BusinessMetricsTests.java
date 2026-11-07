package com.example.springsample.metrics;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.mockito.BDDMockito.given;

import java.util.List;

import com.example.springsample.IntegrationTest;
import com.example.springsample.comment.CommentRepository;
import com.example.springsample.member.MemberRepository;
import com.example.springsample.movie.MovieRepository;
import com.example.springsample.movie.tmdb.TmdbDtos;
import com.example.springsample.review.ReviewRepository;
import com.example.springsample.review.ReviewService;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.MeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Business meters are recorded after commit, so these tests run without the usual test transaction
 * and clean up their data. The registry is shared across tests: assertions compare before and after.
 */
@Transactional(propagation = Propagation.NOT_SUPPORTED)
class BusinessMetricsTests extends IntegrationTest {

	@Autowired
	private MeterRegistry registry;

	@Autowired
	private ReviewService reviewService;

	@Autowired
	private MovieRepository movies;

	@Autowired
	private ReviewRepository reviews;

	@Autowired
	private CommentRepository comments;

	@Autowired
	private MemberRepository members;

	@AfterEach
	void deleteData() {
		comments.deleteAllInBatch();
		reviews.deleteAllInBatch();
		movies.deleteAllInBatch();
		members.deleteAllInBatch();
	}

	@Test
	void countsMovieViewsPerChannelAndPerMovie() throws Exception {
		stubMovie(496243, "기생충", "tt6751668", 99);
		double web = count("movielog.movie.views", "channel", "web");
		double api = count("movielog.movie.views", "channel", "api");

		mockMvc.perform(get("/movies/{id}", 496243)).andExpect(status().isOk());
		mockMvc.perform(get("/movies/{id}", 496243)).andExpect(status().isOk());
		mockMvc.perform(get("/api/movies/{id}", 496243))
			.andExpect(jsonPath("$.viewCount").value(3));

		assertThat(count("movielog.movie.views", "channel", "web")).isEqualTo(web + 2);
		assertThat(count("movielog.movie.views", "channel", "api")).isEqualTo(api + 1);
		mockMvc.perform(get("/api/movies/popular"))
			.andExpect(jsonPath("$[0].rank").value(1))
			.andExpect(jsonPath("$[0].tmdbId").value(496243))
			.andExpect(jsonPath("$[0].viewCount").value(3));
	}

	@Test
	void reviewFormsDoNotCountAsMovieViews() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		register("alice");
		double views = count("movielog.movie.views", "channel", "web");

		mockMvc.perform(get("/movies/{id}/reviews/new", 1).with(user("alice"))).andExpect(status().isOk());

		assertThat(count("movielog.movie.views", "channel", "web")).isEqualTo(views);
		assertThat(movies.findByTmdbId(1L)).hasValueSatisfying(movie -> assertThat(movie.getViewCount()).isZero());
	}

	@Test
	void countsReviewsWithVerdictAndRatingDistribution() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		register("alice");
		double fresh = count("movielog.reviews.posted", "channel", "api", "verdict", "fresh");
		DistributionSummary rating = registry.get("movielog.review.rating").summary();
		long ratings = rating.count();
		double ratingTotal = rating.totalAmount();

		mockMvc.perform(post("/api/movies/{id}/reviews", 1).with(user("alice")).with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"rating\":9,\"title\":\"좋아요\",\"content\":\"내용\"}"))
			.andExpect(status().isCreated());

		assertThat(count("movielog.reviews.posted", "channel", "api", "verdict", "fresh")).isEqualTo(fresh + 1);
		assertThat(rating.count()).isEqualTo(ratings + 1);
		assertThat(rating.totalAmount()).isEqualTo(ratingTotal + 4.5);
	}

	@Test
	void rejectedWritesAreNotCounted() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		reviewService.create(1, register("alice"), 8, "첫 리뷰", "내용");
		double created = count("movielog.reviews.posted", "channel", "api", "verdict", "fresh");
		DistributionSummary rating = registry.get("movielog.review.rating").summary();
		long ratings = rating.count();
		double ratingTotal = rating.totalAmount();

		mockMvc.perform(post("/api/movies/{id}/reviews", 1).with(user("alice")).with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"rating\":9,\"title\":\"또\",\"content\":\"중복\"}"))
			.andExpect(status().isConflict());

		assertThat(count("movielog.reviews.posted", "channel", "api", "verdict", "fresh")).isEqualTo(created);
		assertThat(rating.count()).isEqualTo(ratings);
		assertThat(rating.totalAmount()).isEqualTo(ratingTotal);
	}

	@Test
	void countsCommentsAndSignupsFromWebForms() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		Long reviewId = reviewService.create(1, register("alice"), 8, "제목", "내용").id();
		double commentsBefore = count("movielog.comments.posted", "channel", "web");
		double signupsBefore = count("movielog.members.signups", "channel", "web");

		mockMvc.perform(post("/reviews/{id}/comments", reviewId).with(user("alice")).with(csrf())
				.param("content", "댓글"))
			.andExpect(status().is3xxRedirection());
		mockMvc.perform(post("/signup").with(csrf())
				.param("username", "carol").param("nickname", "캐롤")
				.param("password", "password123").param("passwordConfirm", "password123"))
			.andExpect(status().is3xxRedirection());

		assertThat(count("movielog.comments.posted", "channel", "web")).isEqualTo(commentsBefore + 1);
		assertThat(count("movielog.members.signups", "channel", "web")).isEqualTo(signupsBefore + 1);
	}

	@Test
	void separatesNewSearchesFromScrollingAndCatalogLookups() throws Exception {
		given(tmdb.search("기생충", 1)).willReturn(new TmdbDtos.SearchPage(1, 2, 21,
				List.of(new TmdbDtos.SearchItem(496243, "기생충", null, "2019-05-30", null, null))));
		given(tmdb.search("기생충", 2)).willReturn(new TmdbDtos.SearchPage(2, 2, 21, List.of()));
		stubMovie(496243, "기생충", "tt6751668", null);
		double found = count("movielog.movie.searches", "channel", "api", "outcome", "found");
		double scrolls = count("movielog.movie.search.scrolls", "channel", "api", "outcome", "empty");
		double searchesEmpty = count("movielog.movie.searches", "channel", "api", "outcome", "empty");
		double scrollsFound = count("movielog.movie.search.scrolls", "channel", "api", "outcome", "found");
		double imported = count("movielog.movie.catalog.lookups", "outcome", "imported");
		double cacheHits = count("movielog.movie.catalog.lookups", "outcome", "cache_hit");

		mockMvc.perform(get("/api/movies/search").param("q", "기생충")).andExpect(status().isOk());
		mockMvc.perform(get("/api/movies/search").param("q", "기생충").param("page", "2")).andExpect(status().isOk());
		mockMvc.perform(get("/api/movies/{id}", 496243)).andExpect(status().isOk());
		mockMvc.perform(get("/api/movies/{id}", 496243)).andExpect(status().isOk());

		assertThat(count("movielog.movie.searches", "channel", "api", "outcome", "found")).isEqualTo(found + 1);
		assertThat(count("movielog.movie.search.scrolls", "channel", "api", "outcome", "empty")).isEqualTo(scrolls + 1);
		assertThat(count("movielog.movie.searches", "channel", "api", "outcome", "empty")).isEqualTo(searchesEmpty);
		assertThat(count("movielog.movie.search.scrolls", "channel", "api", "outcome", "found")).isEqualTo(scrollsFound);
		assertThat(count("movielog.movie.catalog.lookups", "outcome", "imported")).isEqualTo(imported + 1);
		assertThat(count("movielog.movie.catalog.lookups", "outcome", "cache_hit")).isEqualTo(cacheHits + 1);
	}

	@Test
	void deleteCountersExistBeforeTheFirstDelete() {
		for (String channel : List.of("web", "api")) {
			assertThat(registry.find("movielog.reviews.deleted").tags("channel", channel).counter()).isNotNull();
			assertThat(registry.find("movielog.comments.deleted").tags("channel", channel).counter()).isNotNull();
		}
	}

	private double count(String name, String... tags) {
		Counter counter = registry.find(name).tags(tags).counter();
		return (counter == null) ? 0 : counter.count();
	}

}
