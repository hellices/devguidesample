package com.example.springsample.discover;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withResourceNotFound;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import java.time.Duration;

import com.example.springsample.movie.MovieApiProperties;
import com.example.springsample.movie.MovieApiUnavailableException;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class TmdbCreditsClientTests {

	private static final String URL = "https://tmdb.test/3/movie/693134/credits?language=ko-KR";

	private MockRestServiceServer server;

	private TmdbCreditsClient client() {
		RestClient.Builder builder = RestClient.builder();
		server = MockRestServiceServer.bindTo(builder).build();
		return new TmdbCreditsClient(builder, new MovieApiProperties(
				new MovieApiProperties.Tmdb("header.payload.signature", "https://tmdb.test/3", "https://img.test", "ko-KR"),
				new MovieApiProperties.Omdb("", "https://omdb.test"), Duration.ofDays(7)));
	}

	@Test
	void returnsDirectorsAndTheFirstSixActorsInBillingOrder() {
		TmdbCreditsClient client = client();
		server.expect(requestTo(URL))
			.andExpect(header(HttpHeaders.AUTHORIZATION, "Bearer header.payload.signature"))
			.andRespond(withSuccess("""
					{"cast": [
					  {"id": 7, "name": "일곱", "order": 6}, {"id": 2, "name": "둘", "order": 1},
					  {"id": 1, "name": "하나", "order": 0}, {"id": 3, "name": "셋", "order": 2},
					  {"id": 4, "name": "넷", "order": 3}, {"id": 5, "name": "다섯", "order": 4},
					  {"id": 6, "name": "여섯", "order": 5}],
					 "crew": [{"id": 137427, "name": "드니 빌뇌브", "job": "Director"},
					  {"id": 9, "name": "작가", "job": "Screenplay"},
					  {"id": 137427, "name": "드니 빌뇌브", "job": "Director"}]}""", MediaType.APPLICATION_JSON));

		TmdbCreditsClient.Credits credits = client.credits(693134);

		assertThat(credits.directors()).containsExactly(new TmdbCreditsClient.Credit(137427, "드니 빌뇌브"));
		assertThat(credits.actors()).extracting(TmdbCreditsClient.Credit::name)
			.containsExactly("하나", "둘", "셋", "넷", "다섯", "여섯");
		assertThat(credits.actors()).extracting(TmdbCreditsClient.Credit::id).containsExactly(1L, 2L, 3L, 4L, 5L, 6L);
	}

	@Test
	void readsTheWikidataIdOfAPersonAndIgnoresMissingOrMalformedIds() {
		TmdbCreditsClient client = client();
		server.expect(requestTo("https://tmdb.test/3/person/16851/external_ids"))
			.andRespond(withSuccess("{\"id\": 16851, \"wikidata_id\": \"Q41396\"}", MediaType.APPLICATION_JSON));
		server.expect(requestTo("https://tmdb.test/3/person/1/external_ids"))
			.andRespond(withSuccess("{\"id\": 1, \"wikidata_id\": null}", MediaType.APPLICATION_JSON));
		server.expect(requestTo("https://tmdb.test/3/person/2/external_ids"))
			.andRespond(withSuccess("{\"id\": 2, \"wikidata_id\": \"Q1 OR 1=1\"}", MediaType.APPLICATION_JSON));
		server.expect(requestTo("https://tmdb.test/3/person/3/external_ids")).andRespond(withResourceNotFound());

		assertThat(client.wikidataId(16851)).contains("Q41396");
		assertThat(client.wikidataId(1)).isEmpty();
		assertThat(client.wikidataId(2)).isEmpty();
		assertThat(client.wikidataId(3)).isEmpty();
	}

	@Test
	void unknownMovieHasNoCreditsButAServerErrorFails() {
		TmdbCreditsClient client = client();
		server.expect(requestTo(URL)).andRespond(withResourceNotFound());
		assertThat(client.credits(693134)).isEqualTo(TmdbCreditsClient.Credits.NONE);

		server.reset();
		server.expect(requestTo(URL)).andRespond(withServerError());
		assertThatThrownBy(() -> client.credits(693134)).isInstanceOf(MovieApiUnavailableException.class);
	}

}
