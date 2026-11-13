package com.example.springsample.discover;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;

/** The catalog, its embeddings or the AGE graph cannot be queried (not loaded yet or the database failed). */
@ResponseStatus(HttpStatus.SERVICE_UNAVAILABLE)
public class DiscoverUnavailableException extends RuntimeException {

	public DiscoverUnavailableException(String message, Throwable cause) {
		super(message, cause);
	}

}
