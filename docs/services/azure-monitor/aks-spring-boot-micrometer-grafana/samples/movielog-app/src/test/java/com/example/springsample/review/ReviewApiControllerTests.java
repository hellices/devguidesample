package com.example.springsample.review;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.hasSize;
import static org.mockito.BDDMockito.given;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.ArrayList;
import java.util.List;

import com.example.springsample.IntegrationTest;
import com.example.springsample.movie.MovieApiUnavailableException;
import com.jayway.jsonpath.JsonPath;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;

class ReviewApiControllerTests extends IntegrationTest {

	@Autowired
	private ReviewService reviewService;

	private static final String BODY = "{\"rating\":9,\"title\":\"인생 영화\",\"content\":\"계단 장면이 압권\"}";

	@Test
	void createsReviewAndImportsMovie() throws Exception {
		stubMovie(496243, "기생충", "tt6751668", 99);
		register("alice");

		var created = mockMvc.perform(post("/api/movies/{id}/reviews", 496243).with(user("alice")).with(csrf())
				.contentType(MediaType.APPLICATION_JSON).content(BODY))
			.andExpect(status().isCreated())
			.andExpect(jsonPath("$.rating").value(9))
			.andExpect(jsonPath("$.authorNickname").value("alice님"))
			.andExpect(jsonPath("$.movie.title").value("기생충"))
			.andExpect(jsonPath("$.movie.releaseYear").value(2019))
			.andExpect(jsonPath("$.movie.posterUrl").value("https://image.tmdb.org/t/p/w185/poster496243.jpg"))
			.andReturn().getResponse();
		Number createdId = JsonPath.read(created.getContentAsString(), "$.id");
		assertThat(created.getHeader("Location")).isEqualTo("/api/reviews/" + createdId);

		mockMvc.perform(get("/api/movies/{id}", 496243))
			.andExpect(jsonPath("$.rottenTomatoes").value(99))
			.andExpect(jsonPath("$.reviewCount").value(1))
			.andExpect(jsonPath("$.averageRating").value(4.5))
			.andExpect(jsonPath("$.audienceScore").value(100));
	}

	@Test
	void allowsOneReviewPerMemberAndMovie() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		register("alice");
		Long existing = reviewService.create(1, "alice", 6, "첫 리뷰", "내용").id();

