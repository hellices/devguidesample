package com.example.springsample.comment;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.stereotype.Controller;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

@Controller
@RequiredArgsConstructor
class CommentWebController {

	private final CommentService commentService;

	@PostMapping("/reviews/{reviewId}/comments")
	String create(@PathVariable Long reviewId, @Valid @ModelAttribute("commentForm") CommentForm form,
			BindingResult bindingResult, @AuthenticationPrincipal UserDetails user, RedirectAttributes redirect) {
		if (bindingResult.hasErrors()) {
			redirect.addFlashAttribute("commentForm", form);
			redirect.addFlashAttribute(BindingResult.MODEL_KEY_PREFIX + "commentForm", bindingResult);
			return "redirect:/reviews/" + reviewId + "#comments";
		}
		CommentResponse created = commentService.create(reviewId, user.getUsername(), form.getContent());
		return "redirect:/reviews/" + reviewId + "#comment-" + created.id();
	}

	@PostMapping("/reviews/{reviewId}/comments/{commentId}/delete")
	String delete(@PathVariable Long reviewId, @PathVariable Long commentId,
			@AuthenticationPrincipal UserDetails user) {
		Long ownerReviewId = commentService.delete(commentId, user.getUsername());
		return "redirect:/reviews/" + ownerReviewId + "#comments";
	}

}
