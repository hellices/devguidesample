package com.example.springsample.common;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;

@ResponseStatus(HttpStatus.FORBIDDEN)
public class NotOwnerException extends RuntimeException {

	public NotOwnerException() {
		super("Only the author can modify this resource");
	}

}
