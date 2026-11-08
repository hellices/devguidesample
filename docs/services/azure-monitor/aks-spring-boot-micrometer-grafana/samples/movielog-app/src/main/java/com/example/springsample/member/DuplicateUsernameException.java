package com.example.springsample.member;

public class DuplicateUsernameException extends RuntimeException {

	public DuplicateUsernameException(String username) {
		super("Username already exists: " + username);
	}

}
