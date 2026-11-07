package com.example.springsample.review;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class ReviewForm {

	/** Half-star units: 1 = ★0.5 … 10 = ★5, so {@code @Max(MAX_RATING)} is 10 while the message says 5 stars. */
	@NotNull(message = "별점을 선택하세요.")
	@Min(value = Review.MIN_RATING, message = "별점을 선택하세요.")
	@Max(value = Review.MAX_RATING, message = "별점은 최대 5개입니다.")
	private Integer rating;

	@NotBlank(message = "제목을 입력하세요.")
	@Size(max = Review.TITLE_MAX_LENGTH, message = "제목은 {max}자 이하로 입력하세요.")
	private String title;

	@NotBlank(message = "내용을 입력하세요.")
	@Size(max = Review.CONTENT_MAX_LENGTH, message = "내용은 {max}자 이하로 입력하세요.")
	private String content;

	/** The empty form preselects ★4 (8 half stars); a submitted form keeps rating null unless the request sends one. */
	static ReviewForm newReview() {
		ReviewForm form = new ReviewForm();
		form.rating = 8;
		return form;
	}

	ReviewForm(ReviewDetail review) {
		this.rating = review.rating();
		this.title = review.title();
		this.content = review.content();
	}

}
