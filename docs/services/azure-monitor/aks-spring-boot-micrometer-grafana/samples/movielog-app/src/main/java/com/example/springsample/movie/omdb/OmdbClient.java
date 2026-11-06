package com.example.springsample.movie.omdb;

import java.util.List;
import java.util.Objects;
import java.util.Optional;

import com.example.springsample.movie.MovieApiProperties;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * Critic ratings from OMDb (https://www.omdbapi.com), the only open source of Rotten Tomatoes scores.
 * Ratings are optional decoration: failures are logged and reported as "no ratings".
 */
@Component
public class OmdbClient {

	private static final Logger logger = LoggerFactory.getLogger(OmdbClient.class);

	private final MovieApiProperties.Omdb properties;

	private final RestClient restClient;

	public OmdbClient(RestClient.Builder builder, MovieApiProperties properties) {
		this.properties = properties.omdb();
		this.restClient = builder.clone().baseUrl(this.properties.baseUrl()).build();
	}

	public boolean isEnabled() {
		return properties.enabled();
	}

	public Optional<ExternalRatings> ratings(String imdbId) {
		if (!properties.enabled()) {
			return Optional.empty();
		}
		try {
			Response response = restClient.get()
				// A URI template keeps the IMDb id and key out of the http.client.requests tags.
				.uri("/?i={imdbId}&apikey={apiKey}", imdbId, properties.apiKey())
				.retrieve()
				.body(Response.class);
			if (response == null || !"True".equalsIgnoreCase(response.response())) {
				logger.debug("OMDb has no entry for {}: {}", imdbId, (response == null) ? null : response.error());
				return Optional.empty();
			}
			return Optional.of(response.toRatings());
		}
		catch (RestClientException ex) {
			logger.warn("OMDb ratings lookup failed for {}: {}", imdbId, ex.getMessage());
			return Optional.empty();
		}
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	record Response(@JsonProperty("Response") String response, @JsonProperty("Error") @Nullable String error,
			@JsonProperty("Ratings") @Nullable List<Rating> ratings,
			@JsonProperty("imdbRating") @Nullable String imdbRating,
			@JsonProperty("Metascore") @Nullable String metascore) {

		ExternalRatings toRatings() {
			Integer rottenTomatoes = (ratings == null) ? null : ratings.stream()
				.filter(rating -> "Rotten Tomatoes".equals(rating.source()))
				.map(rating -> (rating.value() == null) ? null : parseInt(rating.value().replace("%", "")))
				.filter(Objects::nonNull)
				.findFirst()
				.orElse(null);
			return new ExternalRatings(rottenTomatoes, parseDecimal(imdbRating), parseInt(metascore));
		}

	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	record Rating(@JsonProperty("Source") String source, @JsonProperty("Value") @Nullable String value) {
	}

	private static @Nullable Integer parseInt(@Nullable String value) {
		try {
			return (value == null) ? null : Integer.valueOf(value.strip());
		}
		catch (NumberFormatException ex) {
			return null;
		}
	}

	private static @Nullable Double parseDecimal(@Nullable String value) {
		try {
			return (value == null) ? null : Double.valueOf(value.strip());
		}
		catch (NumberFormatException ex) {
			return null;
		}
	}

}
