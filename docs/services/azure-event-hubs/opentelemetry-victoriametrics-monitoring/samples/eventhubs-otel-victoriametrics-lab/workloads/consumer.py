import asyncio
import logging
import os
import signal
import time

from azure.eventhub.aio import EventHubConsumerClient
from azure.eventhub.extensions.checkpointstoreblobaio import BlobCheckpointStore
from azure.identity.aio import DefaultAzureCredential


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
# The Event Hubs AMQP stack logs every link state change at INFO.
logging.getLogger("azure").setLevel(os.getenv("AZURE_LOG_LEVEL", "WARNING"))
LOGGER = logging.getLogger("eventhubs-slow-consumer")


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def new_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(
        managed_identity_client_id=os.getenv("AZURE_CLIENT_ID") or None,
    )


async def run() -> None:
    namespace = required("EVENT_HUB_NAMESPACE")
    event_hub = required("EVENT_HUB_NAME")
    consumer_group = required("EVENT_HUB_CONSUMER_GROUP")
    storage_url = required("CHECKPOINT_STORAGE_URL")
    container_name = required("CHECKPOINT_CONTAINER")
    delay_seconds = float(os.getenv("PROCESSING_DELAY_SECONDS", "0.1"))
    checkpoint_every = int(os.getenv("CHECKPOINT_EVERY", "20"))
    if delay_seconds < 0 or checkpoint_every < 1:
        raise ValueError("processing delay must be non-negative and checkpoint interval positive")

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
    consumer = EventHubConsumerClient(
        fully_qualified_namespace=namespace,
        eventhub_name=event_hub,
        consumer_group=consumer_group,
        credential=credential,
        checkpoint_store=checkpoint_store,
    )

    processed_by_partition: dict[str, int] = {}
    last_log = time.monotonic()

    async def on_event(partition_context, event) -> None:
        nonlocal last_log
        if event is None:
            return
        partition_id = partition_context.partition_id
        await asyncio.sleep(delay_seconds)
        processed_by_partition[partition_id] = processed_by_partition.get(partition_id, 0) + 1
        if processed_by_partition[partition_id] % checkpoint_every == 0:
            await partition_context.update_checkpoint(event)

        now = time.monotonic()
        if now - last_log >= 10:
            LOGGER.info(
                "processed_total=%d per_partition=%s",
                sum(processed_by_partition.values()),
                processed_by_partition,
            )
            last_log = now

    async def on_error(partition_context, error: Exception) -> None:
        partition_id = partition_context.partition_id if partition_context else "processor"
        LOGGER.error("consumer_error partition=%s error=%r", partition_id, error)

    receive_task = None
    try:
        async with credential, consumer:
            receive_task = asyncio.create_task(
                consumer.receive(
                    on_event=on_event,
                    on_error=on_error,
                    starting_position="-1",
                    track_last_enqueued_event_properties=True,
                )
            )
            await stop.wait()
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
    finally:
        if receive_task and not receive_task.done():
            receive_task.cancel()
        LOGGER.info("consumer_stopped processed_total=%d", sum(processed_by_partition.values()))


if __name__ == "__main__":
    asyncio.run(run())
