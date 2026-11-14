package com.example.springsample.discover;

import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Pattern;

import com.example.springsample.movie.MovieApiProperties;
import com.example.springsample.movie.MovieApiUnavailableException;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
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

	private static final Pattern WIKIDATA_ID = Pattern.compile("Q[1-9][0-9]*");

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
			List<Credit> directors = (response.crew() == null) ? List.of()
					: response.crew().stream().filter(c -> "Director".equals(c.job())).map(Person::credit).distinct().toList();
			List<Credit> actors = (response.cast() == null) ? List.of()
					: response.cast().stream()
						.sorted(Comparator.comparingInt(c -> (c.order() == null) ? Integer.MAX_VALUE : c.order()))
						.map(Person::credit)
						.distinct()
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

	/** A TMDB person; {@code id} is the TMDB person id. */
	record Credit(long id, String name) {
	}

	/**
	 * The Wikidata id TMDB records for a person, so a TMDB credit joins the catalog person even when the Korean
	 * spellings differ (조쉬 브롤린 on TMDB, 조시 브롤린 on Wikidata). Empty when TMDB has none.
	 */
	Optional<String> wikidataId(long personId) {
		String uri = "/person/{id}/external_ids" + (properties.usesAccessToken() ? "" : "?api_key={apiKey}");
		try {
			ExternalIds ids = rest.get()
				.uri(uri, Map.of("id", personId, "apiKey", properties.apiKey()))
				.retrieve()
				.body(ExternalIds.class);
			return Optional.ofNullable(ids)
				.map(ExternalIds::wikidataId)
				.filter(id -> WIKIDATA_ID.matcher(id).matches());
		}
		catch (HttpClientErrorException ex) {
			if (ex.getStatusCode() == HttpStatus.NOT_FOUND) {
				return Optional.empty();
			}
			throw new MovieApiUnavailableException("TMDB external ids failed", ex);
		}
		catch (RestClientException ex) {
			throw new MovieApiUnavailableException("TMDB external ids failed", ex);
		}
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	record ExternalIds(@JsonProperty("wikidata_id") @Nullable String wikidataId) {
	}

	record Credits(List<Credit> directors, List<Credit> actors) {

		static final Credits NONE = new Credits(List.of(), List.of());

	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	record Response(@Nullable List<Person> cast, @Nullable List<Person> crew) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	record Person(long id, String name, @Nullable String job, @Nullable Integer order) {

		Credit credit() {
			return new Credit(id, name);
		}

	}

}
