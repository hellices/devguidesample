package io.opentelemetry.javaagent.instrumentation.micrometer.ai;

import org.springframework.boot.autoconfigure.AutoConfigureAfter;
import org.springframework.boot.autoconfigure.AutoConfigureBefore;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@AutoConfigureBefore(name =
        "org.springframework.boot.micrometer.metrics.autoconfigure.CompositeMeterRegistryAutoConfiguration")
@AutoConfigureAfter(name = {
        "org.springframework.boot.micrometer.metrics.autoconfigure.MetricsAutoConfiguration",
        "org.springframework.boot.micrometer.metrics.autoconfigure.export.simple.SimpleMetricsExportAutoConfiguration"
})
public class AzureMonitorAutoConfiguration {

    @Bean
    public AzureMonitorMeterRegistry azureMonitorMeterRegistry() {
        return AzureMonitorMeterRegistry.INSTANCE;
    }
}
