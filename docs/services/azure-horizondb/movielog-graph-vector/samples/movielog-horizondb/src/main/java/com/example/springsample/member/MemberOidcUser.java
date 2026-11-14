package com.example.springsample.member;

import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Set;

import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.oauth2.core.oidc.IdTokenClaimNames;
import org.springframework.security.oauth2.core.oidc.user.DefaultOidcUser;
import org.springframework.security.oauth2.core.oidc.user.OidcUser;

/**
 * A Microsoft Entra ID sign-in bound to a local member. It is also a {@link UserDetails} named after the member's
 * username, so controllers that take {@code @AuthenticationPrincipal UserDetails} work for both login methods.
 */
public final class MemberOidcUser extends DefaultOidcUser implements UserDetails {

	private final String username;

	MemberOidcUser(OidcUser user, String username) {
		super(withUserRole(user.getAuthorities()), user.getIdToken(), user.getUserInfo(), IdTokenClaimNames.SUB);
		this.username = username;
	}

	private static Set<GrantedAuthority> withUserRole(Collection<? extends GrantedAuthority> authorities) {
		Set<GrantedAuthority> all = new LinkedHashSet<>(authorities);
		all.add(new SimpleGrantedAuthority("ROLE_USER"));
		return all;
	}

	@Override
	public String getName() {
		return username;
	}

	@Override
	public String getUsername() {
		return username;
	}

	/** Members from Entra ID have no usable local password. */
	@Override
	public String getPassword() {
		return "";
	}

	@Override
	public boolean equals(Object other) {
		return other instanceof MemberOidcUser that && super.equals(that) && username.equals(that.username);
	}

	@Override
	public int hashCode() {
		return 31 * super.hashCode() + username.hashCode();
	}

}
