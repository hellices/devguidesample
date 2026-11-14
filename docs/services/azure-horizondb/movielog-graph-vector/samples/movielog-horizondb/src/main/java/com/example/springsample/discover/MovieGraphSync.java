package com.example.springsample.discover;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBooleanProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;

/**
 * Keeps the AGE graph current. Triggers in HorizonDB queue every movie whose rows change
 * ({@code db/40-graph-sync.sql}), whether the app imported it or the catalog loader rewrote it; this job applies
 * the queue every 30 seconds and, once an hour, also queues drift between the relational rows and the graph and
 * reconciles all SIMILAR_TO edges. A full rebuild with {@code db/30-graph.sql} is only needed for the first build.
 * Every run is timed as {@code movielog.discover.graph.sync} with {@code mode} and {@code outcome} tags.
 */
@Configuration(proxyBeanMethods = false)
@EnableScheduling
@ConditionalOnBooleanProperty("app.discover.graph-sync.enabled")
class MovieGraphSync {

	private static final Logger logger = LoggerFactory.getLogger(MovieGraphSync.class);

	private final GraphSyncRepository repository;

	private final MeterRegistry registry;

	private final int batchSize;

	MovieGraphSync(GraphSyncRepository repository, MeterRegistry registry,
			@Value("${app.discover.graph-sync.batch-size:500}") int batchSize) {
		this.repository = repository;
		this.registry = registry;
		this.batchSize = batchSize;
	}

	/** Applies queued movies. Also called right after the indexer stores new movies. */
	@Scheduled(initialDelayString = "${app.discover.graph-sync.initial-delay:PT40S}",
			fixedDelayString = "${app.discover.graph-sync.interval:PT30S}")
	void processQueue() {
		run("queue", false);
	}

	/** Queues drift and reconciles SIMILAR_TO even when nothing was queued. */
	@Scheduled(initialDelayString = "${app.discover.graph-sync.drift-initial-delay:PT5M}",
			fixedDelayString = "${app.discover.graph-sync.drift-interval:PT1H}")
	void reconcile() {
		run("drift", true);
	}

	/** The applied movies, or null when the run was skipped or failed; never throws. */
	@Nullable Integer run(String mode, boolean reconcile) {
		Timer.Sample sample = Timer.start(registry);
		String outcome = "error";
		try {
			int drift = reconcile ? repository.enqueueDrift() : 0;
			Integer applied = repository.processQueue(batchSize, reconcile);
			outcome = (applied == null) ? "skipped" : (applied == 0) ? "idle" : "applied";
			if (applied != null && (applied > 0 || drift > 0)) {
				logger.info("Graph sync ({}) applied {} movie(s), {} from drift", mode, applied, drift);
			}
			return applied;
		}
		catch (RuntimeException ex) {
			logger.warn("Graph sync ({}) failed, retrying on the next run: {}", mode, ex.toString());
			return null;
		}
		finally {
			sample.stop(Timer.builder("movielog.discover.graph.sync")
				.description("Incremental updates of the AGE graph from queued relational changes")
				.tag("mode", mode)
				.tag("outcome", outcome)
				.register(registry));
		}
	}

}
