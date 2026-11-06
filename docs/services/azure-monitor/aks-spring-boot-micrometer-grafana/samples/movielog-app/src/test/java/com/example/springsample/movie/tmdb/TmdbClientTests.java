package com.example.springsample.movie.tmdb;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.hamcrest.Matchers.startsWith;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.queryParam;
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

class TmdbClientTests {

	private static final String BASE = "https://tmdb.test/3";

	private MockRestServiceServer server;

	private TmdbClient client(String apiKey) {
		RestClient.Builder builder = RestClient.builder();
		server = MockRestServiceServer.bindTo(builder).build();
		var properties = new MovieApiProperties(
				new MovieApiProperties.Tmdb(apiKey, BASE, "https://img.test/t/p", "ko-KR"),
				new MovieApiProperties.Omdb("", "https://omdb.test"), Duration.ofDays(7));
		return new TmdbClient(builder, properties);
	}

	@Test
	void searchesWithApiKeyAndKoreanLanguage() {
		TmdbClient client = client("v3key");
		server.expect(requestTo(startsWith(BASE + "/search/movie")))
			.andExpect(queryParam("query", "%EA%B8%B0%EC%83%9D%EC%B6%A9"))
			.andExpect(queryParam("page", "2"))
			.andExpect(queryParam("language", "ko-KR"))
			.andExpect(queryParam("api_key", "v3key"))
			.andRespond(withSuccess("""
					{"page":2,"total_pages":3,"total_results":45,"results":[
					  {"id":496243,"title":"기생충","original_title":"기생충","release_date":"2019-05-30",
					   "poster_path":"/abc.jpg","overview":"줄거리","popularity":99.1}]}""",
					MediaType.APPLICATION_JSON));

		TmdbDtos.SearchPage page = client.search("기생충", 2);

		assertThat(page.totalPages()).isEqualTo(3);
		assertThat(page.results()).singleElement().satisfies(item -> {
			assertThat(item.id()).isEqualTo(496243);
			assertThat(item.posterPath()).isEqualTo("/abc.jpg");
			assertThat(item.releaseDate()).isEqualTo("2019-05-30");
		});
		server.verify();
	}

	@Test
	void sendsReadAccessTokenAsBearerHeader() {
		TmdbClient client = client("header.payload.signature");
		server.expect(requestTo(startsWith(BASE + "/movie/27205")))
			.andExpect(header(HttpHeaders.AUTHORIZATION, "Bearer header.payload.signature"))
			.andRespond(withSuccess("""
					{"id":27205,"title":"인셉션","original_title":"Inception","release_date":"2010-07-15",
					 "poster_path":"/p.jpg","overview":"꿈","runtime":148,"imdb_id":"tt1375666",
					 "genres":[{"id":28,"name":"액션"}]}""", MediaType.APPLICATION_JSON));

		TmdbDtos.MovieDetails details = client.details(27205).orElseThrow();

		assertThat(details.imdbId()).isEqualTo("tt1375666");
		assertThat(details.genres()).extracting(TmdbDtos.Genre::name).containsExactly("액션");
		server.verify();
	}

	@Test
	void unknownMovieIsEmpty() {
		TmdbClient client = client("v3key");
		server.expect(requestTo(startsWith(BASE + "/movie/1"))).andRespond(withResourceNotFound());

		assertThat(client.details(1)).isEmpty();
		server.verify();
	}

	@Test
	void serverErrorsAndMissingKeyAreReportedAsUnavailable() {
		TmdbClient client = client("v3key");
		server.expect(requestTo(startsWith(BASE + "/search/movie"))).andRespond(withServerError());

		assertThatThrownBy(() -> client.search("x", 1)).isInstanceOf(MovieApiUnavailableException.class);
		server.verify();
		assertThatThrownBy(() -> client("").search("x", 1)).isInstanceOf(MovieApiUnavailableException.class);
		assertThat(client("").isEnabled()).isFalse();
	}

	@Test
	void parsesBlankAndInvalidDatesAsNull() {
		assertThat(TmdbDtos.parseDate("")).isNull();
		assertThat(TmdbDtos.parseDate("2019")).isNull();
		assertThat(TmdbDtos.parseDate("2019-05-30")).hasYear(2019);
	}

}
