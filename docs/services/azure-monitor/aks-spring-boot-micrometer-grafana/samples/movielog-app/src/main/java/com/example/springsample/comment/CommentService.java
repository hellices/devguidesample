package com.example.springsample.comment;

import java.util.List;

import com.example.springsample.common.NotOwnerException;
import com.example.springsample.common.ResourceNotFoundException;
import com.example.springsample.member.Member;
import com.example.springsample.member.MemberRepository;
import com.example.springsample.review.Review;
import com.example.springsample.review.ReviewRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class CommentService {

	private final CommentRepository comments;

	private final ReviewRepository reviews;

	private final MemberRepository members;

	private final ApplicationEventPublisher events;

	@Transactional(readOnly = true)
	public List<CommentResponse> list(Long reviewId) {
		if (!reviews.existsById(reviewId)) {
			throw new ResourceNotFoundException("Review", reviewId);
		}
		return comments.findResponsesByReviewId(reviewId);
	}

	@Transactional
	public CommentResponse create(Long reviewId, String username, String content) {
		Review review = reviews.findById(reviewId)
			.orElseThrow(() -> new ResourceNotFoundException("Review", reviewId));
		Member author = members.findByUsername(username)
			.orElseThrow(() -> new IllegalStateException("Authenticated member not found: " + username));
		Comment saved = comments.saveAndFlush(new Comment(review, author, content.strip()));
		reviews.adjustCommentCount(reviewId, 1);
		events.publishEvent(new CommentEvents.Created(saved.getId(), reviewId));
		return CommentResponse.from(saved);
	}

	/** Deletes the comment and returns the id of the review it belonged to. */
	@Transactional
	public Long delete(Long commentId, String username) {
		Comment comment = comments.findWithAuthorById(commentId)
			.orElseThrow(() -> new ResourceNotFoundException("Comment", commentId));
		if (!comment.isWrittenBy(username)) {
			throw new NotOwnerException();
		}
		Long reviewId = comment.getReview().getId();
		comments.delete(comment);
		reviews.adjustCommentCount(reviewId, -1);
		events.publishEvent(new CommentEvents.Deleted(commentId, reviewId));
		return reviewId;
	}

}
