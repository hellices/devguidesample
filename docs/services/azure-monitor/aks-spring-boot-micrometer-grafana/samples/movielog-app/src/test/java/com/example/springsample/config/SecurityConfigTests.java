package com.example.springsample.config;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.redirectedUrl;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.springsample.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

class SecurityConfigTests extends IntegrationTest {

	@Test
	void healthEndpointIsPublic() throws Exception {
		mockMvc.perform(get("/actuator/health"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status").value("UP"));
	}

	@Test
	void reviewsAndMoviesCanBeBrowsedAnonymously() throws Exception {
		mockMvc.perform(get("/reviews")).andExpect(status().isOk());
		mockMvc.perform(get("/movies")).andExpect(status().isOk());
		mockMvc.perform(get("/api/reviews")).andExpect(status().isOk());
	}

	@Test
	void writingPagesRedirectToLogin() throws Exception {
		mockMvc.perform(get("/movies/1/reviews/new"))
			.andExpect(status().is3xxRedirection())
			.andExpect(redirectedUrl("/login"));
	}

	@Test
	void protectedApiReturnsUnauthorizedInsteadOfRedirect() throws Exception {
		mockMvc.perform(post("/api/movies/1/reviews").with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"rating\":8,\"title\":\"t\",\"content\":\"c\"}"))
			.andExpect(status().isUnauthorized());
	}

	@Test
	void writesWithoutCsrfTokenAreRejected() throws Exception {
		mockMvc.perform(post("/signup").param("username", "nocsrf"))
			.andExpect(status().isForbidden());
	}

	@Test
	void swaggerIsDisabledOutsideDevProfile() throws Exception {
		mockMvc.perform(get("/v3/api-docs")).andExpect(status().isNotFound());
	}

}
