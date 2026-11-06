package com.example.springsample.comment;

import java.net.URI;
import java.util.List;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Comments", description = "리뷰 댓글")
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
class CommentApiController {

	private final CommentService commentService;

	@Operation(summary = "리뷰의 댓글 목록", description = "작성순으로 반환합니다.")
	@GetMapping("/reviews/{reviewId}/comments")
	List<CommentResponse> list(@PathVariable Long reviewId) {
		return commentService.list(reviewId);
	}

	@Operation(summary = "댓글 작성", description = "로그인이 필요합니다.")
	@PostMapping("/reviews/{reviewId}/comments")
	ResponseEntity<CommentResponse> create(@PathVariable Long reviewId, @Valid @RequestBody CommentRequest request,
			@AuthenticationPrincipal UserDetails user) {
		CommentResponse created = commentService.create(reviewId, user.getUsername(), request.content());
		return ResponseEntity.created(URI.create("/api/comments/" + created.id())).body(created);
	}

	@Operation(summary = "댓글 삭제", description = "작성자만 삭제할 수 있습니다.")
	@DeleteMapping("/comments/{id}")
	ResponseEntity<Void> delete(@PathVariable Long id, @AuthenticationPrincipal UserDetails user) {
		commentService.delete(id, user.getUsername());
		return ResponseEntity.noContent().build();
	}

}
