package com.example.springsample.movie;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;

/** The external movie API is not configured or did not answer. */
@ResponseStatus(HttpStatus.SERVICE_UNAVAILABLE)
public class MovieApiUnavailableException extends RuntimeException {

	public MovieApiUnavailableException(String message) {
		super(message);
	}

	public MovieApiUnavailableException(String message, Throwable cause) {
		super(message, cause);
	}

}
