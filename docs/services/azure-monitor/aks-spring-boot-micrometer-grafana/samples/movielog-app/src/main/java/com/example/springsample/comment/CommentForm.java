package com.example.springsample.comment;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class CommentForm {

	@NotBlank(message = "댓글 내용을 입력하세요.")
	@Size(max = Comment.CONTENT_MAX_LENGTH, message = "댓글은 {max}자 이하로 입력하세요.")
	private String content;

}
