# Supplies Application Insights Java 3.7.10 while the managed AKS image is older than 3.7.9.
# The checksum matches the digest GitHub publishes for the release asset.
FROM alpine:3.22

RUN wget -O /applicationinsights-agent-codeless.jar \
        https://github.com/microsoft/ApplicationInsights-Java/releases/download/3.7.10/applicationinsights-agent-3.7.10.jar \
    && echo "93a70c8f5d364c7e777f6c4d1b235dba91aef8448bd3fa94359f1d7f3e2eb0ec  /applicationinsights-agent-codeless.jar" \
        | sha256sum -c -

ENTRYPOINT ["cp", "/applicationinsights-agent-codeless.jar", "/azure-monitor-auto-instrumentation-java/applicationinsights-agent-codeless.jar"]
