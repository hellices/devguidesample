package com.example.springsample.discover;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Set;

import com.example.springsample.discover.MovieGraphRepository.EdgeRow;
import com.example.springsample.discover.MovieGraphRepository.Props;
import com.example.springsample.discover.MovieGraphRepository.Vertex;
import org.junit.jupiter.api.Test;

class MovieGraphRepositoryTests {

	private static final Vertex INCEPTION = movie("m1", 27205);

	private static final Vertex DARK_KNIGHT = movie("m2", 155);

	private static final Vertex NOLAN = person("p1", "크리스토퍼 놀런");

	private static final Vertex CAINE = person("p2", "마이클 케인");

	private static final Vertex SCI_FI = new Vertex("g1", "Genre", Props.parse("{\"name\": \"SF\"}"));

	@Test
	void keepsOnlyNeighborsLinkingTwoDifferentResultMoviesAndDeduplicatesEdges() {
		List<EdgeRow> rows = List.of(
				// Two edges to the same result movie must not count as a shared neighbor.
				edge(INCEPTION, NOLAN, "e1", "DIRECTED"), edge(INCEPTION, NOLAN, "e2", "ACTED_IN"),
				// AGE returns an undirected match once from each side; the edge is drawn once.
				edge(INCEPTION, CAINE, "e3", "ACTED_IN"), edge(CAINE, INCEPTION, "e3", "ACTED_IN"),
				edge(DARK_KNIGHT, CAINE, "e4", "ACTED_IN"),
				edge(INCEPTION, SCI_FI, "e5", "IN_GENRE"));

		GraphView view = MovieGraphRepository.assemble(rows, Set.of(27205L, 155L), true);

		assertThat(view.nodes()).extracting(GraphView.Node::id).containsExactlyInAnyOrder("m1", "m2", "p2");
		assertThat(view.nodes()).filteredOn(GraphView.Node::focus).extracting(GraphView.Node::tmdbId)
			.containsExactlyInAnyOrder(27205L, 155L);
		assertThat(view.edges()).extracting(GraphView.Edge::id).containsExactlyInAnyOrder("e3", "e4");
	}

	@Test
	void movieNeighborhoodKeepsEveryNeighbor() {
		List<EdgeRow> rows = List.of(edge(INCEPTION, NOLAN, "e1", "DIRECTED"), edge(INCEPTION, SCI_FI, "e5", "IN_GENRE"));

		GraphView view = MovieGraphRepository.assemble(rows, Set.of(27205L), false);

		assertThat(view.nodes()).extracting(GraphView.Node::id).containsExactlyInAnyOrder("m1", "p1", "g1");
		assertThat(view.edges()).hasSize(2);
	}

	private static Vertex movie(String id, long tmdbId) {
		return new Vertex(id, "Movie", Props.parse("{\"tmdb_id\": " + tmdbId + ", \"title\": \"t" + tmdbId + "\"}"));
	}

	private static Vertex person(String id, String name) {
		return new Vertex(id, "Person", Props.parse("{\"name\": \"" + name + "\"}"));
	}

	private static EdgeRow edge(Vertex a, Vertex b, String id, String type) {
		return new EdgeRow(a, b, id, type, a.id(), b.id(), null);
	}

}
