package com.example.springsample.movie.tmdb;

import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import com.example.springsample.movie.MovieApiProperties;
import com.example.springsample.movie.MovieApiUnavailableException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/** Movie search and details from The Movie Database (https://developer.themoviedb.org). */
@Component
public class TmdbClient {

	private final MovieApiProperties.Tmdb properties;

	private final RestClient restClient;

	public TmdbClient(RestClient.Builder builder, MovieApiProperties properties) {
		this.properties = properties.tmdb();
		RestClient.Builder configured = builder.clone().baseUrl(this.properties.baseUrl());
		if (this.properties.enabled() && this.properties.usesAccessToken()) {
			configured.defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + this.properties.apiKey());
		}
		this.restClient = configured.build();
	}

	public boolean isEnabled() {
		return properties.enabled();
	}

	public TmdbDtos.SearchPage search(String query, int page) {
		ensureEnabled();
		try {
			TmdbDtos.SearchPage result = restClient.get()
				.uri(template("/search/movie?query={query}&page={page}&include_adult=false"),
						variables(Map.of("query", query, "page", page)))
				.retrieve()
				.body(TmdbDtos.SearchPage.class);
			if (result == null) {
				throw new MovieApiUnavailableException("Empty TMDB search response");
			}
			return result;
		}
		catch (RestClientException ex) {
			throw new MovieApiUnavailableException("TMDB search failed", ex);
		}
	}

	public Optional<TmdbDtos.MovieDetails> details(long tmdbId) {
		ensureEnabled();
		try {
			TmdbDtos.MovieDetails details = restClient.get()
				.uri(template("/movie/{id}"), variables(Map.of("id", tmdbId)))
				.retrieve()
				.body(TmdbDtos.MovieDetails.class);
			if (details == null) {
				// Only a 404 means "no such movie"; an empty success body is an upstream fault.
				throw new MovieApiUnavailableException("Empty TMDB details response");
			}
			return Optional.of(details);
		}
		catch (HttpClientErrorException ex) {
			if (ex.getStatusCode() == HttpStatus.NOT_FOUND) {
				return Optional.empty();
			}
			throw new MovieApiUnavailableException("TMDB details failed", ex);
		}
		catch (RestClientException ex) {
			throw new MovieApiUnavailableException("TMDB details failed", ex);
		}
	}

	/**
	 * Requests use URI templates so the {@code uri} tag of {@code http.client.requests} names the operation
	 * (for example {@code /movie/{id}}) without ids, search terms or the API key.
	 */
	private String template(String pathAndQuery) {
		String separator = pathAndQuery.contains("?") ? "&" : "?";
		String template = pathAndQuery + separator + "language={language}";
		return properties.usesAccessToken() ? template : template + "&api_key={apiKey}";
	}

	private Map<String, Object> variables(Map<String, Object> values) {
		Map<String, Object> all = new HashMap<>(values);
		all.put("language", properties.language());
		all.put("apiKey", properties.apiKey());
		return all;
	}

	private void ensureEnabled() {
		if (!properties.enabled()) {
			throw new MovieApiUnavailableException("TMDB API key is not configured (TMDB_API_KEY)");
		}
	}

}
