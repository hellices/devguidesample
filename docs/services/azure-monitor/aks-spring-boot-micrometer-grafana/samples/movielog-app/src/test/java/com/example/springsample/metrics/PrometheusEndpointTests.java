package com.example.springsample.metrics;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.micrometer.metrics.test.autoconfigure.AutoConfigureMetrics;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(properties = "app.metrics.scrape-allowed-ips=127.0.0.1,10.20.0.0/16")
@AutoConfigureMockMvc
@AutoConfigureMetrics
@ActiveProfiles("test")
class PrometheusEndpointTests {

	@Autowired
	private MockMvc mockMvc;

	@Test
	void exposesBusinessMetricsToAllowedScrapers() throws Exception {
		mockMvc.perform(get("/actuator/health")).andExpect(status().isOk());

		mockMvc.perform(get("/actuator/prometheus"))
			.andExpect(status().isOk())
			.andExpect(content().string(containsString("movielog_movie_views_total{application=\"spring-sample\",channel=\"web\"}")))
			.andExpect(content().string(containsString("movielog_reviews_stored")))
			.andExpect(content().string(containsString("http_server_requests_seconds_bucket")));
		mockMvc.perform(get("/actuator/prometheus").with(request -> {
			request.setRemoteAddr("10.20.3.4");
			return request;
		})).andExpect(status().isOk());
	}

	/** Guards the names dashboards depend on, e.g. against Prometheus rewriting reserved suffixes. */
	@Test
	void exportsDocumentedMetricNames() throws Exception {
		String body = mockMvc.perform(get("/actuator/prometheus"))
			.andExpect(status().isOk())
			.andReturn().getResponse().getContentAsString();

		assertThat(body).contains(
				"movielog_movie_views_total{", "movielog_review_views_total{", "movielog_reviews_posted_total{",
				"movielog_comments_posted_total{", "movielog_members_signups_total{", "movielog_review_rating_stars_count{",
				"movielog_movies_stored{", "movielog_reviews_stored{", "movielog_comments_stored{",
				"movielog_members_stored{");
		assertThat(body).doesNotContain("movielog_reviews_total", "movielog_comments_total");
	}

	@Test
	void rejectsOtherAddresses() throws Exception {
		mockMvc.perform(get("/actuator/prometheus").with(request -> {
			request.setRemoteAddr("203.0.113.9");
			return request;
		})).andExpect(status().isUnauthorized());
	}

}
