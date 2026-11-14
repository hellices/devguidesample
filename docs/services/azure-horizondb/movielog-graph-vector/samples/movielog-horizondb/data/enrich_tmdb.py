#!/usr/bin/env python3
"""Add TMDB poster, runtime and IMDb id to the catalog movies.

build_catalog.py takes structure and summaries from Wikidata and Wikipedia, so the rows it
loads into public.movies have no poster. This script reads the TMDB ids from catalog.json,
calls the TMDB movie details API and writes tmdb.sql, which fills only empty poster_path,
runtime and imdb_id columns. Titles and summaries from Wikipedia are left unchanged.

The TMDB API Read Access Token is read from the TMDB_API_TOKEN environment variable.
Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "movielog-horizondb-lab/1.0 (https://github.com/hellices/devguidesample)"
DETAILS = "https://api.themoviedb.org/3/movie/{id}?language=ko-KR"


def sql_text(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


def fetch(tmdb_id: int, token: str, attempts: int = 4) -> dict | None:
    request = urllib.request.Request(DETAILS.format(id=tmdb_id), headers={
        "Authorization": "Bearer " + token, "Accept": "application/json", "User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return None
            if ex.code == 429 or ex.code >= 500:
                time.sleep(float(ex.headers.get("Retry-After") or 2 ** attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt)
    raise RuntimeError(f"TMDB details failed for {tmdb_id}")


def update_sql(tmdb_id: int, details: dict) -> str | None:
    poster = (details.get("poster_path") or "")[:200] or None
    imdb = (details.get("imdb_id") or "")[:20] or None
    runtime = details.get("runtime") or None
    if poster is None and imdb is None and runtime is None:
        return None
    return ("UPDATE public.movies SET"
            f" poster_path = COALESCE(poster_path, {sql_text(poster)}),"
            f" imdb_id = COALESCE(imdb_id, {sql_text(imdb)}),"
            f" runtime = COALESCE(runtime, {int(runtime) if runtime else 'NULL'})"
            f" WHERE tmdb_id = {int(tmdb_id)};")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    out_default = Path(__file__).resolve().parent / "out"
    parser.add_argument("--catalog", type=Path, default=out_default / "catalog.json")
    parser.add_argument("--out", type=Path, default=out_default / "tmdb.sql")
    parser.add_argument("--workers", type=int, default=4, help="parallel requests; TMDB allows about 40 per second")
    args = parser.parse_args()

    token = os.environ.get("TMDB_API_TOKEN")
    if not token:
        print("TMDB_API_TOKEN is not set", file=sys.stderr)
        return 2
    ids = sorted({int(film["tmdb_id"]) for film in json.loads(args.catalog.read_text(encoding="utf-8"))})
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda tmdb_id: (tmdb_id, fetch(tmdb_id, token)), ids))

    lines = ["BEGIN;"]
    missing = 0
    for tmdb_id, details in results:
        statement = update_sql(tmdb_id, details) if details else None
        if statement is None:
            missing += 1
        else:
            lines.append(statement)
    lines.append("COMMIT;")
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(ids) - missing} of {len(ids)} movies have TMDB details -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
