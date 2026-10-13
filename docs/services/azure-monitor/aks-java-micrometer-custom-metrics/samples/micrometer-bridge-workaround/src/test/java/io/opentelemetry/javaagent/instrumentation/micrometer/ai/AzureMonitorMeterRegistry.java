package io.opentelemetry.javaagent.instrumentation.micrometer.ai;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;

public final class AzureMonitorMeterRegistry extends SimpleMeterRegistry {

    public static final AzureMonitorMeterRegistry INSTANCE = new AzureMonitorMeterRegistry();
}
