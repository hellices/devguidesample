package com.example.springsample.metrics;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.concurrent.atomic.AtomicLong;

import org.junit.jupiter.api.Test;

class CachedCountTests {

	@Test
	void queriesAtMostOncePerMaxAge() {
		AtomicLong rows = new AtomicLong(5);
		AtomicLong queries = new AtomicLong();
		MutableClock clock = new MutableClock();
		var count = new BusinessGauges.CachedCount(() -> {
			queries.incrementAndGet();
			return rows.get();
		}, clock);

		assertThat(count.value()).isEqualTo(5);
		rows.set(7);
		assertThat(count.value()).isEqualTo(5);
		clock.now = clock.now.plus(BusinessGauges.MAX_AGE).plusSeconds(1);
		assertThat(count.value()).isEqualTo(7);
		assertThat(queries).hasValue(2);
	}

	@Test
	void refreshesExactlyWhenMaxAgeHasPassed() {
		AtomicLong rows = new AtomicLong(5);
		MutableClock clock = new MutableClock();
		var count = new BusinessGauges.CachedCount(rows::get, clock);

		assertThat(count.value()).isEqualTo(5);
		rows.set(7);
		clock.now = clock.now.plus(BusinessGauges.MAX_AGE).minusMillis(1);
		assertThat(count.value()).isEqualTo(5);
		clock.now = clock.now.plusMillis(1);
		assertThat(count.value()).isEqualTo(7);
	}

	@Test
	void keepsLastValueWhenQueryFails() {
		MutableClock clock = new MutableClock();
		AtomicLong calls = new AtomicLong();
		var count = new BusinessGauges.CachedCount(() -> {
			if (calls.incrementAndGet() > 1) {
				throw new IllegalStateException("database down");
			}
			return 3;
		}, clock);

		assertThat(count.value()).isEqualTo(3);
		clock.now = clock.now.plus(BusinessGauges.MAX_AGE).plusSeconds(1);
		assertThat(count.value()).isEqualTo(3);
	}

	private static final class MutableClock extends Clock {

		Instant now = Instant.parse("2026-11-03T00:00:00Z");

		@Override
		public ZoneOffset getZone() {
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
