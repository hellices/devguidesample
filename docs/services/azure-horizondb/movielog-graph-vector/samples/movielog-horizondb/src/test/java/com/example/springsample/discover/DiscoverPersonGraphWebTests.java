package com.example.springsample.discover;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;

import com.example.springsample.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

class DiscoverPersonGraphWebTests extends IntegrationTest {

	@MockitoBean
	private DiscoverService discoverService;

	@Test
	void returnsThePersonGraphWithPosters() throws Exception {
		given(discoverService.personGraph("Q548823")).willReturn(new GraphView(
				List.of(new GraphView.Node("p1", "Person", "드니 빌뇌브", null, null, false, "Q548823", null),
						new GraphView.Node("m1", "Movie", "컨택트", 329865L, 2016, false, null, "https://img.test/w92/a.jpg")),
				List.of(new GraphView.Edge("e1", "p1", "m1", "DIRECTED", null))));

		mockMvc.perform(get("/api/discover/graph/people/Q548823").with(user("alice")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.nodes[0].qid").value("Q548823"))
			.andExpect(jsonPath("$.nodes[1].posterUrl").value("https://img.test/w92/a.jpg"));
	}

	@Test
	void rejectsIdsThatAreNotPersonKeys() throws Exception {
		for (String qid : new String[] { "Q0", "x' OR 1=1", "tmdb:abc", "Q1}) RETURN" }) {
			mockMvc.perform(get("/api/discover/graph/people/{qid}", qid).with(user("alice")))
				.andExpect(status().is4xxClientError());
		}
		verify(discoverService, never()).personGraph(anyString());
	}

}
