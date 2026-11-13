package com.example.springsample.discover;

import org.jspecify.annotations.Nullable;

/** Query text could not be embedded (endpoint not configured, token or API failure). */
class EmbeddingUnavailableException extends RuntimeException {

	EmbeddingUnavailableException(String message, @Nullable Throwable cause) {
		super(message, cause);
	}

}
