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
					  {"name": "일곱", "order": 6}, {"name": "둘", "order": 1}, {"name": "하나", "order": 0},
					  {"name": "셋", "order": 2}, {"name": "넷", "order": 3}, {"name": "다섯", "order": 4},
					  {"name": "여섯", "order": 5}],
					 "crew": [{"name": "드니 빌뇌브", "job": "Director"}, {"name": "작가", "job": "Screenplay"},
					  {"name": "드니 빌뇌브", "job": "Director"}]}""", MediaType.APPLICATION_JSON));

		TmdbCreditsClient.Credits credits = client.credits(693134);

		assertThat(credits.directors()).containsExactly("드니 빌뇌브");
		assertThat(credits.actors()).containsExactly("하나", "둘", "셋", "넷", "다섯", "여섯");
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
