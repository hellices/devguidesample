package com.example.springsample.config;

import static org.hamcrest.Matchers.everyItem;
import static org.hamcrest.Matchers.hasKey;
import static org.hamcrest.Matchers.startsWith;
import static org.hamcrest.Matchers.not;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(properties = "springdoc.api-docs.enabled=true")
@AutoConfigureMockMvc
@ActiveProfiles("test")
class OpenApiDocsTests {

	@Autowired
	private MockMvc mockMvc;

	@Test
	void documentsOnlyTheRestApi() throws Exception {
		mockMvc.perform(get("/v3/api-docs"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.paths", hasKey("/api/movies/search")))
			.andExpect(jsonPath("$.paths", hasKey("/api/movies/{tmdbId}")))
			.andExpect(jsonPath("$.paths", hasKey("/api/movies/{tmdbId}/reviews")))
			.andExpect(jsonPath("$.paths", hasKey("/api/reviews")))
			.andExpect(jsonPath("$.paths", hasKey("/api/reviews/{reviewId}/comments")))
			.andExpect(jsonPath("$.paths", not(hasKey("/reviews"))))
			.andExpect(jsonPath("$.paths.keys()", everyItem(startsWith("/api/"))))
			.andExpect(jsonPath("$.paths['/api/movies/{tmdbId}/reviews'].post").exists())
			.andExpect(jsonPath("$.paths['/api/movies/{tmdbId}/reviews'].post.parameters[?(@.name == 'user')]").isEmpty());
	}

}
