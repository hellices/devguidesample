import asyncio
import sys
import types
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).parents[1]


class _Client:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FailingConsumer(_Client):
    async def receive(self, **kwargs):
        await asyncio.sleep(0)
        raise ConnectionError("link detached")


def _load_consumer(monkeypatch, consumer_cls):
    modules = {
        "azure": types.ModuleType("azure"),
        "azure.eventhub": types.ModuleType("azure.eventhub"),
        "azure.eventhub.aio": types.ModuleType("azure.eventhub.aio"),
        "azure.eventhub.extensions": types.ModuleType("azure.eventhub.extensions"),
        "azure.eventhub.extensions.checkpointstoreblobaio": types.ModuleType("checkpointstoreblobaio"),
        "azure.identity": types.ModuleType("azure.identity"),
        "azure.identity.aio": types.ModuleType("azure.identity.aio"),
    }
    modules["azure.eventhub.aio"].EventHubConsumerClient = consumer_cls
    modules["azure.eventhub.extensions.checkpointstoreblobaio"].BlobCheckpointStore = _Client
    modules["azure.identity.aio"].DefaultAzureCredential = _Client
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.syspath_prepend(str(LAB_ROOT / "workloads"))
    monkeypatch.delitem(sys.modules, "consumer", raising=False)
    import consumer

    return consumer


def test_receive_failure_exits_instead_of_idling(monkeypatch):
    for name, value in {
        "EVENT_HUB_NAMESPACE": "ehp-example.servicebus.windows.net",
        "EVENT_HUB_NAME": "workload",
        "EVENT_HUB_CONSUMER_GROUP": "slow-consumer",
        "CHECKPOINT_STORAGE_URL": "https://stexample.blob.core.windows.net",
        "CHECKPOINT_CONTAINER": "workload-checkpoints",
    }.items():
        monkeypatch.setenv(name, value)
    consumer = _load_consumer(monkeypatch, _FailingConsumer)

    with pytest.raises(ConnectionError):
        asyncio.run(asyncio.wait_for(consumer.run(), timeout=5))



def test_producer_payload_is_exactly_the_requested_size(monkeypatch):
    modules = {
        "azure": types.ModuleType("azure"),
        "azure.eventhub": types.ModuleType("azure.eventhub"),
        "azure.eventhub.aio": types.ModuleType("azure.eventhub.aio"),
        "azure.identity": types.ModuleType("azure.identity"),
        "azure.identity.aio": types.ModuleType("azure.identity.aio"),
    }
    modules["azure.eventhub"].EventData = object
    modules["azure.eventhub.aio"].EventHubProducerClient = _Client
    modules["azure.identity.aio"].DefaultAzureCredential = _Client
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.syspath_prepend(str(LAB_ROOT / "workloads"))
    monkeypatch.delitem(sys.modules, "producer", raising=False)
    import producer

    for size in (128, 1024, 4096):
        assert len(producer.make_payload(123456, size).encode()) == size
