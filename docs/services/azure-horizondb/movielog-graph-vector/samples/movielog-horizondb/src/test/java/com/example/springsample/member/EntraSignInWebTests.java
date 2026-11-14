package com.example.springsample.member;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.authentication;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;

import com.example.springsample.IntegrationTest;
import org.hamcrest.Matchers;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.security.core.authority.AuthorityUtils;
import org.springframework.security.oauth2.client.authentication.OAuth2AuthenticationToken;
import org.springframework.security.oauth2.core.oidc.OidcIdToken;
import org.springframework.security.oauth2.core.oidc.user.DefaultOidcUser;

class EntraSignInWebTests extends IntegrationTest {

	@Autowired
	private EntraMemberService entraMembers;

	@Test
	void entraPrincipalWorksWhereControllersExpectUserDetails() throws Exception {
		stubMovie(496243, "기생충", "tt6751668", null);
		Member member = entraMembers.findOrCreate("entra:tenant:object", "김민지", "minji@contoso.example");
		var principal = new MemberOidcUser(new DefaultOidcUser(AuthorityUtils.createAuthorityList("OIDC_USER"),
				OidcIdToken.withTokenValue("t").subject("s").issuedAt(Instant.now())
					.expiresAt(Instant.now().plusSeconds(60)).build()), member.getUsername());
		var signedIn = new OAuth2AuthenticationToken(principal, principal.getAuthorities(), "entra");

		mockMvc.perform(post("/api/movies/{id}/reviews", 496243).with(authentication(signedIn)).with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"rating\":8,\"title\":\"좋아요\",\"content\":\"Entra 계정으로 쓴 리뷰\"}"))
			.andExpect(status().isCreated())
			.andExpect(jsonPath("$.authorNickname").value("김민지"));
	}

	@Test
	void loginPageHidesTheEntraButtonWithoutAClientRegistration() throws Exception {
		mockMvc.perform(get("/login"))
			.andExpect(status().isOk())
			.andExpect(content().string(Matchers.not(Matchers.containsString("/oauth2/authorization/entra"))));
	}

}
