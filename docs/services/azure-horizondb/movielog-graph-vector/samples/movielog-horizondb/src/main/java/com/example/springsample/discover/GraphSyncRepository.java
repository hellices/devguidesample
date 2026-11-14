package com.example.springsample.discover;

import org.jspecify.annotations.Nullable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Calls the graph maintenance functions of {@code db/40-graph-sync.sql}. Each call is its own transaction; the
 * functions take the graph advisory lock themselves.
 */
@Repository
class GraphSyncRepository {

	private final JdbcClient jdbc;

	GraphSyncRepository(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	/** Applied movies, or null when another session holds the graph lock or the graph does not exist yet. */
	@Nullable Integer processQueue(int limit, boolean reconcile) {
		return jdbc.sql("SELECT catalog.process_graph_queue(:limit, :reconcile)")
			.param("limit", limit)
			.param("reconcile", reconcile)
			.query(Integer.class)
			.optional()
			.orElse(null);
	}

	/** Movies queued because they are only in public.movies or only in the graph. */
	int enqueueDrift() {
		return jdbc.sql("SELECT catalog.enqueue_graph_drift()").query(Integer.class).single();
	}

}
