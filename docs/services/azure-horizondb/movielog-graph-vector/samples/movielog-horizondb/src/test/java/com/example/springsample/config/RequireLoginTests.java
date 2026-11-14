package com.example.springsample.config;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.redirectedUrl;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.springsample.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;

@TestPropertySource(properties = "app.security.require-login=true")
class RequireLoginTests extends IntegrationTest {

	@Test
	void anonymousPagesRedirectToLoginAndApisAnswer401() throws Exception {
		for (String page : new String[] { "/", "/reviews", "/movies", "/discover", "/graph/movies/27205" }) {
			mockMvc.perform(get(page)).andExpect(status().is3xxRedirection())
				.andExpect(redirectedUrl("/login"));
		}
		for (String api : new String[] { "/api/reviews", "/api/movies/search?q=dune", "/api/discover/search?q=x" }) {
			mockMvc.perform(get(api)).andExpect(status().isUnauthorized());
		}
	}

	@Test
	void loginSignupAndHealthStayOpen() throws Exception {
		mockMvc.perform(get("/login")).andExpect(status().isOk());
		mockMvc.perform(get("/signup")).andExpect(status().isOk());
		mockMvc.perform(get("/actuator/health/readiness")).andExpect(status().isOk());
	}

	@Test
	void signedInMembersSeeThePages() throws Exception {
		register("alice");
		mockMvc.perform(get("/reviews").with(user("alice"))).andExpect(status().isOk());
		mockMvc.perform(get("/api/reviews").with(user("alice"))).andExpect(status().isOk());
	}

}
