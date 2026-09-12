"""Azure AI Search eventual consistency reproduction script.

Runs a "upload new version → delete previous version → verify count" pipeline
under concurrent writes and reports per-cycle discrepancies.

Required environment variables:
    AZURE_AI_SEARCH_ENDPOINT
    AZURE_AI_SEARCH_API_KEY

Optional:
    AZURE_AI_SEARCH_INDEX_NAME  (default: repro-index)
    SYSTEM_NAME                 (default: test-system)
    DOC_COUNT                   (default: 35000)
    BATCH_SIZE                  (default: 512)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchableField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
)

ENDPOINT = os.environ["AZURE_AI_SEARCH_ENDPOINT"]
API_KEY = os.environ["AZURE_AI_SEARCH_API_KEY"]
INDEX_NAME = os.environ.get("AZURE_AI_SEARCH_INDEX_NAME", "repro-index")
SYSTEM_NAME = os.environ.get("SYSTEM_NAME", "test-system")
DOC_COUNT = int(os.environ.get("DOC_COUNT", "35000"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "512"))

CREDENTIAL = AzureKeyCredential(API_KEY)


@dataclass
class CycleResult:
    cycle: int
    mode: str
    uploaded: int
    count_api: int
    scanned_count: int
    leftover_old_version: int
    duration_sec: float
    errors: list[str] = field(default_factory=list)


def ensure_index() -> None:
    client = SearchIndexClient(ENDPOINT, CREDENTIAL)
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True, sortable=True),
        SimpleField(name="system_name", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="version", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
    ]
    index = SearchIndex(name=INDEX_NAME, fields=fields)
    try:
        client.get_index(INDEX_NAME)
    except Exception:
        client.create_index(index)


def make_docs(version: int) -> list[dict]:
    return [
        {
            "id": f"{SYSTEM_NAME}-{version}-{i}-{uuid.uuid4().hex[:8]}",
            "system_name": SYSTEM_NAME,
            "version": version,
            "content": f"doc {i} version {version}",
        }
        for i in range(DOC_COUNT)
    ]


def upload_batch(client: SearchClient, batch: list[dict], use_merge_or_upload: bool) -> None:
    if use_merge_or_upload:
        client.merge_or_upload_documents(documents=batch)
    else:
        client.upload_documents(documents=batch)


def upload_docs(docs: list[dict], use_merge_or_upload: bool) -> list[str]:
    errors: list[str] = []
    client = SearchClient(ENDPOINT, INDEX_NAME, CREDENTIAL)
    batches = [docs[i : i + BATCH_SIZE] for i in range(0, len(docs), BATCH_SIZE)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(upload_batch, client, b, use_merge_or_upload) for b in batches]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
    return errors


def delete_previous_version(current_version: int, use_order_by: bool) -> tuple[int, list[str]]:
    """Search for docs with version < current_version and delete them.

    Returns (deleted_count, errors).
    """
    client = SearchClient(ENDPOINT, INDEX_NAME, CREDENTIAL)
    errors: list[str] = []
    deleted = 0
    filter_expr = f"system_name eq '{SYSTEM_NAME}' and version lt {current_version}"

    order_by = ["id asc"] if use_order_by else None
    last_id = ""
    while True:
        iter_filter = filter_expr
        if use_order_by and last_id:
            iter_filter = f"{filter_expr} and id gt '{last_id}'"
        results = list(
            client.search(
                search_text="*",
                filter=iter_filter,
                order_by=order_by,
                top=1000,
                select=["id"],
            )
        )
        if not results:
            break
        ids = [r["id"] for r in results]
        try:
            client.delete_documents(documents=[{"id": i} for i in ids])
            deleted += len(ids)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        if not use_order_by:
            # Without deterministic pagination, one pass is what the original
            # pipeline does — we stop here to surface the leak.
            break
        last_id = ids[-1]
    return deleted, errors


def count_current(version: int) -> tuple[int, int]:
    """Return (count_api_value, scanned_count) for the current version."""
    client = SearchClient(ENDPOINT, INDEX_NAME, CREDENTIAL)
    filter_expr = f"system_name eq '{SYSTEM_NAME}' and version eq {version}"
    api_result = client.search(
        search_text="*", filter=filter_expr, include_total_count=True, top=0
    )
    count_api = api_result.get_count() or 0

    scanned = 0
    last_id = ""
    while True:
        f = filter_expr
        if last_id:
            f = f"{filter_expr} and id gt '{last_id}'"
        page = list(
            client.search(search_text="*", filter=f, order_by=["id asc"], top=1000, select=["id"])
        )
        if not page:
            break
        scanned += len(page)
        last_id = page[-1]["id"]
    return count_api, scanned


def leftover_old(version: int) -> int:
    client = SearchClient(ENDPOINT, INDEX_NAME, CREDENTIAL)
    filter_expr = f"system_name eq '{SYSTEM_NAME}' and version lt {version}"
    leftover = 0
    last_id = ""
    while True:
        f = filter_expr
        if last_id:
            f = f"{filter_expr} and id gt '{last_id}'"
        page = list(
            client.search(search_text="*", filter=f, order_by=["id asc"], top=1000, select=["id"])
        )
        if not page:
            break
        leftover += len(page)
        last_id = page[-1]["id"]
    return leftover


def run_cycle(
    cycle: int,
    version: int,
    mode: str,
    use_merge_or_upload: bool,
    use_order_by: bool,
    propagation_wait_sec: float = 3.0,
) -> CycleResult:
    start = time.monotonic()
    errors: list[str] = []

    docs = make_docs(version)
    errors += upload_docs(docs, use_merge_or_upload=use_merge_or_upload)

    time.sleep(propagation_wait_sec)
    _, del_errors = delete_previous_version(version, use_order_by=use_order_by)
    errors += del_errors

    time.sleep(propagation_wait_sec)
    count_api, scanned = count_current(version)
    leftover = leftover_old(version)

    return CycleResult(
        cycle=cycle,
        mode=mode,
        uploaded=len(docs),
        count_api=count_api,
        scanned_count=scanned,
        leftover_old_version=leftover,
        duration_sec=time.monotonic() - start,
        errors=errors,
    )


def main() -> None:
    ensure_index()
    results: list[CycleResult] = []
    version = 1

    for i in range(5):
        version += 1
        results.append(
            run_cycle(i + 1, version, "original", use_merge_or_upload=False, use_order_by=False)
        )

    for i in range(2):
        version += 1
        results.append(
            run_cycle(
                len(results) + 1, version, "workaround", use_merge_or_upload=True, use_order_by=True
            )
        )

    print(f"\n{'cycle':>5} {'mode':>10} {'uploaded':>9} {'count_api':>10} "
          f"{'scanned':>8} {'leftover':>9} {'sec':>6}")
    for r in results:
        print(
            f"{r.cycle:>5} {r.mode:>10} {r.uploaded:>9} {r.count_api:>10} "
            f"{r.scanned_count:>8} {r.leftover_old_version:>9} {r.duration_sec:>6.1f}"
        )

    with open("repro_results.json", "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    print("\nWrote repro_results.json")


if __name__ == "__main__":
    main()
