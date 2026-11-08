package com.example.springsample.metrics;

import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * @param scrapeAllowedIps addresses or CIDR ranges allowed to read {@code /actuator/prometheus}
 * (for example the Prometheus server or the cluster network); everything else is rejected
 */
@ConfigurationProperties("app.metrics")
public record MetricsProperties(@DefaultValue({ "127.0.0.1", "::1" }) List<String> scrapeAllowedIps) {
}
