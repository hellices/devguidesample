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
		try {
			Long id = members.saveAndFlush(new Member(username, passwordEncoder.encode(rawPassword), nickname)).getId();
			events.publishEvent(new MemberRegistered(id));
			return id;
		}
		catch (DataIntegrityViolationException ex) {
			throw new DuplicateUsernameException(username);
		}
	}

}
