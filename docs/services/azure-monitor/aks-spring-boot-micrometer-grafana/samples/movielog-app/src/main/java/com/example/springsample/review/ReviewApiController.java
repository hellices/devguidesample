package com.example.springsample.review;

import java.net.URI;

import com.example.springsample.common.CursorResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.RequiredArgsConstructor;
import org.jspecify.annotations.Nullable;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Reviews", description = "영화 리뷰")
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
class ReviewApiController {

	private final ReviewService reviewService;

	@Operation(summary = "최신 리뷰 피드 (무한 스크롤)",
			description = "모든 영화의 리뷰를 최신순으로 반환합니다. 다음 묶음은 응답의 nextCursor를 cursor로 넘겨 요청합니다.")
	@GetMapping("/reviews")
	CursorResponse<ReviewSummary> feed(
			@Parameter(description = "이전 응답의 nextCursor. 비우면 처음부터")
			@RequestParam(required = false) @Nullable Long cursor,
			@Parameter(description = "한 번에 가져올 개수")
			@RequestParam(defaultValue = "" + ReviewService.DEFAULT_SLICE_SIZE) @Min(1) @Max(ReviewService.MAX_SLICE_SIZE) int size,
			@Parameter(description = "리뷰 제목/내용, 영화 제목 검색어")
			@RequestParam(required = false) @Nullable String q) {
		return reviewService.feed(cursor, size, q);
	}

	@Operation(summary = "영화별 리뷰 (무한 스크롤)")
	@GetMapping("/movies/{tmdbId}/reviews")
	CursorResponse<ReviewSummary> forMovie(@Parameter(description = "TMDB 영화 id") @PathVariable long tmdbId,
			@RequestParam(required = false) @Nullable Long cursor,
			@RequestParam(defaultValue = "" + ReviewService.DEFAULT_SLICE_SIZE) @Min(1) @Max(ReviewService.MAX_SLICE_SIZE) int size) {
		return reviewService.forMovie(tmdbId, cursor, size);
	}

	@Operation(summary = "리뷰 작성",
			description = "로그인이 필요합니다. 영화당 한 번만 작성할 수 있으며, 이미 썼다면 409와 함께 기존 리뷰 id(reviewId)를 반환합니다.")
	@PostMapping("/movies/{tmdbId}/reviews")
	ResponseEntity<ReviewDetail> create(@PathVariable long tmdbId, @Valid @RequestBody ReviewRequest request,
			@AuthenticationPrincipal UserDetails user) {
		ReviewDetail created = reviewService.create(tmdbId, user.getUsername(), request.rating(), request.title(),
				request.content());
		return ResponseEntity.created(URI.create("/api/reviews/" + created.id())).body(created);
	}

	@Operation(summary = "리뷰 조회", description = "조회수가 1 증가합니다.")
	@GetMapping("/reviews/{id}")
	ReviewDetail get(@PathVariable Long id) {
		return reviewService.view(id);
	}

	@Operation(summary = "리뷰 수정", description = "작성자만 수정할 수 있습니다.")
	@PutMapping("/reviews/{id}")
	ReviewDetail update(@PathVariable Long id, @Valid @RequestBody ReviewRequest request,
			@AuthenticationPrincipal UserDetails user) {
		return reviewService.update(id, user.getUsername(), request.rating(), request.title(), request.content());
	}

	@Operation(summary = "리뷰 삭제", description = "작성자만 삭제할 수 있습니다. 댓글도 함께 삭제됩니다.")
	@DeleteMapping("/reviews/{id}")
	ResponseEntity<Void> delete(@PathVariable Long id, @AuthenticationPrincipal UserDetails user) {
		reviewService.delete(id, user.getUsername());
		return ResponseEntity.noContent().build();
	}

}
