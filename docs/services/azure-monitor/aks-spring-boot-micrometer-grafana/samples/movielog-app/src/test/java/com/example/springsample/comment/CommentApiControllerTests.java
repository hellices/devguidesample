package com.example.springsample.comment;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.springsample.IntegrationTest;
import com.example.springsample.review.ReviewService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;

class CommentApiControllerTests extends IntegrationTest {

	@Autowired
	private ReviewService reviewService;

	@Autowired
	private CommentService commentService;

	private Long reviewId;

	@BeforeEach
	void setUp() {
		stubMovie(1, "영화", "tt1", null);
		register("alice");
		register("bob");
		reviewId = reviewService.create(1, "alice", 8, "제목", "내용").id();
	}

	@Test
	void addsCommentAndUpdatesCount() throws Exception {
		mockMvc.perform(post("/api/reviews/{id}/comments", reviewId).with(user("bob")).with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"content\":\"공감합니다\"}"))
			.andExpect(status().isCreated())
			.andExpect(jsonPath("$.authorNickname").value("bob님"));

		mockMvc.perform(get("/api/reviews/{id}/comments", reviewId))
			.andExpect(jsonPath("$[0].content").value("공감합니다"));
		mockMvc.perform(get("/api/reviews/{id}", reviewId))
			.andExpect(jsonPath("$.commentCount").value(1));
	}

	@Test
	void onlyCommentAuthorCanDelete() throws Exception {
		Long commentId = commentService.create(reviewId, "bob", "댓글").id();

		mockMvc.perform(delete("/api/comments/{id}", commentId).with(user("alice")).with(csrf()))
			.andExpect(status().isForbidden());
		mockMvc.perform(delete("/api/comments/{id}", commentId).with(user("bob")).with(csrf()))
			.andExpect(status().isNoContent());
		mockMvc.perform(get("/api/reviews/{id}", reviewId))
			.andExpect(jsonPath("$.commentCount").value(0));
	}

	@Test
	void deletingReviewRemovesItsComments() throws Exception {
		commentService.create(reviewId, "bob", "댓글");

		mockMvc.perform(delete("/api/reviews/{id}", reviewId).with(user("alice")).with(csrf()))
			.andExpect(status().isNoContent());
		mockMvc.perform(get("/api/reviews/{id}/comments", reviewId))
			.andExpect(status().isNotFound());
	}

	@Test
	void commentsOfMissingReviewReturnNotFound() throws Exception {
		mockMvc.perform(post("/api/reviews/{id}/comments", 9999).with(user("bob")).with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"content\":\"댓글\"}"))
			.andExpect(status().isNotFound());
	}

}
