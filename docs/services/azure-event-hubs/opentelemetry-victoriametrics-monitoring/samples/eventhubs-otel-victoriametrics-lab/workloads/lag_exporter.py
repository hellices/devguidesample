import asyncio
import logging
import os
import signal

from azure.eventhub.aio import EventHubConsumerClient
from azure.eventhub.extensions.checkpointstoreblobaio import BlobCheckpointStore
from azure.identity.aio import DefaultAzureCredential
from prometheus_client import Gauge, start_http_server

from lag import compute_lag


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("eventhubs-lag-exporter")
LABELS = ("namespace", "eventhub", "consumer_group", "partition")

LAG = Gauge(
    "eventhubs_consumer_lag_messages",
    "Outstanding events after the last workload checkpoint.",
    LABELS,
)
CHECKPOINT_PRESENT = Gauge(
    "eventhubs_checkpoint_present",
    "Whether a workload checkpoint exists for the partition.",
    LABELS,
)
PARTITION_EMPTY = Gauge(
    "eventhubs_partition_empty",
    "Whether Event Hubs reports no enqueued event for the partition.",
    LABELS,
)
INVALID_ORDER = Gauge(
    "eventhubs_lag_invalid_order",
    "Whether the checkpoint sequence is ahead of the observed last sequence.",
    LABELS,
)
COLLECTION_SUCCESS = Gauge(
    "eventhubs_lag_collection_success",
    "Whether the most recent lag collection completed successfully.",
)


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def new_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(
        managed_identity_client_id=os.getenv("AZURE_CLIENT_ID") or None,
    )


async def collect_once(
    client: EventHubConsumerClient,
    checkpoint_store: BlobCheckpointStore,
    namespace: str,
    event_hub: str,
    consumer_group: str,
) -> None:
    checkpoints = await checkpoint_store.list_checkpoints(
        fully_qualified_namespace=namespace,
        eventhub_name=event_hub,
        consumer_group=consumer_group,
    )
    checkpoint_by_partition = {
        checkpoint["partition_id"]: checkpoint.get("sequence_number")
        for checkpoint in checkpoints
    }

    for partition_id in await client.get_partition_ids():
        properties = await client.get_partition_properties(partition_id)
        last_sequence = properties.get("last_enqueued_sequence_number")
        checkpoint_sequence = checkpoint_by_partition.get(partition_id)
        result = compute_lag(last_sequence, checkpoint_sequence)
        labels = (namespace, event_hub, consumer_group, partition_id)

        CHECKPOINT_PRESENT.labels(*labels).set(int(result.checkpoint_present))
        PARTITION_EMPTY.labels(*labels).set(int(result.partition_empty))
        INVALID_ORDER.labels(*labels).set(int(result.invalid_order))
        if result.messages is None:
            try:
                LAG.remove(*labels)
            except KeyError:
                pass
        else:
            LAG.labels(*labels).set(result.messages)


async def run() -> None:
    namespace = required("EVENT_HUB_NAMESPACE")
    event_hub = required("EVENT_HUB_NAME")
    consumer_group = required("EVENT_HUB_CONSUMER_GROUP")
    storage_url = required("CHECKPOINT_STORAGE_URL")
    container_name = required("CHECKPOINT_CONTAINER")
    poll_seconds = float(os.getenv("LAG_POLL_SECONDS", "15"))
    port = int(os.getenv("METRICS_PORT", "9464"))
    if poll_seconds <= 0:
        raise ValueError("LAG_POLL_SECONDS must be positive")

    start_http_server(port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    credential = new_credential()
    checkpoint_store = BlobCheckpointStore(
        blob_account_url=storage_url,
        container_name=container_name,
        credential=credential,
    )
    client = EventHubConsumerClient(
        fully_qualified_namespace=namespace,
        eventhub_name=event_hub,
        consumer_group=consumer_group,
        credential=credential,
    )

    async with credential, client:
        while not stop.is_set():
            try:
                await collect_once(
                    client,
                    checkpoint_store,
                    namespace,
                    event_hub,
                    consumer_group,
                )
                COLLECTION_SUCCESS.set(1)
            except Exception:
                COLLECTION_SUCCESS.set(0)
                LOGGER.exception("lag_collection_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass


if __name__ == "__main__":
    asyncio.run(run())
