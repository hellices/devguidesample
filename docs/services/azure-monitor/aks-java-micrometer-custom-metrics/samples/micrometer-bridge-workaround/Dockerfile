FROM alpine:3.22

RUN wget -O /applicationinsights-agent-codeless.jar \
        https://github.com/microsoft/ApplicationInsights-Java/releases/download/3.7.9/applicationinsights-agent-3.7.9.jar \
    && echo "4ab7a442bf9defc7475d026c6b49042793ebb010c391a1db91ae07da0c04d848  /applicationinsights-agent-codeless.jar" \
        | sha256sum -c -

ENTRYPOINT ["cp", "/applicationinsights-agent-codeless.jar", "/azure-monitor-auto-instrumentation-java/applicationinsights-agent-codeless.jar"]
