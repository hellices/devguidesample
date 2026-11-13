package com.example.springsample.discover;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import org.jspecify.annotations.Nullable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * openCypher queries on the Apache AGE graph {@code movie_graph}.
 * <p>
 * AGE accepts Cypher parameters only as a prepared-statement parameter in the third argument of cypher(),
 * so this repository formats only numeric TMDB ids into the Cypher text instead.
 * Every query returns one row per edge: both endpoint vertices and the edge, flattened to SQL columns.
 */
@Repository
class MovieGraphRepository {

	static final String GRAPH = "movie_graph";

	private static final String ROW_COLUMNS = """
			a_id ag_catalog.agtype, a_label ag_catalog.agtype, a_props ag_catalog.agtype,
			b_id ag_catalog.agtype, b_label ag_catalog.agtype, b_props ag_catalog.agtype,
			r_id ag_catalog.agtype, r_type ag_catalog.agtype, r_start ag_catalog.agtype, r_end ag_catalog.agtype,
			r_props ag_catalog.agtype""";

	private static final String RETURN_ROW = """
			RETURN id(a), label(a), properties(a), id(b), label(b), properties(b),
			       id(r), type(r), start_id(r), end_id(r), properties(r)""";

	// JdbcTemplate without parameters: named-parameter parsing would read ":Movie" in Cypher as a parameter.
	private final JdbcTemplate jdbc;

