package com.example.springsample.discover;

import java.util.Comparator;
import java.util.List;
import java.util.Map;

import com.example.springsample.movie.MovieApiProperties;
import com.example.springsample.movie.MovieApiUnavailableException;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.jspecify.annotations.Nullable;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * Directors and leading cast of a movie from TMDB, for the embedded document of movies imported after the catalog
 * load. Uses the same TMDB key and language as the movie pages; with ko-KR, names come back in Korean where TMDB
 * has them, like the Wikidata labels of the catalog.
 */
@Component
class TmdbCreditsClient {

	static final int MAX_ACTORS = 6;

	private final MovieApiProperties.Tmdb properties;

	private final RestClient rest;

	TmdbCreditsClient(RestClient.Builder builder, MovieApiProperties properties) {
		this.properties = properties.tmdb();
		RestClient.Builder configured = builder.clone().baseUrl(this.properties.baseUrl());
		if (this.properties.enabled() && this.properties.usesAccessToken()) {
			configured.defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + this.properties.apiKey());
		}
		this.rest = configured.build();
	}

	boolean isEnabled() {
		return properties.enabled();
	}

	/** Empty credits when TMDB does not know the movie; an exception when TMDB fails. */
	Credits credits(long tmdbId) {
		String uri = "/movie/{id}/credits?language={language}"
				+ (properties.usesAccessToken() ? "" : "&api_key={apiKey}");
		try {
			Response response = rest.get()
				.uri(uri, Map.of("id", tmdbId, "language", properties.language(), "apiKey", properties.apiKey()))
				.retrieve()
				.body(Response.class);
			if (response == null) {
				throw new MovieApiUnavailableException("Empty TMDB credits response");
			}
			List<String> directors = (response.crew() == null) ? List.of()
					: response.crew().stream().filter(c -> "Director".equals(c.job())).map(Person::name).distinct().toList();
			List<String> actors = (response.cast() == null) ? List.of()
					: response.cast().stream()
						.sorted(Comparator.comparingInt(c -> (c.order() == null) ? Integer.MAX_VALUE : c.order()))
						.map(Person::name)
						.limit(MAX_ACTORS)
						.toList();
			return new Credits(directors, actors);
		}
		catch (HttpClientErrorException ex) {
			if (ex.getStatusCode() == HttpStatus.NOT_FOUND) {
				return Credits.NONE;
			}
			throw new MovieApiUnavailableException("TMDB credits failed", ex);
		}
		catch (RestClientException ex) {
			throw new MovieApiUnavailableException("TMDB credits failed", ex);
		}
	}

	record Credits(List<String> directors, List<String> actors) {

		static final Credits NONE = new Credits(List.of(), List.of());

	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	record Response(@Nullable List<Person> cast, @Nullable List<Person> crew) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	record Person(String name, @Nullable String job, @Nullable Integer order) {
	}

}
