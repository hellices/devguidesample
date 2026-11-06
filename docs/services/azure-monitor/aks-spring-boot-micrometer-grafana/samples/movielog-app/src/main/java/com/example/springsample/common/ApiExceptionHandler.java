package com.example.springsample.common;

import com.example.springsample.movie.MovieApiUnavailableException;
import com.example.springsample.review.DuplicateReviewException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

/**
 * Turns REST API errors into RFC 9457 problem details. Thymeleaf controllers are not covered:
 * their errors render the templates under {@code templates/error}.
 */
@RestControllerAdvice(annotations = RestController.class)
@Order(Ordered.HIGHEST_PRECEDENCE)
class ApiExceptionHandler extends ResponseEntityExceptionHandler {

	private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);

	@ExceptionHandler(ResourceNotFoundException.class)
	ProblemDetail notFound(ResourceNotFoundException ex) {
		var problem = ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND, ex.getMessage());
		problem.setTitle("Resource not found");
		problem.setProperty("code", "RESOURCE_NOT_FOUND");
		return problem;
	}

	@ExceptionHandler(NotOwnerException.class)
	ProblemDetail notOwner(NotOwnerException ex) {
		var problem = ProblemDetail.forStatusAndDetail(HttpStatus.FORBIDDEN, ex.getMessage());
		problem.setTitle("Forbidden");
		problem.setProperty("code", "NOT_OWNER");
		return problem;
	}

	@ExceptionHandler(DuplicateReviewException.class)
	ProblemDetail duplicateReview(DuplicateReviewException ex) {
		var problem = ProblemDetail.forStatusAndDetail(HttpStatus.CONFLICT, ex.getMessage());
		problem.setTitle("Review already exists");
		problem.setProperty("code", "DUPLICATE_REVIEW");
		problem.setProperty("reviewId", ex.getExistingReviewId());
		return problem;
	}

	@ExceptionHandler(MovieApiUnavailableException.class)
	ProblemDetail movieApiUnavailable(MovieApiUnavailableException ex) {
		log.warn("Movie API unavailable: {}", ex.getMessage());
		var problem = ProblemDetail.forStatusAndDetail(HttpStatus.SERVICE_UNAVAILABLE,
				"The movie database is not available right now");
		problem.setTitle("Movie API unavailable");
		problem.setProperty("code", "MOVIE_API_UNAVAILABLE");
		return problem;
	}

}
