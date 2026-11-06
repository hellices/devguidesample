package com.example.springsample.member;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class SignupForm {

	@NotBlank(message = "아이디를 입력하세요.")
	@Pattern(regexp = "^[a-zA-Z0-9_]{4,20}$", message = "아이디는 영문, 숫자, 밑줄(_) 4~20자입니다.")
	private String username;

	@NotBlank(message = "비밀번호를 입력하세요.")
	@Size(min = 8, max = 64, message = "비밀번호는 8~64자입니다.")
	private String password;

	@NotBlank(message = "비밀번호 확인을 입력하세요.")
	private String passwordConfirm;

	@NotBlank(message = "닉네임을 입력하세요.")
	@Size(min = 2, max = 20, message = "닉네임은 2~20자입니다.")
	private String nickname;

}
