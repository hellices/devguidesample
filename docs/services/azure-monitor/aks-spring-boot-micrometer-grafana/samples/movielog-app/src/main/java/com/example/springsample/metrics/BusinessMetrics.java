package com.example.springsample.metrics;

import java.util.Locale;

import com.example.springsample.comment.CommentEvents;
import com.example.springsample.member.MemberRegistered;
import com.example.springsample.movie.MovieEvents;
import com.example.springsample.review.ReviewEvents;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionalEventListener;

/**
 * Turns business events into Micrometer meters. See {@code docs/monitoring.md} for the catalogue.
 * <p>
 * Listeners run after the publishing transaction commits, so rolled-back work is never counted;
 * {@code fallbackExecution} also records events published outside a transaction.
 * Tags stay low-cardinality: never add ids, titles or user names (per-movie numbers live in the database).
 * Avoid names ending in {@code .created}: the Prometheus client strips that reserved OpenMetrics suffix.
 */
@Component
class BusinessMetrics {

	static final String PREFIX = "movielog.";

	private final MeterRegistry registry;

	private final DistributionSummary reviewRating;

	BusinessMetrics(MeterRegistry registry) {
		this.registry = registry;
		this.reviewRating = DistributionSummary.builder(PREFIX + "review.rating")
			.description("Star rating of new reviews")
			.baseUnit("stars")
			.register(registry);
		registerZeroCounters();
	}

	@TransactionalEventListener(fallbackExecution = true)
	void movieViewed(MovieEvents.Viewed event) {
		counter("movie.views", "Movie page views (movie clicks)", "channel", channel()).increment();
	}

	@TransactionalEventListener(fallbackExecution = true)
	void movieSearched(MovieEvents.Searched event) {
		if (event.page() == 1) {
			counter("movie.searches", "New movie searches by outcome", "channel", channel(), "outcome",
					tag(event.outcome())).increment();
		}
		else {
			counter("movie.search.scrolls", "Further search result pages loaded by infinite scrolling",
					"channel", channel(), "outcome", tag(event.outcome())).increment();
		}
	}

	@TransactionalEventListener(fallbackExecution = true)
	void movieSynced(MovieEvents.Synced event) {
		counter("movie.catalog.lookups", "How movie data was served: local snapshot or TMDB", "outcome",
				tag(event.outcome())).increment();
	}

	@TransactionalEventListener(fallbackExecution = true)
	void reviewCreated(ReviewEvents.Created event) {
		counter("reviews.posted", "New reviews", "channel", channel(), "verdict",
				event.fresh() ? "fresh" : "rotten").increment();
		reviewRating.record(event.rating() / 2.0);
	}

	@TransactionalEventListener(fallbackExecution = true)
	void reviewViewed(ReviewEvents.Viewed event) {
		counter("review.views", "Review page views", "channel", channel()).increment();
	}

	@TransactionalEventListener(fallbackExecution = true)
	void reviewDeleted(ReviewEvents.Deleted event) {
		counter("reviews.deleted", "Deleted reviews", "channel", channel()).increment();
	}

	@TransactionalEventListener(fallbackExecution = true)
	void commentCreated(CommentEvents.Created event) {
		counter("comments.posted", "New comments", "channel", channel()).increment();
	}

	@TransactionalEventListener(fallbackExecution = true)
	void commentDeleted(CommentEvents.Deleted event) {
		counter("comments.deleted", "Deleted comments", "channel", channel()).increment();
	}

	@TransactionalEventListener(fallbackExecution = true)
	void memberRegistered(MemberRegistered event) {
		counter("members.signups", "New member sign-ups", "channel", channel()).increment();
	}

	/** Registered up front so dashboards and rate() see 0 instead of "no data" before the first event. */
	private void registerZeroCounters() {
		for (Channel channel : new Channel[] { Channel.WEB, Channel.API }) {
			String value = channel.tagValue();
			counter("movie.views", "Movie page views (movie clicks)", "channel", value);
			counter("review.views", "Review page views", "channel", value);
			counter("comments.posted", "New comments", "channel", value);
			counter("reviews.posted", "New reviews", "channel", value, "verdict", "fresh");
			counter("reviews.posted", "New reviews", "channel", value, "verdict", "rotten");
		}
		counter("members.signups", "New member sign-ups", "channel", Channel.WEB.tagValue());
	}

	private Counter counter(String name, String description, String... tags) {
		return Counter.builder(PREFIX + name).description(description).tags(tags).register(registry);
	}

	private static String channel() {
		return Channel.current().tagValue();
	}

	private static String tag(Enum<?> value) {
		return value.name().toLowerCase(Locale.ROOT);
	}

}
