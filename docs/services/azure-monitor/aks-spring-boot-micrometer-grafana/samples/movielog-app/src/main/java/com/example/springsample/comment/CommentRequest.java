package com.example.springsample.comment;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record CommentRequest(@NotBlank @Size(max = Comment.CONTENT_MAX_LENGTH) String content) {
}
