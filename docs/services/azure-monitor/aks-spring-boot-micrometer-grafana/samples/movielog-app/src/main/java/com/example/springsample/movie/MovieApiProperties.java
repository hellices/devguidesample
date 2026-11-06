package com.example.springsample.movie;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;
import org.springframework.util.StringUtils;

/**
 * External movie data sources. Keys come from the environment ({@code TMDB_API_KEY}, {@code OMDB_API_KEY});
 * a blank key disables that source instead of failing startup.
 */
@ConfigurationProperties("app.movies")
public record MovieApiProperties(Tmdb tmdb, Omdb omdb, @DefaultValue("7d") Duration syncTtl) {

	/**
	 * @param apiKey TMDB v3 API key or v4 read access token (a token is sent as a Bearer header)
	 */
	public record Tmdb(@DefaultValue("") String apiKey,
			@DefaultValue("https://api.themoviedb.org/3") String baseUrl,
			@DefaultValue("https://image.tmdb.org/t/p") String imageBaseUrl,
			@DefaultValue("ko-KR") String language) {

		public boolean enabled() {
			return StringUtils.hasText(apiKey);
		}

		public boolean usesAccessToken() {
			return apiKey.contains(".");
		}

	}

	public record Omdb(@DefaultValue("") String apiKey, @DefaultValue("https://www.omdbapi.com") String baseUrl) {

		public boolean enabled() {
			return StringUtils.hasText(apiKey);
		}

	}

}
