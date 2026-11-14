package com.example.springsample.member;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.Locale;
import java.util.Optional;

import org.jspecify.annotations.Nullable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.client.oidc.userinfo.OidcUserRequest;
import org.springframework.security.oauth2.client.oidc.userinfo.OidcUserService;
import org.springframework.security.oauth2.client.userinfo.OAuth2UserService;
import org.springframework.security.oauth2.core.OAuth2AuthenticationException;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.oidc.user.OidcUser;
import org.springframework.stereotype.Service;

/**
 * Binds a Microsoft Entra ID sign-in to a local member, creating the member on the first sign-in.
 * The member is keyed by the immutable {@code tid} and {@code oid} claims; {@code name} and
 * {@code preferred_username} only seed the nickname and username because they can change.
 */
@Service
public class EntraMemberService implements OAuth2UserService<OidcUserRequest, OidcUser> {

	static final int USERNAME_PREFIX_LENGTH = 13;

	private static final int NICKNAME_MAX = 20;

	private static final SecureRandom RANDOM = new SecureRandom();

	private final OAuth2UserService<OidcUserRequest, OidcUser> delegate;

	private final MemberRepository members;

	private final PasswordEncoder passwordEncoder;

	private final ApplicationEventPublisher events;

	@Autowired
	EntraMemberService(MemberRepository members, PasswordEncoder passwordEncoder, ApplicationEventPublisher events) {
		this(idTokenOnly(), members, passwordEncoder, events);
	}

	EntraMemberService(OAuth2UserService<OidcUserRequest, OidcUser> delegate, MemberRepository members,
			PasswordEncoder passwordEncoder, ApplicationEventPublisher events) {
		this.delegate = delegate;
		this.members = members;
		this.passwordEncoder = passwordEncoder;
		this.events = events;
	}

	/** The ID token carries every claim used here, so the Microsoft Graph user info call is skipped. */
	private static OidcUserService idTokenOnly() {
		OidcUserService service = new OidcUserService();
		service.setRetrieveUserInfo(request -> false);
		return service;
	}

	@Override
	public OidcUser loadUser(OidcUserRequest request) {
		OidcUser user = delegate.loadUser(request);
		String tenantId = user.getClaimAsString("tid");
		String objectId = user.getClaimAsString("oid");
		if (tenantId == null || objectId == null) {
			throw new OAuth2AuthenticationException(new OAuth2Error("invalid_id_token",
					"The ID token has no tid or oid claim; request the profile scope", null));
		}
		Member member = findOrCreate("entra:" + tenantId + ":" + objectId, user.getClaimAsString("name"),
				user.getPreferredUsername());
		return new MemberOidcUser(user, member.getUsername());
	}

	Member findOrCreate(String externalId, @Nullable String name, @Nullable String preferredUsername) {
		Optional<Member> existing = members.findByExternalId(externalId);
		if (existing.isPresent()) {
			return existing.get();
		}
		Member created;
		try {
			// A random password the member never learns: this account signs in only through Entra ID.
			byte[] secret = new byte[32];
			RANDOM.nextBytes(secret);
			created = members.saveAndFlush(new Member(username(externalId, preferredUsername),
					passwordEncoder.encode(HexFormat.of().formatHex(secret)), nickname(name, preferredUsername),
					externalId));
		}
		catch (DataIntegrityViolationException ex) {
			// A concurrent first sign-in of the same user created the member.
			return members.findByExternalId(externalId).orElseThrow(() -> ex);
		}
		events.publishEvent(new MemberRegistered(created.getId()));
		return created;
	}

	/**
	 * Readable and stable: the local part of the preferred username plus a hash of the external id. The hyphen
	 * cannot appear in form sign-up usernames ({@code [a-zA-Z0-9_]}), so the two kinds never collide.
	 */
	static String username(String externalId, @Nullable String preferredUsername) {
		String local = (preferredUsername == null) ? "" : preferredUsername.split("[@#]", 2)[0];
		local = local.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9_]", "_");
		if (local.isEmpty()) {
			local = "entra";
		}
		if (local.length() > USERNAME_PREFIX_LENGTH) {
			local = local.substring(0, USERNAME_PREFIX_LENGTH);
		}
		return local + "-" + sha256Hex(externalId).substring(0, 6);
	}

	static String nickname(@Nullable String name, @Nullable String preferredUsername) {
		String nickname = (name != null && !name.isBlank()) ? name.strip()
				: (preferredUsername != null && !preferredUsername.isBlank()) ? preferredUsername.split("@", 2)[0]
						: "Entra 사용자";
		if (nickname.codePointCount(0, nickname.length()) > NICKNAME_MAX) {
			nickname = nickname.substring(0, nickname.offsetByCodePoints(0, NICKNAME_MAX));
		}
		return (nickname.codePointCount(0, nickname.length()) < 2) ? nickname + "님" : nickname;
	}

	private static String sha256Hex(String value) {
		try {
			return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
				.digest(value.getBytes(StandardCharsets.UTF_8)));
		}
		catch (NoSuchAlgorithmException ex) {
			throw new IllegalStateException(ex);
		}
	}

}
