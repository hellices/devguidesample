package com.example.springsample.discover;

import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;

import com.example.springsample.IntegrationTest;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

class DiscoverCorrectionWebTests extends IntegrationTest {

	@MockitoBean
	private DiscoverService discoverService;

	@Test
	void searchPageNamesTheCorrectedWords() throws Exception {
		MovieHit dune = new MovieHit(693134, "듄: 파트 2", "Dune: Part Two", 2024, List.of("SF"), "줄거리", null, 0.27);
		given(discoverService.searchWithCorrection(eq("드늬 뷜베브"), anyInt(), anyString())).willReturn(
				new DiscoverService.DiscoverSearch(List.of(dune), new QueryCorrection("드니 빌뇌브", "드늬 뷜베브", "드니 빌뇌브")));

		mockMvc.perform(get("/discover").param("q", "드늬 뷜베브"))
			.andExpect(status().isOk())
			.andExpect(content().string(containsString("&#39;드늬 뷜베브&#39;을(를) &#39;드니 빌뇌브&#39;(으)로 고쳐 검색했습니다.")))
			.andExpect(content().string(containsString("듄: 파트 2")));
	}

}
