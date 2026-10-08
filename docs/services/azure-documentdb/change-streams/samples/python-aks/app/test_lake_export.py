import unittest
from types import SimpleNamespace

from azure.core import MatchConditions
from bson import json_util

from lake_export import Checkpoint


class State:
    def __init__(self, body):
        self.body = body
        self.etag = '"etag-1"'


class Download:
    def __init__(self, state):
        self.state = state
        self.properties = SimpleNamespace(etag=state.etag)

    def readall(self):
        return self.state.body


class FileClient:
    def __init__(self, state):
        self.state = state

    def download_file(self):
        return Download(self.state)

    def get_file_properties(self):
        return SimpleNamespace(etag=self.state.etag)

    def upload_data(self, *_args, **_kwargs):
        raise AssertionError("checkpoint save must not use DFS upload_data")


class FileSystem:
    def __init__(self, state):
        self.state = state

    def get_file_client(self, _path):
        return FileClient(self.state)


class BlobClient:
    def __init__(self, state):
        self.state = state
        self.fail = False
        self.calls = []

    def upload_blob(self, body, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("injected Put Blob failure")
        if kwargs.get("etag") and kwargs["etag"] != self.state.etag:
            raise AssertionError("wrong ETag")
        self.state.body = body
        self.state.etag = '"etag-2"'
        return {"etag": self.state.etag}


class BlobContainer:
    def __init__(self, blob):
        self.blob = blob

    def get_blob_client(self, _path):
        return self.blob


class CheckpointAtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.old = {
            "token": {"_data": "old"},
            "start_at": None,
            "events": 1,
            "writing": None,
        }
        self.state = State(json_util.dumps(self.old))
        self.blob = BlobClient(self.state)
        self.checkpoint = Checkpoint(
            FileSystem(self.state),
            BlobContainer(self.blob),
            "orders",
        )
        self.assertEqual(self.checkpoint.load()["token"], {"_data": "old"})

    def test_existing_checkpoint_is_one_conditional_blob_upload(self):
        self.checkpoint.save({"_data": "new"}, 2)

        self.assertEqual(
            self.blob.calls,
            [
                {
                    "overwrite": True,
                    "etag": '"etag-1"',
                    "match_condition": MatchConditions.IfNotModified,
                }
            ],
        )
        self.assertEqual(self.checkpoint.load()["token"], {"_data": "new"})

    def test_failed_upload_preserves_previous_checkpoint(self):
        previous_body = self.state.body
        self.blob.fail = True

        with self.assertRaisesRegex(RuntimeError, "injected Put Blob failure"):
            self.checkpoint.save({"_data": "new"}, 2)

        self.assertEqual(self.state.body, previous_body)
        self.assertEqual(self.checkpoint.load()["token"], {"_data": "old"})


if __name__ == "__main__":
    unittest.main()
