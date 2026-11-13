package com.example.springsample.discover;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import java.time.OffsetDateTime;
import java.util.concurrent.atomic.AtomicInteger;

import com.azure.core.credential.AccessToken;
import com.azure.core.credential.TokenCredential;
import com.azure.core.credential.TokenRequestContext;
import com.azure.identity.CredentialUnavailableException;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import reactor.core.publisher.Mono;

class EmbeddingClientTests {

	private static final String URL =
			"https://aoai.test/openai/deployments/text-embedding-3-large/embeddings?api-version=2024-10-21";

	private final AtomicInteger tokenRequests = new AtomicInteger();

	private MockRestServiceServer server;

	private EmbeddingClient client(String endpoint, TokenCredential credential) {
		RestClient.Builder builder = RestClient.builder();
		server = MockRestServiceServer.bindTo(builder).build();
		return new EmbeddingClient(new EmbeddingProperties(endpoint, null, 0, null), builder, () -> credential);
	}

	private TokenCredential token(String value) {
		return context -> {
			tokenRequests.incrementAndGet();
			return Mono.just(new AccessToken(value, OffsetDateTime.now().plusHours(1)));
		};
	}

	@Test
	void postsQueryWithBearerTokenAndDimensionsAndReusesTheToken() {
		EmbeddingClient client = client("https://aoai.test", token("entra-token"));
		for (int i = 0; i < 2; i++) {
			server.expect(requestTo(URL))
				.andExpect(method(HttpMethod.POST))
				.andExpect(header(HttpHeaders.AUTHORIZATION, "Bearer entra-token"))
				.andExpect(content().json("""
						{"input":"우주 가족","dimensions":1536}"""))
				.andRespond(withSuccess("""
						{"data":[{"embedding":[0.25,-0.5,1.0],"index":0}],"usage":{"total_tokens":3}}""",
						MediaType.APPLICATION_JSON));
		}

		assertThat(client.embed("우주 가족")).containsExactly(0.25f, -0.5f, 1.0f);
		assertThat(client.embed("우주 가족")).hasSize(3);
		assertThat(tokenRequests).hasValue(1);
		server.verify();
	}

	@Test
	void tokenFailureIsAnEmbeddingErrorWithoutCallingAzureOpenAi() {
		TokenCredential noLogin = new TokenCredential() {
			@Override
			public Mono<AccessToken> getToken(TokenRequestContext request) {
				return Mono.error(new CredentialUnavailableException("no Azure login"));
			}

			@Override
			public AccessToken getTokenSync(TokenRequestContext request) {
				throw new CredentialUnavailableException("no Azure login");
			}
		};
		EmbeddingClient client = client("https://aoai.test", noLogin);

		assertThatThrownBy(() -> client.embed("질문")).isInstanceOf(EmbeddingUnavailableException.class)
			.hasCauseInstanceOf(CredentialUnavailableException.class);
		server.verify();
	}

	@Test
	void httpErrorsAndEmptyResponsesAreEmbeddingErrors() {
		EmbeddingClient client = client("https://aoai.test", token("t"));
		server.expect(requestTo(URL)).andRespond(withServerError());
		server.expect(requestTo(URL)).andRespond(withSuccess("""
				{"data":[]}""", MediaType.APPLICATION_JSON));

		assertThatThrownBy(() -> client.embed("a")).isInstanceOf(EmbeddingUnavailableException.class);
		assertThatThrownBy(() -> client.embed("b")).isInstanceOf(EmbeddingUnavailableException.class)
			.hasMessageContaining("Empty");
		server.verify();
	}

	@Test
	void blankEndpointDisablesSearchWithoutRequests() {
		EmbeddingClient client = client(" ", token("t"));

		assertThat(client.isEnabled()).isFalse();
		assertThatThrownBy(() -> client.embed("a")).isInstanceOf(EmbeddingUnavailableException.class);
		assertThat(tokenRequests).hasValue(0);
		server.verify();
	}

}