	MovieGraphRepository(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	/** The movie, its people, genres and SIMILAR_TO neighbors, plus other movies of the same people. */
	GraphView neighborhood(long tmdbId, int coCreditLimit) {
		List<EdgeRow> rows = new ArrayList<>(cypher("""
				MATCH (a:Movie {tmdb_id: %d})-[r]-(b)
				%s""".formatted(tmdbId, RETURN_ROW)));
		rows.addAll(cypher("""
				MATCH (m:Movie {tmdb_id: %d})<-[]-(a:Person)-[r]->(b:Movie)
				WHERE id(b) <> id(m)
				%s
				LIMIT %d""".formatted(tmdbId, RETURN_ROW, coCreditLimit)));
		return assemble(rows, Set.of(tmdbId), false);
	}

	/**
	 * Connections among the given movies: their direct neighbors (people, genres, SIMILAR_TO movies) that link
	 * at least two of them. Neighbors linked to only one of the movies are dropped to keep the picture readable.
	 */
	GraphView among(Collection<Long> tmdbIds) {
		if (tmdbIds.isEmpty()) {
			return new GraphView(List.of(), List.of());
		}
		String list = tmdbIds.stream().map(String::valueOf).collect(Collectors.joining(", "));
		// UNWIND + property map lets AGE use the GIN index per movie; "WHERE a.tmdb_id IN [...]" on an
		// undirected pattern scanned every edge (about 27 s instead of 0.1 s for 8 movies).
		List<EdgeRow> rows = cypher("""
				UNWIND [%s] AS t
				MATCH (a:Movie {tmdb_id: t})-[r]-(b)
				%s""".formatted(list, RETURN_ROW));
		return assemble(rows, Set.copyOf(tmdbIds), true);
	}

	private List<EdgeRow> cypher(String query) {
		return jdbc.query("""
				SELECT a_id::text AS a_id, a_label::text AS a_label, a_props::text AS a_props,
				       b_id::text AS b_id, b_label::text AS b_label, b_props::text AS b_props,
				       r_id::text AS r_id, r_type::text AS r_type, r_start::text AS r_start, r_end::text AS r_end,
				       r_props::text AS r_props
				FROM ag_catalog.cypher('%s', $cy$ %s $cy$) AS (%s)""".formatted(GRAPH, query, ROW_COLUMNS), MovieGraphRepository::row);
	}

	private static GraphView assemble(List<EdgeRow> rows, Set<Long> focusIds, boolean onlyShared) {
		Map<String, GraphView.Node> nodes = new LinkedHashMap<>();
		Map<String, GraphView.Edge> edges = new LinkedHashMap<>();
		for (EdgeRow row : rows) {
			nodes.putIfAbsent(row.a().id(), row.a().toNode(focusIds));
			nodes.putIfAbsent(row.b().id(), row.b().toNode(focusIds));
			edges.putIfAbsent(row.edgeId(), new GraphView.Edge(row.edgeId(), row.start(), row.end(), row.type(),
					row.score()));
		}
		if (onlyShared) {
			Set<String> keep = new HashSet<>();
			Map<String, Set<String>> linkedFocus = new HashMap<>();
			for (GraphView.Node node : nodes.values()) {
				if (node.focus()) {
					keep.add(node.id());
				}
			}
			for (GraphView.Edge edge : edges.values()) {
				if (keep.contains(edge.source()) && !keep.contains(edge.target())) {
					linkedFocus.computeIfAbsent(edge.target(), id -> new HashSet<>()).add(edge.source());
				}
				else if (keep.contains(edge.target()) && !keep.contains(edge.source())) {
					linkedFocus.computeIfAbsent(edge.source(), id -> new HashSet<>()).add(edge.target());
				}
			}
			// A neighbor stays only when it links two different result movies, not two edges to the same one
			// (for example a director who also acted in that movie).
			linkedFocus.forEach((id, focus) -> {
				if (focus.size() >= 2) {
					keep.add(id);
				}
			});
			nodes.keySet().retainAll(keep);
			edges.values().removeIf(edge -> !keep.contains(edge.source()) || !keep.contains(edge.target()));
		}
		return new GraphView(List.copyOf(nodes.values()), List.copyOf(edges.values()));
	}

	private static EdgeRow row(ResultSet rs, int rowNum) throws SQLException {
		return new EdgeRow(
				new Vertex(rs.getString("a_id"), unquote(rs.getString("a_label")), Props.parse(rs.getString("a_props"))),
				new Vertex(rs.getString("b_id"), unquote(rs.getString("b_label")), Props.parse(rs.getString("b_props"))),
				rs.getString("r_id"), unquote(rs.getString("r_type")), rs.getString("r_start"), rs.getString("r_end"),
				Props.parse(rs.getString("r_props")).number("score"));
	}

	private static String unquote(String agtypeString) {
		return Props.parseString(agtypeString.strip(), new int[] { 0 });
	}

	private record EdgeRow(Vertex a, Vertex b, String edgeId, String type, String start, String end,
			@Nullable Double score) {
	}

	private record Vertex(String id, String label, Props props) {

		GraphView.Node toNode(Set<Long> focusIds) {
			Double tmdb = props.number("tmdb_id");
			Long tmdbId = (tmdb == null) ? null : tmdb.longValue();
			Double year = props.number("year");
			String name = props.text("title");
			if (name == null) {
				name = props.text("name");
			}
			return new GraphView.Node(id, label, (name == null) ? id : name, tmdbId,
					(year == null) ? null : year.intValue(), tmdbId != null && focusIds.contains(tmdbId));
		}

	}

	/**
	 * Flat agtype map ({@code {"key": "text", "n": 1}}) as printed by AGE. Vertex and edge properties
	 * in this graph hold only strings, numbers and null, so a small parser avoids a JSON binding.
	 */
	record Props(Map<String, Object> values) {

		static Props parse(@Nullable String text) {
			Map<String, Object> values = new HashMap<>();
			if (text == null) {
				return new Props(values);
			}
			String s = text.strip();
			int[] pos = { 0 };
			if (s.isEmpty() || s.charAt(0) != '{') {
				return new Props(values);
			}
			pos[0] = 1;
			while (pos[0] < s.length()) {
				skipSpace(s, pos);
				if (s.charAt(pos[0]) == '}') {
					break;
				}
				String key = parseString(s, pos);
				skipSpace(s, pos);
				pos[0]++; // ':'
				skipSpace(s, pos);
				Object value;
				if (s.charAt(pos[0]) == '"') {
					value = parseString(s, pos);
				}
				else {
					int start = pos[0];
					while (pos[0] < s.length() && ",}".indexOf(s.charAt(pos[0])) < 0) {
						pos[0]++;
					}
					String token = s.substring(start, pos[0]).strip();
					value = token.equals("null") ? null : parseNumber(token);
				}
				values.put(key, value);
				skipSpace(s, pos);
				if (pos[0] < s.length() && s.charAt(pos[0]) == ',') {
					pos[0]++;
				}
			}
			return new Props(values);
		}

		@Nullable String text(String key) {
			return (values.get(key) instanceof String value) ? value : null;
		}

		@Nullable Double number(String key) {
			return (values.get(key) instanceof Double value) ? value : null;
		}

		private static @Nullable Double parseNumber(String token) {
			try {
				// AGE may suffix typed numbers, e.g. 1.5::numeric.
				int cast = token.indexOf("::");
				return Double.valueOf((cast < 0) ? token : token.substring(0, cast));
			}
			catch (NumberFormatException ex) {
				return null;
			}
		}

		private static void skipSpace(String s, int[] pos) {
			while (pos[0] < s.length() && Character.isWhitespace(s.charAt(pos[0]))) {
				pos[0]++;
			}
		}

		static String parseString(String s, int[] pos) {
			if (pos[0] >= s.length() || s.charAt(pos[0]) != '"') {
				return s.substring(pos[0]);
			}
			StringBuilder out = new StringBuilder();
			int i = pos[0] + 1;
			while (i < s.length() && s.charAt(i) != '"') {
				char c = s.charAt(i);
				if (c == '\\' && i + 1 < s.length()) {
					char next = s.charAt(++i);
					switch (next) {
						case 'n' -> out.append('\n');
						case 't' -> out.append('\t');
						case 'r' -> out.append('\r');
						case 'u' -> {
							out.append((char) Integer.parseInt(s.substring(i + 1, i + 5), 16));
							i += 4;
						}
						default -> out.append(next);
					}
				}
				else {
					out.append(c);
				}
				i++;
			}
			pos[0] = i + 1;
			return out.toString();
		}

	}

}
