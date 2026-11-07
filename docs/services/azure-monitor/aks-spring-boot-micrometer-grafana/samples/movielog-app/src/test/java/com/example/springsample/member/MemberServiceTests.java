package com.example.springsample.member;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.BDDMockito.willThrow;
import static org.mockito.Mockito.mock;

import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.NoOpPasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

class MemberServiceTests {

	private final MemberRepository members = mock(MemberRepository.class);

	private final ApplicationEventPublisher events = mock(ApplicationEventPublisher.class);

	private final MemberService service = new MemberService(members, NoOpPasswordEncoder.getInstance(), events);

	@Test
	void uniqueConstraintOnSaveIsReportedAsDuplicateUsername() {
		given(members.saveAndFlush(any(Member.class))).willThrow(new DataIntegrityViolationException("uk_username"));

		assertThatThrownBy(() -> service.register("alice", "password", "앨리스"))
			.isInstanceOf(DuplicateUsernameException.class);
	}

	@Test
	void listenerConstraintFailureIsNotReportedAsDuplicateUsername() {
		given(members.saveAndFlush(any(Member.class))).willAnswer(invocation -> {
			Member saved = invocation.getArgument(0);
			ReflectionTestUtils.setField(saved, "id", 1L);
			return saved;
		});
		DataIntegrityViolationException listenerFailure = new DataIntegrityViolationException("listener");
		willThrow(listenerFailure).given(events).publishEvent(any(MemberRegistered.class));

		assertThatThrownBy(() -> service.register("alice", "password", "앨리스")).isSameAs(listenerFailure);
	}

}
