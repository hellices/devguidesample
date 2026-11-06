package com.example.springsample.review;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record ReviewRequest(
		@Schema(description = "별점(0.5개 단위): 1 = ★0.5 ... 10 = ★5", example = "8")
		@NotNull @Min(Review.MIN_RATING) @Max(Review.MAX_RATING) Integer rating,
		@NotBlank @Size(max = Review.TITLE_MAX_LENGTH) String title,
		@NotBlank @Size(max = Review.CONTENT_MAX_LENGTH) String content) {
}
