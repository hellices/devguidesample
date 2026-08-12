import json
import logging
import os
import time
from typing import Optional
from uuid import uuid4

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from fastapi import FastAPI, Header, HTTPException

from telemetry import configure_telemetry


configure_telemetry()

app = FastAPI(title="Azure SRE Agent Event Lab")
logger = logging.getLogger("sre_event_lab")
logger.setLevel(logging.INFO)


def _order_delay_seconds() -> float:
    raw_value = os.getenv("ORDER_DELAY_MS", "0")
    try:
        delay_ms = int(raw_value)
    except ValueError as exc:
        raise ValueError("ORDER_DELAY_MS must be a non-negative integer") from exc
    if delay_ms < 0:
        raise ValueError("ORDER_DELAY_MS must be a non-negative integer")
    return delay_ms / 1000


def _log_outcome(
    *,
    scenario: str,
    operation: str,
    status: int,
    started: float,
    correlation_id: str,
) -> None:
    logger.info(
        json.dumps(
            {
                "scenario": scenario,
                "operation": operation,
                "status": status,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "correlation_id": correlation_id,
            },
            separators=(",", ":"),
        )
    )


def list_documents() -> list[str]:
    account_url = os.environ["AZURE_STORAGE_ACCOUNT_URL"]
    credential = DefaultAzureCredential()
    service = BlobServiceClient(account_url=account_url, credential=credential)
    container = service.get_container_client("documents")
    return [blob.name for blob in container.list_blobs(results_per_page=100)]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "sre-event-lab"}


@app.get("/api/orders")
def orders(x_correlation_id: Optional[str] = Header(default=None)) -> dict[str, str]:
    started = time.perf_counter()
    scenario = os.getenv("FAILURE_MODE", "none")
    correlation_id = x_correlation_id or str(uuid4())

    if scenario == "http500":
        _log_outcome(
            scenario=scenario,
            operation="orders",
            status=500,
            started=started,
            correlation_id=correlation_id,
        )
        raise HTTPException(status_code=500, detail="Injected order processing failure")

    time.sleep(_order_delay_seconds())
    _log_outcome(
        scenario=scenario,
        operation="orders",
        status=200,
        started=started,
        correlation_id=correlation_id,
    )
    return {"status": "accepted", "correlation_id": correlation_id}


@app.get("/api/documents")
def documents(
    x_correlation_id: Optional[str] = Header(default=None),
) -> dict[str, list[str]]:
    started = time.perf_counter()
    correlation_id = x_correlation_id or str(uuid4())
    try:
        names = list_documents()
    except HttpResponseError:
        logger.exception(
            "Blob dependency authorization failed",
            extra={"correlation_id": correlation_id},
        )
        _log_outcome(
            scenario="storage-rbac",
            operation="documents",
            status=503,
            started=started,
            correlation_id=correlation_id,
        )
        raise HTTPException(status_code=503, detail="Blob dependency unavailable")

    _log_outcome(
        scenario="none",
        operation="documents",
        status=200,
        started=started,
        correlation_id=correlation_id,
    )
    return {"documents": names}
