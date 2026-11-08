package com.example.springsample.metrics;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

class ChannelTests {

	@AfterEach
	void clearRequest() {
		RequestContextHolder.resetRequestAttributes();
	}

	@Test
	void apiRootAndPathsBelowItAreTheApiChannel() {
		assertThat(channelFor("/api")).isEqualTo(Channel.API);
		assertThat(channelFor("/api/movies/1")).isEqualTo(Channel.API);
		assertThat(channelFor("/apix")).isEqualTo(Channel.WEB);
		assertThat(channelFor("/movies/1")).isEqualTo(Channel.WEB);
	}

	@Test
	void noRequestIsInternal() {
		assertThat(Channel.current()).isEqualTo(Channel.INTERNAL);
	}

	private static Channel channelFor(String path) {
		RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(new MockHttpServletRequest("GET", path)));
		return Channel.current();
	}

}
