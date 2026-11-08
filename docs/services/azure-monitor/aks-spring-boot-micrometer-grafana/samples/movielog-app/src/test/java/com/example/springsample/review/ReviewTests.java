package com.example.springsample.review;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.function.Consumer;

import org.junit.jupiter.api.Test;

class ReviewTests {

	@Test
	void editRejectsInvalidTitleOrContentBeforeChangingState() {
		assertRejectedWithoutChange(review -> review.edit(3, null, "새 내용"));
		assertRejectedWithoutChange(review -> review.edit(3, " ", "새 내용"));
		assertRejectedWithoutChange(review -> review.edit(3, "a".repeat(Review.TITLE_MAX_LENGTH + 1), "새 내용"));
		assertRejectedWithoutChange(review -> review.edit(3, "새 제목", null));
		assertRejectedWithoutChange(review -> review.edit(3, "새 제목", "a".repeat(Review.CONTENT_MAX_LENGTH + 1)));
		assertRejectedWithoutChange(review -> review.edit(11, "새 제목", "새 내용"));
	}

	private static void assertRejectedWithoutChange(Consumer<Review> invalidEdit) {
		Review review = new Review();
		review.edit(8, "원래 제목", "원래 내용");

		assertThatThrownBy(() -> invalidEdit.accept(review)).isInstanceOf(IllegalArgumentException.class);

		assertThat(review.getRating()).isEqualTo(8);
		assertThat(review.getTitle()).isEqualTo("원래 제목");
		assertThat(review.getContent()).isEqualTo("원래 내용");
	}

}
