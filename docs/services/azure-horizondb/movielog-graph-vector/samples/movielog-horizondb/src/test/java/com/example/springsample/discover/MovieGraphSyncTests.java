package com.example.springsample.discover;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;

class MovieGraphSyncTests {

	private final GraphSyncRepository repository = mock();

	private final SimpleMeterRegistry registry = new SimpleMeterRegistry();

	private final MovieGraphSync sync = new MovieGraphSync(repository, registry, 500);

	private long runs(String mode, String outcome) {
		return registry.timer("movielog.discover.graph.sync", "mode", mode, "outcome", outcome).count();
	}

	@Test
	void queueRunsDoNotLookForDriftOrForceAReconcile() {
		given(repository.processQueue(500, false)).willReturn(3, 0);

		sync.processQueue();
		sync.processQueue();

		verify(repository, never()).enqueueDrift();
		assertThat(runs("queue", "applied")).isEqualTo(1);
		assertThat(runs("queue", "idle")).isEqualTo(1);
	}

	@Test
	void driftRunsQueueDriftThenReconcile() {
		given(repository.enqueueDrift()).willReturn(2);
		given(repository.processQueue(500, true)).willReturn(2);

		sync.reconcile();

		verify(repository).processQueue(500, true);
		assertThat(runs("drift", "applied")).isEqualTo(1);
	}

	@Test
	void aHeldLockIsSkippedAndAFailureIsRecordedWithoutThrowing() {
		given(repository.processQueue(500, false)).willReturn(null)
			.willThrow(new DataAccessResourceFailureException("down"));

		assertThat(sync.run("queue", false)).isNull();
		assertThat(sync.run("queue", false)).isNull();

		assertThat(runs("queue", "skipped")).isEqualTo(1);
		assertThat(runs("queue", "error")).isEqualTo(1);
	}

}
