package com.example.springsample.review;

import lombok.Getter;

/** A member tried to review the same movie twice. */
@Getter
public class DuplicateReviewException extends RuntimeException {

	private final Long existingReviewId;

	public DuplicateReviewException(Long existingReviewId) {
		super("You already reviewed this movie (review " + existingReviewId + ")");
		this.existingReviewId = existingReviewId;
	}

}
