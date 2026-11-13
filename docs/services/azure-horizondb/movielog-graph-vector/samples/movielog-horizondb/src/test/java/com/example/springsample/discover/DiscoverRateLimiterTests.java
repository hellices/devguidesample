package com.example.springsample.discover;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;

import org.junit.jupiter.api.Test;

class DiscoverRateLimiterTests {

	private final MutableClock clock = new MutableClock();

	@Test
	void capsEachClientPerMinuteAndResetsInTheNextMinute() {
		var limiter = new DiscoverRateLimiter(new DiscoverRateLimitProperties(2, 0), clock);

		assertThat(limiter.tryAcquire("10.0.0.1")).isTrue();
		assertThat(limiter.tryAcquire("10.0.0.1")).isTrue();
		assertThat(limiter.tryAcquire("10.0.0.1")).isFalse();
		assertThat(limiter.tryAcquire("10.0.0.2")).isTrue();

		clock.now = clock.now.plusSeconds(60);
		assertThat(limiter.tryAcquire("10.0.0.1")).isTrue();
	}

	@Test
	void totalCapRefusalDoesNotSpendTheClientAllowance() {
		var limiter = new DiscoverRateLimiter(new DiscoverRateLimitProperties(2, 2), clock);

		assertThat(limiter.tryAcquire("a")).isTrue();
		assertThat(limiter.tryAcquire("b")).isTrue();
		assertThat(limiter.tryAcquire("c")).isFalse();

		clock.now = clock.now.plusSeconds(60);
		assertThat(limiter.tryAcquire("c")).isTrue();
		assertThat(limiter.tryAcquire("c")).isTrue();
	}

	@Test
	void truncatesQueriesOnCodePointBoundaries() {
		String text = "a".repeat(3) + "😀" + "b";

		assertThat(DiscoverService.truncate(text, 4)).isEqualTo("aaa😀");
		assertThat(DiscoverService.truncate(text, 3)).isEqualTo("aaa");
		assertThat(DiscoverService.truncate(text, 10)).isEqualTo(text);
	}

	private static final class MutableClock extends Clock {

		Instant now = Instant.parse("2026-11-14T00:00:30Z");

		@Override
		public ZoneId getZone() {
			return ZoneOffset.UTC;
		}

		@Override
		public Clock withZone(ZoneId zone) {
			return this;
		}

		@Override
		public Instant instant() {
			return now;
		}

	}

}
