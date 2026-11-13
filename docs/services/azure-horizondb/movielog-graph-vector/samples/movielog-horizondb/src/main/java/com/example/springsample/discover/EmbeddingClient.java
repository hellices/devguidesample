package com.example.springsample.discover;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import com.azure.core.credential.AccessToken;
import com.azure.core.credential.TokenCredential;
import com.azure.core.credential.TokenRequestContext;
import com.azure.core.exception.ClientAuthenticationException;
import com.azure.identity.DefaultAzureCredentialBuilder;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * Embeds query text with Azure OpenAI using a Microsoft Entra token (no API key). In AKS the token comes from
 * workload identity; locally from the Azure CLI login. HorizonDB's in-database {@code azure_openai} functions
 * need a subscription key for bring-your-own models, which keyless Azure OpenAI accounts cannot provide.
 */
@Component
class EmbeddingClient {

	private static final TokenRequestContext SCOPE = new TokenRequestContext()
		.addScopes("https://cognitiveservices.azure.com/.default");

	private final EmbeddingProperties properties;

	private final RestClient rest;

	private volatile TokenCredential credential;

	private volatile AccessToken token;

	EmbeddingClient(EmbeddingProperties properties, RestClient.Builder builder) {
		this.properties = properties;
		this.rest = builder.clone().baseUrl(properties.endpoint()).build();
	}

	boolean isEnabled() {
		return properties.enabled();
	}

	float[] embed(String text) {
		if (!properties.enabled()) {
			throw new EmbeddingUnavailableException("Embedding endpoint is not configured (AZURE_OPENAI_ENDPOINT)", null);
		}
		try {
			String bearer = accessToken();
			EmbeddingResponse response = rest.post()
				.uri("/openai/deployments/{deployment}/embeddings?api-version={version}", properties.deployment(),
						properties.apiVersion())
				.contentType(MediaType.APPLICATION_JSON)
				.headers(headers -> headers.setBearerAuth(bearer))
				.body(Map.of("input", text, "dimensions", properties.dimensions()))
				.retrieve()
				.body(EmbeddingResponse.class);
			if (response == null || response.data() == null || response.data().isEmpty()) {
				throw new EmbeddingUnavailableException("Empty embedding response", null);
			}
			List<Float> values = response.data().getFirst().embedding();
			float[] vector = new float[values.size()];
			for (int i = 0; i < vector.length; i++) {
				vector[i] = values.get(i);
			}
			return vector;
		}
		catch (ClientAuthenticationException ex) {
			throw new EmbeddingUnavailableException("Microsoft Entra token for Azure OpenAI is unavailable", ex);
		}
		catch (RestClientException ex) {
			throw new EmbeddingUnavailableException("Azure OpenAI embedding call failed", ex);
		}
	}

	/** Reuses the token until five minutes before it expires. */
	private String accessToken() {
		AccessToken current = token;
		if (current == null || current.getExpiresAt().isBefore(OffsetDateTime.now().plusMinutes(5))) {
			synchronized (this) {
				current = token;
				if (current == null || current.getExpiresAt().isBefore(OffsetDateTime.now().plusMinutes(5))) {
					if (credential == null) {
						credential = new DefaultAzureCredentialBuilder().build();
					}
					current = credential.getTokenSync(SCOPE);
					token = current;
				}
			}
		}
		return current.getToken();
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	record EmbeddingResponse(List<Item> data) {

		@JsonIgnoreProperties(ignoreUnknown = true)
		record Item(List<Float> embedding) {
		}

	}

}
