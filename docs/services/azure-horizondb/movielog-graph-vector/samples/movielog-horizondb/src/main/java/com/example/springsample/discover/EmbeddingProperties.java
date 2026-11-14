package com.example.springsample.discover;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Azure OpenAI embedding deployment used for query text. The catalog documents are embedded with the
 * same deployment and dimensions by {@code data/embed_catalog.py}; anything else makes the distances meaningless.
 *
 * @param endpoint Azure OpenAI endpoint, for example https://my-openai.openai.azure.com/ (blank disables search)
 * @param deployment deployment name of text-embedding-3-large
 * @param dimensions output size, equal to the {@code vector(n)} column of {@code catalog.movie_docs}
 * @param apiVersion Azure OpenAI data-plane API version
 */
@ConfigurationProperties("app.discover.embedding")
public record EmbeddingProperties(String endpoint, String deployment, int dimensions, String apiVersion) {

	public EmbeddingProperties {
		endpoint = (endpoint == null) ? "" : endpoint.strip();
		deployment = (deployment == null || deployment.isBlank()) ? "text-embedding-3-large" : deployment;
		dimensions = (dimensions <= 0) ? 1536 : dimensions;
		apiVersion = (apiVersion == null || apiVersion.isBlank()) ? "2024-10-21" : apiVersion;
	}

	public boolean enabled() {
		return !endpoint.isEmpty();
	}

}
