package com.example.springsample.discover;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Caps on semantic searches, which call Azure OpenAI anonymously. Zero or less disables a cap.
 *
 * @param perClientPerMinute searches one client address may run per minute
 * @param totalPerMinute searches all clients together may run per minute
 */
@ConfigurationProperties("app.discover.rate-limit")
public record DiscoverRateLimitProperties(int perClientPerMinute, int totalPerMinute) {
}
