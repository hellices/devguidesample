package com.example.observability;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Metrics;
import io.opentelemetry.javaagent.instrumentation.micrometer.ai.AzureMonitorAutoConfiguration;
import io.opentelemetry.javaagent.instrumentation.micrometer.ai.AzureMonitorMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.micrometer.metrics.autoconfigure.CompositeMeterRegistryAutoConfiguration;
import org.springframework.boot.micrometer.metrics.autoconfigure.MetricsAutoConfiguration;
import org.springframework.boot.micrometer.metrics.autoconfigure.export.simple.SimpleMetricsExportAutoConfiguration;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;

class AzureMonitorMeterRegistryBridgeConfigurationTest {

    @Test
    void exposesAgentRegistryAsSpringMeterRegistry() {
        AzureMonitorMeterRegistry agentRegistry = new AzureMonitorMeterRegistry();
        Metrics.addRegistry(agentRegistry);
        try {
            contextRunner(false).run(context -> {
                assertThat(context).hasNotFailed();
                MeterRegistry registry = context.getBean("azureMonitorMeterRegistry",
                        MeterRegistry.class);

                registry.counter("bridge.test", "source", "spring").increment();

                assertThat(agentRegistry.get("bridge.test")
                        .tag("source", "spring").counter().count()).isEqualTo(1);
            });
        } finally {
            Metrics.removeRegistry(agentRegistry);
            agentRegistry.close();
        }
    }

    @Test
    void failsWhenEnabledWithoutAgentRegistry() {
        contextRunner(false).run(context -> {
            assertThat(context).hasFailed();
            assertThat(context.getStartupFailure())
                    .hasRootCauseInstanceOf(IllegalStateException.class)
                    .hasRootCauseMessage(
                            "Application Insights AzureMonitorMeterRegistry is unavailable");
        });
    }

    @Test
    void disabledBridgeLetsFutureAgentAutoConfigurationTakeOver() {
        AzureMonitorMeterRegistry agentRegistry = AzureMonitorMeterRegistry.INSTANCE;
        Metrics.addRegistry(agentRegistry);
        try {
            contextRunner(true)
                    .withPropertyValues(
                            "management.application-insights.micrometer-bridge.enabled=false")
                    .run(context -> {
                        assertThat(context).hasNotFailed();
                        assertThat(context.getBeanNamesForType(AzureMonitorMeterRegistry.class))
                                .containsExactly("azureMonitorMeterRegistry");
                    });
        } finally {
            Metrics.removeRegistry(agentRegistry);
            agentRegistry.clear();
        }
    }

    private ApplicationContextRunner contextRunner(boolean includeAgentAutoConfiguration) {
        Class<?>[] configurations = includeAgentAutoConfiguration
                ? new Class<?>[]{
                        MetricsAutoConfiguration.class,
                        SimpleMetricsExportAutoConfiguration.class,
                        AzureMonitorAutoConfiguration.class,
                        AzureMonitorMeterRegistryBridgeConfiguration.class,
                        CompositeMeterRegistryAutoConfiguration.class
                }
                : new Class<?>[]{
                        MetricsAutoConfiguration.class,
                        SimpleMetricsExportAutoConfiguration.class,
                        AzureMonitorMeterRegistryBridgeConfiguration.class,
                        CompositeMeterRegistryAutoConfiguration.class
                };

        return new ApplicationContextRunner()
                .withConfiguration(AutoConfigurations.of(configurations))
                .withPropertyValues(
                        "management.application-insights.micrometer-bridge.enabled=true");
    }
}
