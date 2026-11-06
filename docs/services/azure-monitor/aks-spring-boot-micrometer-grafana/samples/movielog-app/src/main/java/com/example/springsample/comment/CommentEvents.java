package com.example.springsample.comment;

/** Business events of comments, delivered to listeners after the transaction commits. */
public final class CommentEvents {

	private CommentEvents() {
	}

	public record Created(long commentId, long reviewId) {
	}

	public record Deleted(long commentId, long reviewId) {
	}

}
