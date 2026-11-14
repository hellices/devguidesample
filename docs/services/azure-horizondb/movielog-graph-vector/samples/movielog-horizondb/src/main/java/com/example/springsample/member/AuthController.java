package com.example.springsample.member;

import java.nio.charset.StandardCharsets;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.security.oauth2.client.registration.ClientRegistrationRepository;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PostMapping;

@Controller
@RequiredArgsConstructor
class AuthController {

	/** BCrypt hashes at most 72 bytes and Spring Security rejects longer input instead of truncating it. */
	private static final int BCRYPT_MAX_PASSWORD_BYTES = 72;

	private final MemberService memberService;

	/** Present only when the entra profile registers the Microsoft Entra ID client. */
	private final ObjectProvider<ClientRegistrationRepository> clientRegistrations;

	@GetMapping("/login")
	String loginPage(Model model) {
		model.addAttribute("entraLogin", clientRegistrations.getIfAvailable() != null);
		return "auth/login";
	}

	@GetMapping("/signup")
	String signupPage(@ModelAttribute("form") SignupForm form) {
		return "auth/signup";
	}

	@PostMapping("/signup")
	String signup(@Valid @ModelAttribute("form") SignupForm form, BindingResult bindingResult) {
		if (!bindingResult.hasFieldErrors("password")
				&& form.getPassword().getBytes(StandardCharsets.UTF_8).length > BCRYPT_MAX_PASSWORD_BYTES) {
			bindingResult.rejectValue("password", "tooManyBytes",
					"비밀번호가 너무 깁니다. 영문·숫자는 64자, 한글은 24자까지 쓸 수 있습니다.");
		}
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
