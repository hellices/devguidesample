package com.example.springsample.review;

import com.example.springsample.comment.CommentForm;
import com.example.springsample.comment.CommentService;
import com.example.springsample.movie.MovieService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.jspecify.annotations.Nullable;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

@Controller
@RequiredArgsConstructor
class ReviewWebController {

	private final ReviewService reviewService;

	private final CommentService commentService;

	private final MovieService movieService;

	@GetMapping("/")
	String home() {
		return "redirect:/reviews";
	}

	@GetMapping("/reviews")
	String feed(@RequestParam(required = false) @Nullable String q, Model model) {
		model.addAttribute("q", (q == null) ? "" : q.strip());
		model.addAttribute("slice", reviewService.feed(null, ReviewService.DEFAULT_SLICE_SIZE, q));
		model.addAttribute("pageSize", ReviewService.DEFAULT_SLICE_SIZE);
		return "reviews/list";
	}

	@GetMapping("/reviews/{id}")
	String detail(@PathVariable Long id, @AuthenticationPrincipal @Nullable UserDetails user, Model model) {
		model.addAttribute("review", reviewService.view(id));
		model.addAttribute("comments", commentService.list(id));
		model.addAttribute("currentUsername", (user == null) ? null : user.getUsername());
		if (!model.containsAttribute("commentForm")) {
			model.addAttribute("commentForm", new CommentForm());
		}
		return "reviews/detail";
	}

	@GetMapping("/movies/{tmdbId}/reviews/new")
	String createForm(@PathVariable long tmdbId, @AuthenticationPrincipal UserDetails user, Model model,
			RedirectAttributes redirect) {
		Long existing = reviewService.findOwnReviewId(tmdbId, user.getUsername());
		if (existing != null) {
			redirect.addFlashAttribute("notice", "이미 이 영화에 리뷰를 남겼습니다. 기존 리뷰를 수정할 수 있습니다.");
			return "redirect:/reviews/" + existing + "/edit";
		}
		model.addAttribute("movie", movieService.getMovie(tmdbId));
		model.addAttribute("form", new ReviewForm());
		return "reviews/form";
	}

	@PostMapping("/movies/{tmdbId}/reviews")
	String create(@PathVariable long tmdbId, @Valid @ModelAttribute("form") ReviewForm form,
			BindingResult bindingResult, @AuthenticationPrincipal UserDetails user, Model model,
			RedirectAttributes redirect) {
		if (bindingResult.hasErrors()) {
			model.addAttribute("movie", movieService.getMovie(tmdbId));
			return "reviews/form";
		}
		try {
			ReviewDetail created = reviewService.create(tmdbId, user.getUsername(), form.getRating(),
					form.getTitle(), form.getContent());
			return "redirect:/reviews/" + created.id();
		}
		catch (DuplicateReviewException ex) {
			redirect.addFlashAttribute("notice", "이미 이 영화에 리뷰를 남겼습니다. 기존 리뷰를 수정할 수 있습니다.");
			return "redirect:/reviews/" + ex.getExistingReviewId() + "/edit";
		}
	}

	@GetMapping("/reviews/{id}/edit")
	String editForm(@PathVariable Long id, @AuthenticationPrincipal UserDetails user, Model model) {
		ReviewDetail review = reviewService.getForEdit(id, user.getUsername());
		model.addAttribute("reviewId", id);
		model.addAttribute("movie", movieService.getMovie(review.movie().tmdbId()));
		model.addAttribute("form", new ReviewForm(review));
		return "reviews/form";
	}

	@PostMapping("/reviews/{id}/edit")
	String edit(@PathVariable Long id, @Valid @ModelAttribute("form") ReviewForm form, BindingResult bindingResult,
			@AuthenticationPrincipal UserDetails user, Model model) {
		if (bindingResult.hasErrors()) {
			ReviewDetail review = reviewService.getForEdit(id, user.getUsername());
			model.addAttribute("reviewId", id);
			model.addAttribute("movie", movieService.getMovie(review.movie().tmdbId()));
			return "reviews/form";
		}
		reviewService.update(id, user.getUsername(), form.getRating(), form.getTitle(), form.getContent());
		return "redirect:/reviews/" + id;
	}

	@PostMapping("/reviews/{id}/delete")
	String delete(@PathVariable Long id, @AuthenticationPrincipal UserDetails user) {
		Long tmdbId = reviewService.delete(id, user.getUsername());
		return "redirect:/movies/" + tmdbId;
	}

}
