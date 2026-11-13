package com.example.springsample.discover;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

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
	void refusesNewClientsBeyondTheTrackedLimitUntilTheNextMinute() {
		var limiter = new DiscoverRateLimiter(new DiscoverRateLimitProperties(5, 0), clock, 2);

		assertThat(limiter.tryAcquire("a")).isTrue();
		assertThat(limiter.tryAcquire("b")).isTrue();
		assertThat(limiter.tryAcquire("c")).isFalse();
		assertThat(limiter.tryAcquire("a")).isTrue();

		clock.now = clock.now.plusSeconds(60);
		assertThat(limiter.tryAcquire("c")).isTrue();
	}

	@Test
	void concurrentCallersNeverExceedTheCaps() throws Exception {
		var limiter = new DiscoverRateLimiter(new DiscoverRateLimitProperties(25, 60), clock);
		AtomicInteger granted = new AtomicInteger();
		CountDownLatch start = new CountDownLatch(1);
		try (ExecutorService pool = Executors.newFixedThreadPool(16)) {
			for (int i = 0; i < 400; i++) {
				String client = "client-" + (i % 4);
				pool.submit(() -> {
					start.await();
					if (limiter.tryAcquire(client)) {
						granted.incrementAndGet();
					}
					return null;
				});
			}
			start.countDown();
		}

		assertThat(granted).hasValue(60);
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
