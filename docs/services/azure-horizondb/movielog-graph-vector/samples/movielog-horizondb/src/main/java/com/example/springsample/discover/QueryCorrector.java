package com.example.springsample.discover;

import java.text.Normalizer;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

/**
 * Corrects misspelled person names and movie titles in a semantic search query ("드늬 뷜베브" → "드니 빌뇌브").
 * An embedding does not treat a misspelled name as the same person, and the keyword ranking needs the exact
 * spelling, so the query is rewritten before both.
 * <p>
 * Hangul is compared by jamo (NFD), where a vowel swap costs half an edit, because misspelled transliterations
 * mostly differ in vowels. To leave descriptive queries alone, only words found in no movie document (ignoring a
 * trailing particle such as 와·을) are corrected, and the best candidate must reach {@link #MIN_SIMILARITY} and beat
 * the second by {@link #MIN_MARGIN}. Windows of one to three words compete on similarity, so a full name replaces
 * both of its words ("드늬 뷜베브") while a modifier next to a title stays ("인셉숀 2" → "인셉션 2"); on a tie the
 * longer window wins.
 */
@Component
class QueryCorrector {

	private static final Logger logger = LoggerFactory.getLogger(QueryCorrector.class);

	static final double MIN_SIMILARITY = 0.75;

	static final double MIN_MARGIN = 0.1;

	private static final int MAX_WINDOW = 3;

	private static final int MIN_JAMO = 4;

	private static final int MAX_LENGTH_GAP = 3;

	private static final Duration TTL = Duration.ofMinutes(10);

	private static final List<String> PARTICLES = List.of("에서", "으로", "과", "와", "은", "는", "이", "가", "을", "를",
			"의", "에", "로", "도", "만");

	private final JdbcClient jdbc;

	private volatile @Nullable Snapshot snapshot;

	QueryCorrector(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	Optional<QueryCorrection> correct(String query) {
		return correct(query, snapshot());
	}

	/** Drops the cached names and documents; the next query reloads them. */
	void refresh() {
		snapshot = null;
	}

	private Snapshot snapshot() {
		Snapshot current = snapshot;
		if (current == null || current.loadedAt().plus(TTL).isBefore(Instant.now())) {
			synchronized (this) {
				current = snapshot;
				if (current == null || current.loadedAt().plus(TTL).isBefore(Instant.now())) {
					current = load();
					snapshot = current;
				}
			}
		}
		return current;
	}

	private Snapshot load() {
		try {
			List<String> names = jdbc.sql("""
					SELECT name FROM catalog.people
					UNION SELECT name_en FROM catalog.people WHERE name_en IS NOT NULL
					UNION SELECT title FROM public.movies""").query(String.class).list();
			String corpus = jdbc.sql("SELECT coalesce(string_agg(lower(doc), chr(10)), '') FROM catalog.movie_docs")
				.query(String.class)
				.single();
			return Snapshot.of(names, corpus, Instant.now());
		}
		catch (DataAccessException ex) {
			// Without the catalog (for example the H2 dev profile) queries are searched as typed.
			logger.debug("Spelling correction is off: {}", ex.getMessage());
			return Snapshot.of(List.of(), "", Instant.now());
		}
	}

	static Optional<QueryCorrection> correct(String query, Snapshot snapshot) {
		String[] words = query.strip().split("\\s+");
		Candidate chosen = null;
		for (int size = Math.min(MAX_WINDOW, words.length); size >= 1; size--) {
			for (int start = 0; start + size <= words.length; start++) {
				String[] window = Arrays.copyOfRange(words, start, start + size);
				if (Arrays.stream(window).allMatch(snapshot::isKnown)) {
					continue;
				}
				Candidate candidate = snapshot.closest(String.join(" ", window), start, size);
				if (candidate != null && (chosen == null || candidate.similarity() > chosen.similarity())) {
					chosen = candidate;
				}
			}
		}
		if (chosen == null) {
			return Optional.empty();
		}
		List<String> rewritten = new ArrayList<>(Arrays.asList(words).subList(0, chosen.start()));
		rewritten.add(chosen.name());
		rewritten.addAll(Arrays.asList(words).subList(chosen.start() + chosen.size(), words.length));
		return Optional.of(new QueryCorrection(String.join(" ", rewritten), chosen.from(), chosen.name()));
	}

	static String jamo(String text) {
		return Normalizer.normalize(text.toLowerCase(Locale.ROOT).replaceAll("\\s+", ""), Normalizer.Form.NFD);
	}

	/** 1 - weighted edit distance / longer length, where a jamo vowel swap costs 0.5. */
	static double similarity(String a, String b) {
		double[] previous = new double[b.length() + 1];
		double[] current = new double[b.length() + 1];
		for (int j = 0; j <= b.length(); j++) {
			previous[j] = j;
		}
		for (int i = 1; i <= a.length(); i++) {
			current[0] = i;
			char ca = a.charAt(i - 1);
			for (int j = 1; j <= b.length(); j++) {
				char cb = b.charAt(j - 1);
				double swap = (ca == cb) ? 0 : (isVowel(ca) && isVowel(cb)) ? 0.5 : 1;
				current[j] = Math.min(Math.min(previous[j] + 1, current[j - 1] + 1), previous[j - 1] + swap);
			}
			double[] swapRows = previous;
			previous = current;
			current = swapRows;
		}
		int longer = Math.max(a.length(), b.length());
		return (longer == 0) ? 1 : 1 - previous[b.length()] / longer;
	}

	private static boolean isVowel(char c) {
		return c >= '\u1161' && c <= '\u1175';
	}

	private record Candidate(String from, String name, double similarity, int start, int size) {
	}

	/** Correction candidates keyed by jamo, and every movie document lower-cased. */
	record Snapshot(Map<String, String> names, String corpus, Instant loadedAt) {

		static Snapshot of(List<String> names, String corpus, Instant loadedAt) {
			Map<String, String> byJamo = new LinkedHashMap<>();
			for (String name : names) {
				if (name != null && !name.isBlank()) {
					byJamo.putIfAbsent(jamo(name), name.strip());
				}
			}
			return new Snapshot(byJamo, corpus, loadedAt);
		}

		boolean isKnown(String word) {
			String lower = word.toLowerCase(Locale.ROOT);
			if (corpus.contains(lower)) {
				return true;
			}
			for (String particle : PARTICLES) {
				if (lower.length() > particle.length() && lower.endsWith(particle)
						&& corpus.contains(lower.substring(0, lower.length() - particle.length()))) {
					return true;
				}
			}
			return false;
		}

		@Nullable Candidate closest(String window, int start, int size) {
			String key = jamo(window);
			if (key.length() < MIN_JAMO || names.containsKey(key)) {
				return null;
			}
			double best = 0;
			double second = 0;
			String bestName = null;
			for (Map.Entry<String, String> entry : names.entrySet()) {
				if (Math.abs(entry.getKey().length() - key.length()) > MAX_LENGTH_GAP) {
					continue;
				}
				double similarity = similarity(key, entry.getKey());
				if (similarity > best) {
					second = best;
					best = similarity;
					bestName = entry.getValue();
				}
				else if (similarity > second) {
					second = similarity;
				}
			}
			return (bestName != null && best >= MIN_SIMILARITY && best - second >= MIN_MARGIN)
					? new Candidate(window, bestName, best, start, size) : null;
		}

	}

}
