package com.example.springsample.metrics;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.function.LongSupplier;

import com.example.springsample.comment.CommentRepository;
import com.example.springsample.member.MemberRepository;
import com.example.springsample.movie.MovieRepository;
import com.example.springsample.review.ReviewRepository;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.binder.MeterBinder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Totals stored in the database. Each value is cached for {@link #MAX_AGE} so frequent scrapes
 * do not turn into frequent {@code count(*)} queries.
 */
@Component
class BusinessGauges implements MeterBinder {

	static final Duration MAX_AGE = Duration.ofMinutes(1);

	private final MovieRepository movies;

	private final ReviewRepository reviews;

	private final CommentRepository comments;

	private final MemberRepository members;

	private final Clock clock;

	BusinessGauges(MovieRepository movies, ReviewRepository reviews, CommentRepository comments,
			MemberRepository members, Clock clock) {
		this.movies = movies;
		this.reviews = reviews;
		this.comments = comments;
		this.members = members;
		this.clock = clock;
	}

	@Override
	public void bindTo(MeterRegistry registry) {
		gauge(registry, "movies.stored", "Movies imported into the local catalog", movies::count);
		gauge(registry, "reviews.stored", "Reviews currently stored", reviews::count);
		gauge(registry, "comments.stored", "Comments currently stored", comments::count);
		gauge(registry, "members.stored", "Registered members", members::count);
	}

	private void gauge(MeterRegistry registry, String name, String description, LongSupplier query) {
		CachedCount count = new CachedCount(query, clock);
		Gauge.builder(BusinessMetrics.PREFIX + name, count, CachedCount::value)
			.description(description)
			.strongReference(true)
			.register(registry);
	}

	static final class CachedCount {

		private static final Logger logger = LoggerFactory.getLogger(CachedCount.class);

		private final LongSupplier query;

		private final Clock clock;

		private double value = Double.NaN;

		private Instant refreshedAt = Instant.MIN;

		CachedCount(LongSupplier query, Clock clock) {
			this.query = query;
			this.clock = clock;
		}

		synchronized double value() {
			Instant now = clock.instant();
			if (!now.isBefore(refreshedAt.plus(MAX_AGE))) {
				try {
					value = query.getAsLong();
				}
				catch (RuntimeException ex) {
					logger.warn("Could not refresh business gauge: {}", ex.getMessage());
				}
				refreshedAt = now;
			}
			return value;
		}

	}

}
