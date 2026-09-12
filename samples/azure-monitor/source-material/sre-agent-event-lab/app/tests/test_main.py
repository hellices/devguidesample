import importlib
import json
import logging
import time

import pytest
from azure.core.exceptions import HttpResponseError
from fastapi.testclient import TestClient


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://example.blob.core.windows.net")
    module = importlib.import_module("main")
    return importlib.reload(module)


@pytest.fixture
def client(app_module):
    return TestClient(app_module.app)


def test_healthz_reports_service_status(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "sre-event-lab"}


def test_orders_normal(client, monkeypatch):
    monkeypatch.setenv("FAILURE_MODE", "none")
    monkeypatch.setenv("ORDER_DELAY_MS", "0")

    response = client.get("/api/orders")

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_orders_http500(client, monkeypatch):
    monkeypatch.setenv("FAILURE_MODE", "http500")
    monkeypatch.setenv("ORDER_DELAY_MS", "0")

    response = client.get("/api/orders")

    assert response.status_code == 500
    assert response.json()["detail"] == "Injected order processing failure"


def test_orders_delay(client, monkeypatch):
    monkeypatch.setenv("FAILURE_MODE", "none")
    monkeypatch.setenv("ORDER_DELAY_MS", "50")

    started = time.perf_counter()
    response = client.get("/api/orders")

    assert response.status_code == 200
    assert time.perf_counter() - started >= 0.045


def test_orders_reject_invalid_delay(client, monkeypatch):
    monkeypatch.setenv("FAILURE_MODE", "none")
    monkeypatch.setenv("ORDER_DELAY_MS", "-1")

    with pytest.raises(ValueError, match="non-negative integer"):
        client.get("/api/orders")


def test_documents_maps_authorization_failure_to_503(
    client, app_module, monkeypatch
):
    def denied_service():
        raise HttpResponseError(message="AuthorizationPermissionMismatch")

    monkeypatch.setattr(app_module, "list_documents", denied_service)

    response = client.get("/api/documents")

    assert response.status_code == 503
    assert response.json()["detail"] == "Blob dependency unavailable"


def test_documents_returns_blob_names(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "list_documents", lambda: ["one.json", "two.json"])

    response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.json() == {"documents": ["one.json", "two.json"]}


def test_order_log_contains_required_structured_fields(
    client, monkeypatch, caplog
):
    monkeypatch.setenv("FAILURE_MODE", "none")
    monkeypatch.setenv("ORDER_DELAY_MS", "0")
    caplog.set_level(logging.INFO)

    response = client.get(
        "/api/orders", headers={"x-correlation-id": "test-correlation"}
    )

    assert response.status_code == 200
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "sre_event_lab"
    ]
    assert records[-1]["scenario"] == "none"
    assert records[-1]["operation"] == "orders"
    assert records[-1]["status"] == 200
    assert records[-1]["elapsed_ms"] >= 0
    assert records[-1]["correlation_id"] == "test-correlation"
