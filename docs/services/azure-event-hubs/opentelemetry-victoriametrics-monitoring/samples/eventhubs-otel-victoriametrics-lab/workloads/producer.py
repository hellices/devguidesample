import asyncio
import json
import logging
import os
import signal
import time
from collections.abc import Iterable

from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient
from azure.identity.aio import DefaultAzureCredential


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("eventhubs-producer")


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def new_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(
        managed_identity_client_id=os.getenv("AZURE_CLIENT_ID") or None,
    )


def make_payload(sequence: int, payload_bytes: int) -> str:
    body = {
        "sequence": sequence,
        "sent_at_unix": time.time(),
        "source": "eventhubs-observability-lab",
    }
    encoded = json.dumps(body, separators=(",", ":"))
    if len(encoded) < payload_bytes:
        body["padding"] = "x" * (payload_bytes - len(encoded))
    return json.dumps(body, separators=(",", ":"))


async def send_payloads(
    producer: EventHubProducerClient,
    payloads: Iterable[str],
) -> int:
    batch = await producer.create_batch()
    count = 0
    batch_count = 0

    for payload in payloads:
        event = EventData(payload)
        try:
            batch.add(event)
        except ValueError:
            if batch_count == 0:
                raise RuntimeError("one event exceeds the Event Hubs batch limit")
            await producer.send_batch(batch)
            batch = await producer.create_batch()
            batch.add(event)
            batch_count = 0
        batch_count += 1
        count += 1

    if batch_count:
        await producer.send_batch(batch)
    return count


async def run() -> None:
    namespace = required("EVENT_HUB_NAMESPACE")
    event_hub = required("EVENT_HUB_NAME")
    rate = int(os.getenv("EVENTS_PER_SECOND", "100"))
    payload_bytes = int(os.getenv("PAYLOAD_BYTES", "1024"))
    if rate < 1 or payload_bytes < 128:
        raise ValueError("EVENTS_PER_SECOND must be positive and PAYLOAD_BYTES >= 128")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    credential = new_credential()
    producer = EventHubProducerClient(
        fully_qualified_namespace=namespace,
        eventhub_name=event_hub,
        credential=credential,
    )

    sequence = 0
    sent = 0
    last_log = time.monotonic()
    try:
        async with credential, producer:
            while not stop.is_set():
                started = time.monotonic()
                payloads = [
                    make_payload(sequence + offset, payload_bytes)
                    for offset in range(rate)
                ]
                sent += await send_payloads(producer, payloads)
                sequence += rate

                now = time.monotonic()
                if now - last_log >= 10:
                    LOGGER.info("sent_total=%d target_events_per_second=%d", sent, rate)
                    last_log = now
                try:
                    await asyncio.wait_for(stop.wait(), timeout=max(0.0, 1 - (now - started)))
                except TimeoutError:
                    pass
    finally:
        LOGGER.info("producer_stopped sent_total=%d", sent)


if __name__ == "__main__":
    asyncio.run(run())
