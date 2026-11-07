package com.example.springsample.member;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PostMapping;

@Controller
@RequiredArgsConstructor
class AuthController {

	private final MemberService memberService;

	@GetMapping("/login")
	String loginPage() {
		return "auth/login";
	}

	@GetMapping("/signup")
	String signupPage(@ModelAttribute("form") SignupForm form) {
		return "auth/signup";
	}

	@PostMapping("/signup")
	String signup(@Valid @ModelAttribute("form") SignupForm form, BindingResult bindingResult) {
		if (!bindingResult.hasFieldErrors("passwordConfirm") && !form.getPasswordConfirm().equals(form.getPassword())) {
			bindingResult.rejectValue("passwordConfirm", "mismatch", "비밀번호가 일치하지 않습니다.");
		}
		if (bindingResult.hasErrors()) {
			return "auth/signup";
		}
		try {
			memberService.register(form.getUsername(), form.getPassword(), form.getNickname());
		}
		catch (DuplicateUsernameException ex) {
			bindingResult.rejectValue("username", "duplicate", "이미 사용 중인 아이디입니다.");
			return "auth/signup";
		}
		return "redirect:/login?registered";
	}

}
