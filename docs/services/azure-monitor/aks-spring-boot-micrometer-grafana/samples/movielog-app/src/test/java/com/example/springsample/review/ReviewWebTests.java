package com.example.springsample.review;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.matchesPattern;
import static org.hamcrest.Matchers.not;
import static org.mockito.BDDMockito.given;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.flash;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.model;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.redirectedUrl;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.redirectedUrlPattern;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.view;

import java.util.List;

import com.example.springsample.IntegrationTest;
import com.example.springsample.member.MemberRepository;
import com.example.springsample.movie.tmdb.TmdbDtos;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.crypto.password.PasswordEncoder;

class ReviewWebTests extends IntegrationTest {

	@Autowired
	private MemberRepository memberRepository;

	@Autowired
	private ReviewService reviewService;

	@Autowired
	private PasswordEncoder passwordEncoder;

	@Test
	void signsUpAndRedirectsToLogin() throws Exception {
		mockMvc.perform(post("/signup").with(csrf())
				.param("username", "carol")
				.param("nickname", "캐롤")
				.param("password", "password123")
				.param("passwordConfirm", "password123"))
			.andExpect(status().is3xxRedirection())
			.andExpect(redirectedUrl("/login?registered"));

		assertThat(memberRepository.findByUsername("carol")).hasValueSatisfying(member -> {
			assertThat(member.getPassword()).startsWith("{bcrypt}").isNotEqualTo("password123");
			assertThat(passwordEncoder.matches("password123", member.getPassword())).isTrue();
		});
	}

	@Test
	void signupRejectsMismatchedPasswordConfirmation() throws Exception {
		mockMvc.perform(post("/signup").with(csrf())
				.param("username", "dave")
				.param("nickname", "데이브")
				.param("password", "password123")
				.param("passwordConfirm", "different123"))
			.andExpect(status().isOk())
			.andExpect(view().name("auth/signup"))
			.andExpect(model().attributeHasFieldErrors("form", "passwordConfirm"));

		assertThat(memberRepository.findByUsername("dave")).isEmpty();
	}

	@Test
	void signupRejectsDuplicateUsername() throws Exception {
		register("carol");
		long members = memberRepository.count();

		mockMvc.perform(post("/signup").with(csrf())
				.param("username", "carol")
				.param("nickname", "캐롤2")
				.param("password", "password123")
				.param("passwordConfirm", "password123"))
			.andExpect(status().isOk())
			.andExpect(view().name("auth/signup"))
			.andExpect(model().attributeHasFieldErrors("form", "username"))
			.andExpect(model().attributeErrorCount("form", 1));

		assertThat(memberRepository.count()).isEqualTo(members);
	}

	@Test
	void feedShowsReviewsWithPosters() throws Exception {
		stubMovie(496243, "기생충", "tt6751668", 99);
		reviewService.create(496243, register("alice"), 9, "첫 화면에 보이는 리뷰", "내용");

		mockMvc.perform(get("/reviews"))
			.andExpect(status().isOk())
			.andExpect(content().string(containsString("첫 화면에 보이는 리뷰")))
			.andExpect(content().string(containsString("https://image.tmdb.org/t/p/w185/poster496243.jpg")))
			.andExpect(content().string(containsString("data-has-next=\"false\"")));
	}

	@Test
	void searchPageShowsPosterGrid() throws Exception {
		given(tmdb.search("기생충", 1)).willReturn(new TmdbDtos.SearchPage(1, 1, 1, List.of(
				new TmdbDtos.SearchItem(496243, "기생충", "기생충", "2019-05-30", "/abc.jpg", "줄거리"))));

		mockMvc.perform(get("/movies").param("q", "기생충"))
			.andExpect(status().isOk())
			.andExpect(content().string(containsString("https://image.tmdb.org/t/p/w342/abc.jpg")))
			.andExpect(content().string(containsString("/movies/496243")));
	}

	@Test
	void searchPageExplainsMissingApiKey() throws Exception {
		given(tmdb.isEnabled()).willReturn(false);

		mockMvc.perform(get("/movies").param("q", "기생충"))
			.andExpect(status().isOk())
			.andExpect(content().string(containsString("TMDB_API_KEY")));
	}

	@Test
	void moviePageShowsScoresAndWriteButton() throws Exception {
		stubMovie(496243, "기생충", "tt6751668", 99);
		register("alice");

		mockMvc.perform(get("/movies/{id}", 496243).with(user("alice")))
			.andExpect(status().isOk())
			.andExpect(content().string(containsString("99%")))
			.andExpect(content().string(containsString("신선 (평론가)")))
			.andExpect(content().string(containsString("/movies/496243/reviews/new")));
	}

