package com.example.springsample.discover;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.List;

import org.junit.jupiter.api.Test;

class QueryCorrectorTests {

	private static final QueryCorrector.Snapshot SNAPSHOT = QueryCorrector.Snapshot.of(
			List.of("드니 빌뇌브", "크리스토퍼 놀런", "밥 놀런", "봉준호", "아이유", "아티스트", "티모시 샬라메", "인셉션",
					"박서준", "박서진"),
			"제목: 인셉션\n감독: 크리스토퍼 놀런\n출연: 티모시 샬라메\n줄거리: 아이 둘과 함께 보는 판타지 애니메이션 영화. 하이스트",
			Instant.now());

	@Test
	void correctsAMisspelledNameAcrossItsWords() {
		assertThat(QueryCorrector.correct("드늬 뷜베브", SNAPSHOT))
			.contains(new QueryCorrection("드니 빌뇌브", "드늬 뷜베브", "드니 빌뇌브"));
		assertThat(QueryCorrector.correct("크리스토퍼 놀랜 영화", SNAPSHOT))
			.contains(new QueryCorrection("크리스토퍼 놀런 영화", "크리스토퍼 놀랜", "크리스토퍼 놀런"));
		assertThat(QueryCorrector.correct("인셉숀", SNAPSHOT)).map(QueryCorrection::query).contains("인셉션");
		// The one-word window is the closer match, so the modifier "2" stays in the query.
		assertThat(QueryCorrector.correct("인셉숀 2", SNAPSHOT))
			.contains(new QueryCorrection("인셉션 2", "인셉숀", "인셉션"));
	}

	@Test
	void leavesExactNamesAndKnownWordsAlone() {
		assertThat(QueryCorrector.correct("드니 빌뇌브", SNAPSHOT)).isEmpty();
		// "아이와" is 아이 + the particle 와, found in the documents, so it is not turned into 아이유.
		assertThat(QueryCorrector.correct("아이와 함께 보는 판타지 애니메이션", SNAPSHOT)).isEmpty();
		assertThat(QueryCorrector.correct("하이스트", SNAPSHOT)).isEmpty();
	}

	@Test
	void ambiguousCandidatesAreNotGuessed() {
		assertThat(QueryCorrector.correct("박서즌", SNAPSHOT)).isEmpty();
	}

	@Test
	void vowelSwapsCostLessThanConsonantSwaps() {
		assertThat(QueryCorrector.similarity(QueryCorrector.jamo("드늬"), QueryCorrector.jamo("드니")))
			.isGreaterThan(QueryCorrector.similarity(QueryCorrector.jamo("드늬"), QueryCorrector.jamo("드긔")));
	}

}
