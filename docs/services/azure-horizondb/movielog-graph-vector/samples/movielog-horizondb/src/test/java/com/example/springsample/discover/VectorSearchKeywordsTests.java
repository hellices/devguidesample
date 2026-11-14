package com.example.springsample.discover;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class VectorSearchKeywordsTests {

	@Test
	void keepsKoreanWordsOfAnyLengthAndDropsShortLatinWords() {
		assertThat(VectorSearchRepository.keywords("듄")).containsExactly("듄");
		assertThat(VectorSearchRepository.keywords("드니 빌뇌브, 드니!")).containsExactly("드니", "빌뇌브");
		assertThat(VectorSearchRepository.keywords("a shark terrorizes THE beach town"))
			.containsExactly("shark", "terrorizes", "beach", "town");
	}

	@Test
	void blankQueryHasNoKeywordsAndLongQueriesStopAtEight() {
		assertThat(VectorSearchRepository.keywords("  ...  ")).isEmpty();
		assertThat(VectorSearchRepository.keywords("가 나 다 라 마 바 사 아 자 차")).hasSize(8);
	}

}
