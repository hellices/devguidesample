package com.example.springsample.discover;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.BDDMockito.willAnswer;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Consumer;

import com.example.springsample.discover.CatalogIndexRepository.PendingMovie;
import com.example.springsample.discover.TmdbCreditsClient.Credit;
import com.example.springsample.discover.TmdbCreditsClient.Credits;
import com.example.springsample.movie.MovieApiUnavailableException;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.transaction.support.TransactionOperations;

class CatalogIndexerTests {

	private static final PendingMovie DUNE_2 = new PendingMovie(693134, "듄: 파트 2", "Dune: Part Two", 2024,
			"SF, 모험", "폴은 챠니와 프레멘과 함께 복수를 준비한다.");

	private static final PendingMovie UNKNOWN = new PendingMovie(1, "제목", "제목", null, null, null);

	private static final Credits DUNE_2_CREDITS = new Credits(List.of(new Credit(137427, "드니 빌뇌브")),
			List.of(new Credit(1190668, "티모시 샬라메"), new Credit(505710, "젠데이아")));

	private final CatalogIndexRepository repository = mock();

	private final EmbeddingClient embeddings = mock();

	private final TmdbCreditsClient tmdb = mock();

	private final QueryCorrector corrector = mock();

	private final MovieGraphSync graphSync = mock();

	private final CatalogIndexer indexer = new CatalogIndexer(repository, embeddings, tmdb, corrector,
			provider(graphSync), TransactionOperations.withoutTransaction(), 20);

	@SuppressWarnings("unchecked")
	private static ObjectProvider<MovieGraphSync> provider(MovieGraphSync graphSync) {
		ObjectProvider<MovieGraphSync> provider = mock();
		willAnswer(call -> {
			((Consumer<MovieGraphSync>) call.getArgument(0)).accept(graphSync);
			return null;
		}).given(provider).ifAvailable(any());
		return provider;
	}

	@Test
	void documentFollowsTheCatalogLayoutAndSkipsMissingParts() {
		assertThat(CatalogIndexer.document(DUNE_2, DUNE_2_CREDITS)).isEqualTo("""
				제목: 듄: 파트 2
				원제: Dune: Part Two
				개봉: 2024
				장르: SF, 모험
				감독: 드니 빌뇌브
				출연: 티모시 샬라메, 젠데이아
				줄거리: 폴은 챠니와 프레멘과 함께 복수를 준비한다.""");
		assertThat(CatalogIndexer.document(UNKNOWN, Credits.NONE)).isEqualTo("제목: 제목");
	}

	@Test
	void storesDocumentCreditsAndGenresForEachMovieThenAppliesTheGraphQueue() {
		given(embeddings.isEnabled()).willReturn(true);
		given(tmdb.isEnabled()).willReturn(true);
		given(tmdb.credits(693134)).willReturn(DUNE_2_CREDITS);
		given(tmdb.credits(1)).willReturn(Credits.NONE);
		given(tmdb.wikidataId(137427)).willReturn(Optional.of("Q548823"));
		given(repository.tryLock()).willReturn(true);
		given(repository.pending(1)).willReturn(List.of(DUNE_2), List.of(UNKNOWN), List.of());
		float[] vector = { 0.1f, 0.2f };
		given(embeddings.embed(anyString())).willReturn(vector);

		assertThat(indexer.indexPending()).containsExactly(693134L, 1L);
		InOrder order = inOrder(repository);
		order.verify(repository).insert(693134L, CatalogIndexer.document(DUNE_2, DUNE_2_CREDITS), vector);
		order.verify(repository).saveCredits(693134L, DUNE_2_CREDITS, Map.of(137427L, "Q548823"));
		order.verify(repository).saveGenres(693134L, "SF, 모험");
		order.verify(repository).insert(1L, "제목: 제목", vector);
		verify(corrector).refresh();
		verify(graphSync).processQueue();
	}

	@Test
	void anotherPodHoldingTheLockMakesTheRunANoOp() {
		given(embeddings.isEnabled()).willReturn(true);
		given(repository.tryLock()).willReturn(false);

		assertThat(indexer.indexPending()).isEmpty();
		verify(repository, never()).pending(1);
		verify(embeddings, never()).embed(anyString());
		verify(corrector, never()).refresh();
		verify(graphSync, never()).processQueue();
	}

	@Test
	void stopsAtTheFirstEmbeddingFailureAndKeepsEarlierMovies() {
		given(embeddings.isEnabled()).willReturn(true);
		given(repository.tryLock()).willReturn(true);
		given(repository.pending(1)).willReturn(List.of(DUNE_2), List.of(UNKNOWN));
		given(embeddings.embed(CatalogIndexer.document(DUNE_2, Credits.NONE))).willReturn(new float[] { 1f });
		given(embeddings.embed("제목: 제목")).willThrow(new EmbeddingUnavailableException("down", null));

		assertThat(indexer.indexPending()).containsExactly(693134L);
		verify(repository, never()).insert(eq(1L), anyString(), any());
		verify(repository, never()).saveCredits(eq(1L), any(), any());
	}

	@Test
	void aTmdbFailureStopsTheRunSoTheMovieIsIndexedLaterWithCredits() {
		given(embeddings.isEnabled()).willReturn(true);
		given(tmdb.isEnabled()).willReturn(true);
		given(repository.tryLock()).willReturn(true);
		given(repository.pending(1)).willReturn(List.of(DUNE_2));
		given(tmdb.credits(693134)).willThrow(new MovieApiUnavailableException("TMDB down"));

		assertThat(indexer.indexPending()).isEmpty();
		verify(embeddings, never()).embed(anyString());
		verify(repository, never()).insert(anyLong(), anyString(), any());
		verify(repository, never()).saveCredits(anyLong(), any(), any());
	}

	@Test
	void doesNothingWithoutAnEmbeddingEndpoint() {
		assertThat(indexer.indexPending()).isEmpty();
		verify(repository, never()).tryLock();
	}

}