	@Test
	void showsReviewFormForMovie() throws Exception {
		stubMovie(496243, "기생충", "tt6751668", 99);
		register("alice");

		mockMvc.perform(get("/movies/{id}/reviews/new", 496243).with(user("alice")))
			.andExpect(status().isOk())
			.andExpect(view().name("reviews/form"))
			.andExpect(content().string(containsString("기생충")))
			.andExpect(content().string(containsString("name=\"rating\"")));
	}

	@Test
	void invalidReviewRedisplaysFormWithErrors() throws Exception {
		stubMovie(496243, "기생충", "tt6751668", 99);
		register("alice");

		mockMvc.perform(post("/movies/{id}/reviews", 496243).with(user("alice")).with(csrf())
				.param("rating", "")
				.param("title", "")
				.param("content", "본문"))
			.andExpect(status().isOk())
			.andExpect(view().name("reviews/form"))
			.andExpect(model().attributeHasFieldErrors("form", "rating", "title"))
			.andExpect(content().string(containsString("별점을 선택하세요.")));
	}

	@Test
	void editFormShowsExistingRating() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		Long id = reviewService.create(1, register("alice"), 7, "제목", "내용").id();

		mockMvc.perform(get("/reviews/{id}/edit", id).with(user("alice")))
			.andExpect(status().isOk())
			.andExpect(content().string(matchesPattern("(?s).*id=\"rating-7\" value=\"7\"[^>]*checked=\"checked\".*")))
			.andExpect(content().string(containsString("3.5 / 5")));
	}

	@Test
	void writesReviewThroughFormAndThenLinksToIt() throws Exception {
		stubMovie(496243, "기생충", "tt6751668", 99);
		register("alice");

		var result = mockMvc.perform(post("/movies/{id}/reviews", 496243).with(user("alice")).with(csrf())
				.param("rating", "9")
				.param("title", "폼으로 쓴 리뷰")
				.param("content", "본문"))
			.andExpect(status().is3xxRedirection())
			.andExpect(redirectedUrlPattern("/reviews/*"))
			.andReturn();
		String reviewUrl = result.getResponse().getRedirectedUrl();

		mockMvc.perform(get(reviewUrl).with(user("alice")))
			.andExpect(status().isOk())
			.andExpect(content().string(containsString("폼으로 쓴 리뷰")))
			.andExpect(content().string(containsString("/edit")));
		mockMvc.perform(get("/movies/{id}", 496243).with(user("alice")))
			.andExpect(content().string(containsString("내 리뷰 보기")))
			.andExpect(content().string(containsString("100%")));
	}

	@Test
	void secondReviewOfSameMovieRedirectsToEdit() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		Long existing = reviewService.create(1, register("alice"), 6, "첫 리뷰", "내용").id();

		mockMvc.perform(get("/movies/{id}/reviews/new", 1).with(user("alice")))
			.andExpect(status().is3xxRedirection())
			.andExpect(redirectedUrl("/reviews/" + existing + "/edit"))
			.andExpect(flash().attributeExists("notice"));
	}

	@Test
	void hidesEditButtonsFromOtherUsers() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		Long id = reviewService.create(1, register("writer"), 8, "제목", "내용").id();
		register("other");

		mockMvc.perform(get("/reviews/{id}", id).with(user("other")))
			.andExpect(status().isOk())
			.andExpect(content().string(not(containsString("/reviews/" + id + "/edit"))));
	}

	@Test
	void forbidsEditingSomeoneElsesReview() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		Long id = reviewService.create(1, register("writer"), 8, "제목", "내용").id();
		register("other");

		mockMvc.perform(get("/reviews/{id}/edit", id).with(user("other")))
			.andExpect(status().isForbidden());
	}

	@Test
	void escapesUserContent() throws Exception {
		stubMovie(1, "영화", "tt1", null);
		// Different payloads so a regression in either field cannot hide behind the other.
		Long id = reviewService.create(1, register("writer"), 8, "<script>alert('title')</script>",
				"<img src=x onerror=alert('content')>").id();

		mockMvc.perform(get("/reviews/{id}", id))
			.andExpect(content().string(not(containsString("<script>alert('title')</script>"))))
			.andExpect(content().string(containsString("&lt;script&gt;alert(&#39;title&#39;)&lt;/script&gt;")))
			.andExpect(content().string(not(containsString("<img src=x onerror=alert('content')>"))))
			.andExpect(content().string(containsString("&lt;img src=x onerror=alert(&#39;content&#39;)&gt;")));
	}

	@Test
	void deletingReviewReturnsToMoviePage() throws Exception {
		stubMovie(7, "영화", "tt7", null);
		Long id = reviewService.create(7, register("writer"), 8, "제목", "내용").id();

		mockMvc.perform(post("/reviews/{id}/delete", id).with(user("writer")).with(csrf()))
			.andExpect(status().is3xxRedirection())
			.andExpect(redirectedUrl("/movies/7"));

		mockMvc.perform(get("/reviews/{id}", id)).andExpect(status().isNotFound());
	}

}
