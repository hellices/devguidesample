package com.example.springsample.discover;

import java.util.List;
import java.util.Map;

import org.jspecify.annotations.Nullable;

/** Graph in the shape Cytoscape.js expects: node and edge ids are AGE graph ids as strings. */
public record GraphView(List<Node> nodes, List<Edge> edges) {

	/**
	 * {@code kind} is the AGE vertex label: Movie, Person or Genre. {@code qid} identifies a Person (Wikidata id or
	 * {@code tmdb:<id>}) so the page can expand it; {@code posterUrl} is a small TMDB poster of a Movie.
	 */
	public record Node(String id, String kind, String name, @Nullable Long tmdbId, @Nullable Integer year,
			boolean focus, @Nullable String qid, @Nullable String posterUrl) {
	}

	/** {@code type} is the AGE edge label; {@code score} is set for SIMILAR_TO only. */
	public record Edge(String id, String source, String target, String type, @Nullable Double score) {
	}

	/** Movie nodes get the poster URL stored for their TMDB id; the graph itself holds no posters. */
	GraphView withPosters(Map<Long, String> posterUrls) {
		if (posterUrls.isEmpty()) {
			return this;
		}
		List<Node> withPosters = nodes.stream()
			.map(node -> (node.tmdbId() == null || !posterUrls.containsKey(node.tmdbId())) ? node
					: new Node(node.id(), node.kind(), node.name(), node.tmdbId(), node.year(), node.focus(), node.qid(),
							posterUrls.get(node.tmdbId())))
			.toList();
		return new GraphView(withPosters, edges);
	}

}
