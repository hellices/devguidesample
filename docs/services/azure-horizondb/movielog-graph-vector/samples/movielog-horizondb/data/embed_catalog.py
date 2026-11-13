#!/usr/bin/env python3
"""Embed catalog.movie_docs.doc with Azure OpenAI and store the vectors in HorizonDB.

Only rows whose embedding is NULL are processed (new or changed documents); --all re-embeds
every row, which is required after changing the model or dimensions. Authentication
uses a Microsoft Entra token from the Azure CLI (role: Cognitive Services OpenAI User), so the
Azure OpenAI account can keep key authentication disabled. psql must be on PATH; connection
settings come from the standard PGHOST, PGDATABASE, PGUSER, PGPASSWORD and PGSSLMODE variables.

  AZURE_OPENAI_ENDPOINT=https://<name>.openai.azure.com/ python3 data/embed_catalog.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
# text-embedding-3-large is shortened to the vector(1536) column; the app requests the same size.
DIMENSIONS = 1536
API_VERSION = "2024-10-21"
BATCH = 32


def psql(*args: str) -> str:
    return subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", *args], check=True, capture_output=True,
                          text=True).stdout


def token() -> str:
    return subprocess.run(["az", "account", "get-access-token", "--resource", "https://cognitiveservices.azure.com",
                           "--query", "accessToken", "-o", "tsv"], check=True, capture_output=True,
                          text=True).stdout.strip()


def embed(endpoint: str, bearer: str, texts: list[str]) -> list[list[float]]:
    url = f"{endpoint.rstrip('/')}/openai/deployments/{DEPLOYMENT}/embeddings?api-version={API_VERSION}"
    body = json.dumps({"input": texts, "dimensions": DIMENSIONS}).encode()
    for attempt in range(6):
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {bearer}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.load(response)["data"]
                return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
        except urllib.error.HTTPError as ex:
            if ex.code in (429, 500, 503) and attempt < 5:
                time.sleep(int(ex.headers.get("retry-after", 2 ** attempt)))
                continue
            raise
    raise RuntimeError("unreachable")


def main() -> int:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        print("AZURE_OPENAI_ENDPOINT is required", file=sys.stderr)
        return 2
    where = "" if "--all" in sys.argv[1:] else " WHERE embedding IS NULL"
    rows = json.loads(psql("-Atc", "SELECT coalesce(json_agg(json_build_object('id', tmdb_id, 'doc', doc)"
                                   " ORDER BY tmdb_id), '[]') FROM catalog.movie_docs" + where))
    print(f"{len(rows)} documents to embed", file=sys.stderr)
    if not rows:
        return 0
    bearer = token()
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8") as out:
        out.write("BEGIN;\n")
        for start in range(0, len(rows), BATCH):
            batch = rows[start:start + BATCH]
            vectors = embed(endpoint, bearer, [row["doc"] for row in batch])
            for row, vector in zip(batch, vectors):
                literal = "[" + ",".join(f"{v:.7g}" for v in vector) + "]"
                out.write(f"UPDATE catalog.movie_docs SET embedding = '{literal}'::vector, embedded_at = now()"
                          f" WHERE tmdb_id = {int(row['id'])};\n")
            print(f"  embedded {min(start + BATCH, len(rows))}/{len(rows)}", file=sys.stderr)
        out.write("COMMIT;\n")
        path = out.name
    try:
        psql("-q", "-f", path)
    finally:
        os.unlink(path)
    print(psql("-Atc", "SELECT count(*) || ' documents, ' || count(embedding) || ' embedded' FROM catalog.movie_docs"),
          end="", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
