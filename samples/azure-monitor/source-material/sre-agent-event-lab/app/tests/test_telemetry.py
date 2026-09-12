from fastapi import FastAPI

import telemetry


def test_configure_telemetry_instruments_fastapi_app(monkeypatch):
    app = FastAPI()
    azure_monitor_calls = []
    instrumented_apps = []
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=test-key",
    )
    monkeypatch.setattr(
        telemetry,
        "configure_azure_monitor",
        lambda **kwargs: azure_monitor_calls.append(kwargs),
    )
    monkeypatch.setattr(
        telemetry.FastAPIInstrumentor,
        "instrument_app",
        lambda candidate: instrumented_apps.append(candidate),
    )

    telemetry.configure_telemetry(app)

    assert azure_monitor_calls == [
        {
            "connection_string": (
                "InstrumentationKey=test-key"
            ),
            "instrumentation_options": {"fastapi": {"enabled": False}},
            "sampling_ratio": 1.0,
        }
    ]
    assert instrumented_apps == [app]


def test_configure_telemetry_skips_when_connection_string_is_absent(monkeypatch):
    app = FastAPI()
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setattr(
        telemetry,
        "configure_azure_monitor",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError(kwargs)),
    )

    telemetry.configure_telemetry(app)
