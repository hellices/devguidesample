"""Shared helpers for the Azure DocumentDB change stream lab."""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

import certifi
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

CHECKPOINT_COLLECTION = "_cs_checkpoints"
SINK_COLLECTION = "_cs_sink"
RUN_COLLECTION = "_cs_runs"


def env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        stream=sys.stdout,
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("changestream")


def log_json(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str))


def get_client(app_name: str) -> MongoClient:
    return MongoClient(
        env("MONGO_URI"),
        appname=app_name,
        serverSelectionTimeoutMS=15000,
        tlsCAFile=certifi.where(),
        tz_aware=True,
    )


def get_database(client: MongoClient) -> Database:
    return client[env("MONGO_DB", "cslab")]


def get_source(db: Database) -> Collection:
    return db[env("MONGO_COLLECTION", "orders")]
