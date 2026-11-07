package com.example.springsample.member;

import lombok.RequiredArgsConstructor;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class MemberService {

	private final MemberRepository members;

	private final PasswordEncoder passwordEncoder;

	private final ApplicationEventPublisher events;

	@Transactional
	public Long register(String username, String rawPassword, String nickname) {
		if (members.existsByUsername(username)) {
			throw new DuplicateUsernameException(username);
		}
		Long id;
		try {
			id = members.saveAndFlush(new Member(username, passwordEncoder.encode(rawPassword), nickname)).getId();
		}
		catch (DataIntegrityViolationException ex) {
			throw new DuplicateUsernameException(username);
		}
		// Outside the try: a listener's own constraint failure must not be reported as a duplicate username.
		events.publishEvent(new MemberRegistered(id));
		return id;
	}

}