		mockMvc.perform(post("/api/movies/{id}/reviews", 1).with(user("alice")).with(csrf())
				.contentType(MediaType.APPLICATION_JSON).content(BODY))
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.code").value("DUPLICATE_REVIEW"))
			.andExpect(jsonPath("$.reviewId").value(existing));
	}

	@Test
	void reviewingUnknownMovieIsNotFound() throws Exception {
		register("alice");

		mockMvc.perform(post("/api/movies/{id}/reviews", 999).with(user("alice")).with(csrf())
				.contentType(MediaType.APPLICATION_JSON).content(BODY))
			.andExpect(status().isNotFound());
	}

	@Test
	void validatesRatingRange() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		register("alice");

		mockMvc.perform(post("/api/movies/{id}/reviews", 1).with(user("alice")).with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"rating\":11,\"title\":\"제목\",\"content\":\"내용\"}"))
			.andExpect(status().isBadRequest())
			.andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON));
	}

	@Test
	void scrollsThroughFeedWithCursor() throws Exception {
		for (int i = 1; i <= 25; i++) {
			stubMovie(i, "영화 " + i, "tt" + i, null);
			reviewService.create(i, i == 1 ? register("alice") : "alice", 8, "리뷰 " + i, "내용 " + i);
		}

		List<Integer> seen = new ArrayList<>();
		String cursor = null;
		int requests = 0;
		boolean hasNext = true;
		while (hasNext) {
			var request = get("/api/reviews").param("size", "10");
			if (cursor != null) {
				request.param("cursor", cursor);
			}
			String body = mockMvc.perform(request).andExpect(status().isOk())
				.andReturn().getResponse().getContentAsString();
			seen.addAll(JsonPath.read(body, "$.items[*].id"));
			hasNext = JsonPath.read(body, "$.hasNext");
			Object next = JsonPath.read(body, "$.nextCursor");
			cursor = (next == null) ? null : next.toString();
			requests++;
		}

		assertThat(requests).isEqualTo(3);
		assertThat(seen).hasSize(25).doesNotHaveDuplicates()
			.isSortedAccordingTo((a, b) -> Integer.compare(b, a));
	}

	@Test
	void listsReviewsOfOneMovie() throws Exception {
		stubMovie(1, "영화 A", "tt1", null);
		stubMovie(2, "영화 B", "tt2", null);
		reviewService.create(1, register("alice"), 8, "A 리뷰", "내용");
		reviewService.create(1, register("bob"), 4, "A 리뷰 2", "내용");
		reviewService.create(2, "alice", 6, "B 리뷰", "내용");

		mockMvc.perform(get("/api/movies/{id}/reviews", 1))
			.andExpect(jsonPath("$.items", hasSize(2)))
			.andExpect(jsonPath("$.items[0].title").value("A 리뷰 2"))
			.andExpect(jsonPath("$.hasNext").value(false));
	}

	@Test
	void searchesReviewTextAndMovieTitle() throws Exception {
		stubMovie(1, "Inception", "tt1", null);
		stubMovie(2, "기생충", "tt2", null);
		reviewService.create(1, register("alice"), 8, "꿈속의 꿈", "팽이가 돈다");
		reviewService.create(2, "alice", 10, "100% 추천", "계단");

		mockMvc.perform(get("/api/reviews").param("q", "inception"))
			.andExpect(jsonPath("$.items", hasSize(1)))
			.andExpect(jsonPath("$.items[0].movie.title").value("Inception"));
		mockMvc.perform(get("/api/reviews").param("q", "팽이"))
			.andExpect(jsonPath("$.items", hasSize(1)));
		mockMvc.perform(get("/api/reviews").param("q", "%"))
			.andExpect(jsonPath("$.items", hasSize(1)))
			.andExpect(jsonPath("$.items[0].title").value("100% 추천"));
	}

	@Test
	void countsViews() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		Long id = reviewService.create(1, register("alice"), 8, "제목", "내용").id();

		mockMvc.perform(get("/api/reviews/{id}", id)).andExpect(jsonPath("$.viewCount").value(1));
		mockMvc.perform(get("/api/reviews/{id}", id)).andExpect(jsonPath("$.viewCount").value(2));
	}

	@Test
	void onlyAuthorCanUpdateOrDelete() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		Long id = reviewService.create(1, register("alice"), 8, "제목", "내용").id();
		register("bob");

		mockMvc.perform(put("/api/reviews/{id}", id).with(user("bob")).with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"rating\":2,\"title\":\"남의 수정\",\"content\":\"덮어쓰기\"}"))
			.andExpect(status().isForbidden())
			.andExpect(jsonPath("$.code").value("NOT_OWNER"));
		mockMvc.perform(get("/api/reviews/{id}", id))
			.andExpect(jsonPath("$.rating").value(8))
			.andExpect(jsonPath("$.title").value("제목"))
			.andExpect(jsonPath("$.content").value("내용"));
		mockMvc.perform(delete("/api/reviews/{id}", id).with(user("bob")).with(csrf()))
			.andExpect(status().isForbidden());

		mockMvc.perform(put("/api/reviews/{id}", id).with(user("alice")).with(csrf())
				.contentType(MediaType.APPLICATION_JSON).content(BODY))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.rating").value(9))
			.andExpect(jsonPath("$.title").value("인생 영화"));
		mockMvc.perform(delete("/api/reviews/{id}", id).with(user("alice")).with(csrf()))
			.andExpect(status().isNoContent());
		mockMvc.perform(get("/api/reviews/{id}", id)).andExpect(status().isNotFound());
	}

	@Test
	void movieSearchReportsUnavailableApi() throws Exception {
		given(tmdb.search("x", 1)).willThrow(new MovieApiUnavailableException("down"));

		mockMvc.perform(get("/api/movies/search").param("q", "x"))
			.andExpect(status().isServiceUnavailable())
			.andExpect(jsonPath("$.code").value("MOVIE_API_UNAVAILABLE"));
	}

}
