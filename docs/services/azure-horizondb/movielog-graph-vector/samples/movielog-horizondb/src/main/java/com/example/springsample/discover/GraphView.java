package com.example.springsample.discover;

import java.util.List;

import org.jspecify.annotations.Nullable;

/** Graph in the shape Cytoscape.js expects: node and edge ids are AGE graph ids as strings. */
public record GraphView(List<Node> nodes, List<Edge> edges) {

	/** {@code kind} is the AGE vertex label: Movie, Person or Genre. */
	public record Node(String id, String kind, String name, @Nullable Long tmdbId, @Nullable Integer year,
			boolean focus) {
	}

	/** {@code type} is the AGE edge label; {@code score} is set for SIMILAR_TO only. */
	public record Edge(String id, String source, String target, String type, @Nullable Double score) {
	}

}
