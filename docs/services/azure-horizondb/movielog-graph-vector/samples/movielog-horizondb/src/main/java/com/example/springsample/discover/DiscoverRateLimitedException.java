package com.example.springsample.discover;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;

/** A semantic search was refused before calling Azure OpenAI because a rate cap was reached. */
@ResponseStatus(HttpStatus.TOO_MANY_REQUESTS)
public class DiscoverRateLimitedException extends RuntimeException {

	public DiscoverRateLimitedException(String message) {
		super(message);
	}

}
