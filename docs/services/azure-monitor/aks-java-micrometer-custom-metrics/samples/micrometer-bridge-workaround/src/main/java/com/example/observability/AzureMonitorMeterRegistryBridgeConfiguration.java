package com.example.observability;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Metrics;
import org.springframework.boot.autoconfigure.AutoConfigureAfter;
import org.springframework.boot.autoconfigure.AutoConfigureBefore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;

@AutoConfigureAfter(name = {
        "io.opentelemetry.javaagent.instrumentation.micrometer.ai.AzureMonitorAutoConfiguration",
        "org.springframework.boot.micrometer.metrics.autoconfigure.MetricsAutoConfiguration",
        "org.springframework.boot.micrometer.metrics.autoconfigure.export.simple.SimpleMetricsExportAutoConfiguration"
})
@AutoConfigureBefore(name =
        "org.springframework.boot.micrometer.metrics.autoconfigure.CompositeMeterRegistryAutoConfiguration")
@ConditionalOnProperty(
        name = "management.application-insights.micrometer-bridge.enabled",
        havingValue = "true")
public class AzureMonitorMeterRegistryBridgeConfiguration {

    private static final String AZURE_MONITOR_REGISTRY =
            "io.opentelemetry.javaagent.instrumentation.micrometer.ai.AzureMonitorMeterRegistry";

    @Bean
    @ConditionalOnMissingBean(name = "azureMonitorMeterRegistry")
    MeterRegistry azureMonitorMeterRegistry() {
        return Metrics.globalRegistry.getRegistries().stream()
                .filter(registry -> registry.getClass().getName().equals(AZURE_MONITOR_REGISTRY))
                .findFirst()
                .orElseThrow(() -> new IllegalStateException(
                        "Application Insights AzureMonitorMeterRegistry is unavailable"));
    }
}
