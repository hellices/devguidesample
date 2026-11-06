package com.example.springsample.review;

import java.util.List;
import java.util.Locale;

import com.example.springsample.comment.CommentRepository;
import com.example.springsample.common.CursorResponse;
import com.example.springsample.common.NotOwnerException;
import com.example.springsample.common.ResourceNotFoundException;
import com.example.springsample.member.Member;
import com.example.springsample.member.MemberRepository;
import com.example.springsample.movie.Movie;
import com.example.springsample.movie.MovieService;
import org.jspecify.annotations.Nullable;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.Limit;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.StringUtils;

@Service
public class ReviewService {

	public static final int DEFAULT_SLICE_SIZE = 20;

	public static final int MAX_SLICE_SIZE = 50;

	private final ReviewRepository reviews;

	private final CommentRepository comments;

	private final MemberRepository members;

	private final MovieService movieService;

	private final TransactionTemplate transactionTemplate;

	private final ApplicationEventPublisher events;

	public ReviewService(ReviewRepository reviews, CommentRepository comments, MemberRepository members,
			MovieService movieService, TransactionTemplate transactionTemplate, ApplicationEventPublisher events) {
		this.reviews = reviews;
		this.comments = comments;
		this.members = members;
		this.movieService = movieService;
		this.transactionTemplate = transactionTemplate;
		this.events = events;
	}

	/** Newest first across all movies; {@code cursor} is the id of the last review already shown. */
	@Transactional(readOnly = true)
	public CursorResponse<ReviewSummary> feed(@Nullable Long cursor, int size, @Nullable String query) {
		int sliceSize = sliceSize(size);
		Limit limit = Limit.of(sliceSize + 1);
		long before = before(cursor);
		List<ReviewRow> rows = StringUtils.hasText(query)
				? reviews.searchSlice(before, likePattern(query), limit)
				: reviews.findSlice(before, limit);
		return CursorResponse.of(rows.stream().map(this::toSummary).toList(), sliceSize, ReviewSummary::id);
	}

	@Transactional(readOnly = true)
	public CursorResponse<ReviewSummary> forMovie(long tmdbId, @Nullable Long cursor, int size) {
		int sliceSize = sliceSize(size);
		List<ReviewRow> rows = reviews.findSliceByMovie(tmdbId, before(cursor), Limit.of(sliceSize + 1));
		return CursorResponse.of(rows.stream().map(this::toSummary).toList(), sliceSize, ReviewSummary::id);
	}

	@Transactional(readOnly = true)
	public @Nullable Long findOwnReviewId(long tmdbId, String username) {
		return reviews.findIdByMovieAndAuthor(tmdbId, username).orElse(null);
	}

	/** Returns the review and counts the read. */
	@Transactional
	public ReviewDetail view(Long id) {
		if (reviews.incrementViewCount(id) == 0) {
			throw new ResourceNotFoundException("Review", id);
		}
		events.publishEvent(new ReviewEvents.Viewed(id));
		return toDetail(load(id));
	}

	@Transactional(readOnly = true)
	public ReviewDetail getForEdit(Long id, String username) {
		return toDetail(loadOwned(id, username));
	}

	/**
	 * Imports the movie if this is its first review (an external call, so outside the transaction),
	 * then stores the review.
	 */
	public ReviewDetail create(long tmdbId, String username, int rating, String title, String content) {
		Movie movie = movieService.sync(tmdbId);
		try {
			return transactionTemplate.execute(status -> {
				Long existing = reviews.findIdByMovieAndAuthor(tmdbId, username).orElse(null);
				if (existing != null) {
					throw new DuplicateReviewException(existing);
				}
				Member author = members.findByUsername(username)
					.orElseThrow(() -> new IllegalStateException("Authenticated member not found: " + username));
				Review saved = reviews.saveAndFlush(new Review(movie, author, rating, title.strip(), content));
				events.publishEvent(new ReviewEvents.Created(saved.getId(), tmdbId, rating));
				return toDetail(saved);
			});
		}
		catch (DataIntegrityViolationException ex) {
			// Lost a race with a concurrent submission of the same review.
			throw reviews.findIdByMovieAndAuthor(tmdbId, username)
				.<RuntimeException>map(DuplicateReviewException::new)
				.orElse(ex);
		}
	}

	@Transactional
	public ReviewDetail update(Long id, String username, int rating, String title, String content) {
		Review review = loadOwned(id, username);
		review.edit(rating, title.strip(), content);
		reviews.flush();
		return toDetail(review);
	}

	/** Deletes the review with its comments and returns the movie's TMDB id. */
	@Transactional
	public Long delete(Long id, String username) {
		Review review = loadOwned(id, username);
		Long tmdbId = review.getMovie().getTmdbId();
		comments.deleteByReviewId(id);
		reviews.deleteById(id);
		events.publishEvent(new ReviewEvents.Deleted(id));
		return tmdbId;
	}

	private Review loadOwned(Long id, String username) {
		Review review = load(id);
		if (!review.isWrittenBy(username)) {
			throw new NotOwnerException();
		}
		return review;
	}

	private Review load(Long id) {
		return reviews.findWithAuthorAndMovieById(id).orElseThrow(() -> new ResourceNotFoundException("Review", id));
	}

	private ReviewSummary toSummary(ReviewRow row) {
		return new ReviewSummary(row.id(), row.title(), row.excerpt(), row.rating(), row.authorNickname(),
				movieService.toRef(row.tmdbId(), row.movieTitle(),
						(row.releaseDate() == null) ? null : row.releaseDate().getYear(), row.posterPath()),
				row.viewCount(), row.commentCount(), row.createdAt());
	}

	private ReviewDetail toDetail(Review review) {
		Movie movie = review.getMovie();
		return new ReviewDetail(review.getId(), review.getTitle(), review.getContent(), review.getRating(),
				review.getAuthor().getUsername(), review.getAuthor().getNickname(),
				movieService.toRef(movie.getTmdbId(), movie.getTitle(), movie.getReleaseYear(), movie.getPosterPath()),
				review.getViewCount(), review.getCommentCount(), review.getCreatedAt(), review.getUpdatedAt());
	}

	private static int sliceSize(int size) {
		return Math.clamp(size, 1, MAX_SLICE_SIZE);
	}

	private static long before(@Nullable Long cursor) {
		return (cursor == null) ? Long.MAX_VALUE : cursor;
	}

	private static String likePattern(String query) {
		String escaped = query.strip()
			.toLowerCase(Locale.ROOT)
			.replace("\\", "\\\\")
			.replace("%", "\\%")
			.replace("_", "\\_");
		return "%" + escaped + "%";
	}

}
