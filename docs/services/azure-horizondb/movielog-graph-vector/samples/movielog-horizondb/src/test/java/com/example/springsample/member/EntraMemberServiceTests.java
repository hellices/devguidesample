package com.example.springsample.member;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.security.core.authority.AuthorityUtils;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.crypto.password.NoOpPasswordEncoder;
import org.springframework.security.oauth2.client.oidc.userinfo.OidcUserRequest;
import org.springframework.security.oauth2.core.OAuth2AuthenticationException;
import org.springframework.security.oauth2.core.oidc.OidcIdToken;
import org.springframework.security.oauth2.core.oidc.user.DefaultOidcUser;
import org.springframework.security.oauth2.core.oidc.user.OidcUser;
import org.springframework.test.util.ReflectionTestUtils;

class EntraMemberServiceTests {

	private static final String TENANT = "11111111-2222-3333-4444-555555555555";

	private static final String OBJECT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

	private final MemberRepository members = mock(MemberRepository.class);

	private final ApplicationEventPublisher events = mock(ApplicationEventPublisher.class);

	private OidcUser signedIn = oidcUser(Map.of("tid", TENANT, "oid", OBJECT, "name", "김민지",
			"preferred_username", "minji.kim@contoso.example"));

	private final EntraMemberService service = new EntraMemberService(request -> signedIn, members,
			NoOpPasswordEncoder.getInstance(), events);

	@Test
	void firstSignInCreatesMemberKeyedByTenantAndObjectId() {
		given(members.findByExternalId("entra:" + TENANT + ":" + OBJECT)).willReturn(Optional.empty());
		given(members.saveAndFlush(any(Member.class))).willAnswer(invocation -> {
			Member saved = invocation.getArgument(0);
			ReflectionTestUtils.setField(saved, "id", 7L);
			return saved;
		});

		OidcUser principal = service.loadUser(mock(OidcUserRequest.class));

		assertThat(principal).isInstanceOf(UserDetails.class);
		assertThat(((UserDetails) principal).getUsername()).matches("minji_kim-[0-9a-f]{6}")
			.isEqualTo(principal.getName());
		assertThat(AuthorityUtils.authorityListToSet(principal.getAuthorities())).contains("ROLE_USER");
		verify(members).saveAndFlush(org.mockito.ArgumentMatchers.argThat(member ->
				member.getExternalId().equals("entra:" + TENANT + ":" + OBJECT) && member.getNickname().equals("김민지")));
		verify(events).publishEvent(new MemberRegistered(7L));
	}

	@Test
	void laterSignInReusesTheMemberEvenAfterTheDisplayNameChanges() {
		Member existing = new Member("minji_kim-abc123", "{noop}x", "김민지", "entra:" + TENANT + ":" + OBJECT);
		given(members.findByExternalId("entra:" + TENANT + ":" + OBJECT)).willReturn(Optional.of(existing));
		signedIn = oidcUser(Map.of("tid", TENANT, "oid", OBJECT, "name", "다른 이름", "preferred_username", "new@contoso.example"));

		OidcUser principal = service.loadUser(mock(OidcUserRequest.class));

		assertThat(principal.getName()).isEqualTo("minji_kim-abc123");
		verify(members, never()).saveAndFlush(any(Member.class));
	}

	@Test
	void usernameTakenByAnotherIdentityMovesToTheNextCandidate() {
		String externalId = "entra:" + TENANT + ":" + OBJECT;
		String first = EntraMemberService.username(externalId, "minji.kim@contoso.example", 0);
		String second = EntraMemberService.username(externalId, "minji.kim@contoso.example", 1);
		given(members.findByExternalId(externalId)).willReturn(Optional.empty());
		given(members.existsByUsername(first)).willReturn(true);
		given(members.saveAndFlush(any(Member.class))).willAnswer(invocation -> {
			Member saved = invocation.getArgument(0);
			ReflectionTestUtils.setField(saved, "id", 8L);
			return saved;
		});

		OidcUser principal = service.loadUser(mock(OidcUserRequest.class));

		assertThat(second).isNotEqualTo(first).matches("minji_kim-[0-9a-f]{6}");
		assertThat(principal.getName()).isEqualTo(second);
	}

	@Test
	void insertRaceOnTheUsernameRetriesWhileTheSameIdentityRaceReturnsTheWinner() {
		String externalId = "entra:" + TENANT + ":" + OBJECT;
		Member winner = new Member("minji_kim-000000", "{noop}x", "김민지", externalId);
		given(members.findByExternalId(externalId)).willReturn(Optional.empty(), Optional.empty(), Optional.of(winner));
		given(members.saveAndFlush(any(Member.class)))
			.willThrow(new org.springframework.dao.DataIntegrityViolationException("uk_username"));

		OidcUser principal = service.loadUser(mock(OidcUserRequest.class));

		assertThat(principal.getName()).isEqualTo("minji_kim-000000");
		verify(members, org.mockito.Mockito.times(2)).saveAndFlush(any(Member.class));
	}

	@Test
	void tokenWithoutObjectIdIsRejected() {
		signedIn = oidcUser(Map.of("tid", TENANT));

		assertThatThrownBy(() -> service.loadUser(mock(OidcUserRequest.class)))
			.isInstanceOf(OAuth2AuthenticationException.class);
	}

	@Test
	void usernamesStayWithinTheColumnAndNeverMatchSignUpUsernames() {
		String guest = EntraMemberService.username("entra:t:o", "very.long.name_naver.com#EXT#@contoso.onmicrosoft.com");

		assertThat(guest).matches("very_long_nam-[0-9a-f]{6}").hasSizeLessThanOrEqualTo(20);
		assertThat(EntraMemberService.username("entra:t:o", null)).matches("entra-[0-9a-f]{6}");
		assertThat(guest).doesNotMatch("^[a-zA-Z0-9_]{4,20}$");
	}

	@Test
	void nicknamesFitTheTwoToTwentyCharacterRule() {
		assertThat(EntraMemberService.nickname("가".repeat(25), null)).hasSize(20);
		assertThat(EntraMemberService.nickname(null, "kim@contoso.example")).isEqualTo("kim");
		assertThat(EntraMemberService.nickname("A", null)).isEqualTo("A님");
		assertThat(EntraMemberService.nickname(" ", null)).isEqualTo("Entra 사용자");
	}

	private static OidcUser oidcUser(Map<String, Object> claims) {
		OidcIdToken token = OidcIdToken.withTokenValue("id-token")
			.subject("pairwise-subject")
			.issuedAt(Instant.now())
			.expiresAt(Instant.now().plusSeconds(3600))
			.claims(all -> all.putAll(claims))
			.build();
		return new DefaultOidcUser(AuthorityUtils.createAuthorityList("OIDC_USER"), token);
	}

}
