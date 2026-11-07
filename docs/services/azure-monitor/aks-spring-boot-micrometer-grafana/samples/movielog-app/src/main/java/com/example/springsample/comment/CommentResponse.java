package com.example.springsample.comment;

import java.time.Instant;

public record CommentResponse(Long id, String content, String authorUsername, String authorNickname,
		Instant createdAt) {

	static CommentResponse from(Comment comment) {
		return new CommentResponse(comment.getId(), comment.getContent(), comment.getAuthor().getUsername(),
				comment.getAuthor().getNickname(), comment.getCreatedAt());
	}

}
