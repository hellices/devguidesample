package com.example.springsample.review;

import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

class ReviewTests {

	@Test
	void editRejectsInvalidTitleOrContentBeforeChangingState() {
		Review review = new Review();

		assertThatThrownBy(() -> review.edit(8, null, "내용")).isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> review.edit(8, " ", "내용")).isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> review.edit(8, "a".repeat(Review.TITLE_MAX_LENGTH + 1), "내용"))
			.isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> review.edit(8, "제목", null)).isInstanceOf(IllegalArgumentException.class);
		assertThatThrownBy(() -> review.edit(8, "제목", "a".repeat(Review.CONTENT_MAX_LENGTH + 1)))
			.isInstanceOf(IllegalArgumentException.class);
	}

}
