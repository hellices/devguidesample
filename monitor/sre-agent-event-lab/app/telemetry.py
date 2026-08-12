import os

from azure.monitor.opentelemetry import configure_azure_monitor
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor


def configure_telemetry(app: FastAPI) -> None:
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if connection_string:
        configure_azure_monitor(
            connection_string=connection_string,
            instrumentation_options={"fastapi": {"enabled": False}},
            sampling_ratio=1.0,
        )
        FastAPIInstrumentor.instrument_app(app)
