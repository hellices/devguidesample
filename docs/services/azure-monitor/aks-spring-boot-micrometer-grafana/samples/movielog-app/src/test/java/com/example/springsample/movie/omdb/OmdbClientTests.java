package com.example.springsample.movie.omdb;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.startsWith;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.queryParam;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import java.time.Duration;

import com.example.springsample.movie.MovieApiProperties;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class OmdbClientTests {

	private MockRestServiceServer server;

	private OmdbClient client(String apiKey) {
		RestClient.Builder builder = RestClient.builder();
		server = MockRestServiceServer.bindTo(builder).build();
		var properties = new MovieApiProperties(
				new MovieApiProperties.Tmdb("", "https://tmdb.test/3", "https://img.test/t/p", "ko-KR"),
				new MovieApiProperties.Omdb(apiKey, "https://omdb.test"), Duration.ofDays(7));
		return new OmdbClient(builder, properties);
	}

	@Test
	void readsRottenTomatoesImdbAndMetacritic() {
		OmdbClient client = client("omdbkey");
		server.expect(requestTo(startsWith("https://omdb.test/")))
			.andExpect(queryParam("i", "tt6751668"))
			.andExpect(queryParam("apikey", "omdbkey"))
			.andRespond(withSuccess("""
					{"Title":"Parasite","Ratings":[
					  {"Source":"Internet Movie Database","Value":"8.5/10"},
					  {"Source":"Rotten Tomatoes","Value":"99%"},
					  {"Source":"Metacritic","Value":"97/100"}],
					 "Metascore":"97","imdbRating":"8.5","Response":"True"}""", MediaType.APPLICATION_JSON));

		assertThat(client.ratings("tt6751668")).contains(new ExternalRatings(99, 8.5, 97));
	}

	@Test
	void missingValuesBecomeNull() {
		OmdbClient client = client("omdbkey");
		server.expect(requestTo(startsWith("https://omdb.test/")))
			.andExpect(queryParam("i", "tt0000001"))
			.andRespond(withSuccess("""
					{"Ratings":[],"Metascore":"N/A","imdbRating":"N/A","Response":"True"}""",
					MediaType.APPLICATION_JSON));

		assertThat(client.ratings("tt0000001")).contains(new ExternalRatings(null, null, null));
	}

	@Test
	void ratingWithoutValueIsIgnored() {
		OmdbClient client = client("omdbkey");
		server.expect(requestTo(startsWith("https://omdb.test/")))
			.andExpect(queryParam("i", "tt0000002"))
			.andRespond(withSuccess("""
					{"Ratings":[null,{"Source":"Rotten Tomatoes"},{"Source":"Rotten Tomatoes","Value":null}],
					 "Metascore":"70","imdbRating":"7.0","Response":"True"}""", MediaType.APPLICATION_JSON));

		assertThat(client.ratings("tt0000002")).contains(new ExternalRatings(null, 7.0, 70));
		server.verify();
	}

	@Test
	void notFoundErrorsAndMissingKeyGiveNoRatings() {
		OmdbClient client = client("omdbkey");
		server.expect(requestTo(startsWith("https://omdb.test/")))
			.andExpect(queryParam("i", "tt0"))
			.andRespond(withSuccess("{\"Response\":\"False\",\"Error\":\"Incorrect IMDb ID.\"}",
					MediaType.APPLICATION_JSON));
		server.expect(requestTo(startsWith("https://omdb.test/"))).andExpect(queryParam("i", "tt0"))
			.andRespond(withServerError());

		assertThat(client.ratings("tt0")).isEmpty();
		assertThat(client.ratings("tt0")).isEmpty();
		server.verify();
		assertThat(client("").ratings("tt0")).isEmpty();
	}

}
