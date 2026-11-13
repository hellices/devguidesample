#!/usr/bin/env python3
"""Build a movie catalog from Wikidata (structure) and Wikipedia (summaries).

Output (under --out, default data/out/):
  catalog.json  movies with credits, genres and summary text
  catalog.sql   idempotent upserts into public.movies and the catalog schema

Wikidata content is CC0. Wikipedia summaries (Korean lead, plus the English lead in the
embedded text) are CC BY-SA 4.0; the SQL keeps the shown article URL per movie for attribution. Only the Python standard
library is used.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "movielog-horizondb-lab/1.0 (https://github.com/hellices/devguidesample)"
SPARQL = "https://query.wikidata.org/sparql"

TOP_FILMS = """
SELECT ?film ?tmdb ?links WHERE {
  ?film wdt:P31 wd:Q11424; wdt:P4947 ?tmdb; wikibase:sitelinks ?links.
  FILTER(?links >= %(min_links)d)
} ORDER BY DESC(?links) LIMIT %(limit)d
"""

KOREAN_FILMS = """
SELECT ?film ?tmdb ?links WHERE {
  ?film wdt:P31 wd:Q11424; wdt:P495 wd:Q884; wdt:P4947 ?tmdb; wikibase:sitelinks ?links.
  FILTER(?links >= %(min_links)d)
} ORDER BY DESC(?links) LIMIT %(limit)d
"""

FILM_DETAILS = """
SELECT ?film ?date ?koLabel ?enLabel ?koArticle ?enArticle WHERE {
  VALUES ?film { %(values)s }
  OPTIONAL { ?film wdt:P577 ?date. }
  OPTIONAL { ?film rdfs:label ?koLabel FILTER(LANG(?koLabel) = "ko") }
  OPTIONAL { ?film rdfs:label ?enLabel FILTER(LANG(?enLabel) = "en") }
  OPTIONAL { ?koArticle schema:about ?film; schema:isPartOf <https://ko.wikipedia.org/>. }
  OPTIONAL { ?enArticle schema:about ?film; schema:isPartOf <https://en.wikipedia.org/>. }
}
"""

FILM_CREDITS = """
SELECT ?film ?role ?person ?ord WHERE {
  VALUES ?film { %(values)s }
  {
    ?film wdt:P57 ?person. BIND("director" AS ?role)
  } UNION {
    ?film p:P161 ?st. ?st ps:P161 ?person. BIND("actor" AS ?role)
    OPTIONAL { ?st pq:P1545 ?ord. }
  }
}
"""

# Person labels and sitelinks are fetched separately: joining them into the credits
# query makes the Wikidata Query Service time out.
PEOPLE = """
SELECT ?person ?plinks ?koName ?enName WHERE {
  VALUES ?person { %(values)s }
  ?person wikibase:sitelinks ?plinks.
  OPTIONAL { ?person rdfs:label ?koName FILTER(LANG(?koName) = "ko") }
  OPTIONAL { ?person rdfs:label ?enName FILTER(LANG(?enName) = "en") }
}
"""

FILM_GENRES = """
SELECT ?film ?genre ?koGenre ?enGenre WHERE {
  VALUES ?film { %(values)s }
  ?film wdt:P136 ?genre.
  OPTIONAL { ?genre rdfs:label ?koGenre FILTER(LANG(?koGenre) = "ko") }
  OPTIONAL { ?genre rdfs:label ?enGenre FILTER(LANG(?enGenre) = "en") }
}
"""

MAX_ACTORS = 6
MAX_GENRES = 4


def http_json(url: str, *, timeout: int = 120, retries: int = 4) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return {}
            if ex.code in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                time.sleep(2 ** attempt * 3)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead, json.JSONDecodeError):
            if attempt + 1 < retries:
                time.sleep(2 ** attempt * 3)
                continue
            raise
    return {}


def sparql(query: str) -> list[dict]:
    url = SPARQL + "?format=json&query=" + urllib.parse.quote(query)
    return http_json(url).get("results", {}).get("bindings", [])


def value(row: dict, key: str) -> str | None:
    cell = row.get(key)
    return None if cell is None else cell["value"]


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def clean_genre(label: str) -> str:
    cleaned = re.sub(r"\s*(영화|film|movie)$", "", label.strip(), flags=re.IGNORECASE).strip()
    return cleaned or label.strip()


def select_films(limit: int, korean_limit: int) -> dict[str, dict]:
    films: dict[str, dict] = {}
    for query, args in ((TOP_FILMS, {"min_links": 45, "limit": limit}),
                        (KOREAN_FILMS, {"min_links": 15, "limit": korean_limit})):
        for row in sparql(query % args):
            film = qid(value(row, "film"))
            tmdb = value(row, "tmdb")
            if not tmdb or not tmdb.isdigit():
                continue
            films.setdefault(film, {"qid": film, "tmdb_id": int(tmdb), "sitelinks": int(value(row, "links"))})
    # One TMDB id must map to exactly one film.
    seen: dict[int, str] = {}
    for film in sorted(films.values(), key=lambda f: -f["sitelinks"]):
        seen.setdefault(film["tmdb_id"], film["qid"])
    return {q: f for q, f in films.items() if seen[f["tmdb_id"]] == q}


def enrich(films: dict[str, dict]) -> None:
    for batch in chunks(list(films), 60):
        values = " ".join(f"wd:{q}" for q in batch)
        for row in sparql(FILM_DETAILS % {"values": values}):
            film = films[qid(value(row, "film"))]
            date = value(row, "date")
            if date and not date.startswith("-") and (film.get("release_date") is None or date[:10] < film["release_date"]):
                film["release_date"] = date[:10]
            for key, column in (("title_ko", "koLabel"), ("title_en", "enLabel"),
                                ("ko_article", "koArticle"), ("en_article", "enArticle")):
                if film.get(key) is None:
                    film[key] = value(row, column)

        raw_credits = sparql(FILM_CREDITS % {"values": values})
        people = lookup_people({qid(value(row, "person")) for row in raw_credits})
        credits: dict[str, dict[str, dict]] = {}
        for row in raw_credits:
            film = qid(value(row, "film"))
            person = qid(value(row, "person"))
            info = people.get(person)
            if info is None:
                continue
            role = value(row, "role")
            ordinal = value(row, "ord")
            entry = credits.setdefault(film, {}).setdefault(f"{role}:{person}", {"qid": person, "role": role, **info, "ord": None})
            if entry["ord"] is None and ordinal and ordinal.isdigit():
                entry["ord"] = int(ordinal)
        for film_qid, entries in credits.items():
            directors = sorted((e for e in entries.values() if e["role"] == "director"), key=lambda e: -e["sitelinks"])
            actors = sorted((e for e in entries.values() if e["role"] == "actor"),
                            key=lambda e: (e["ord"] is None, e["ord"] or 0, -e["sitelinks"]))[:MAX_ACTORS]
            films[film_qid]["credits"] = directors + actors

        genres: dict[str, list[str]] = {}
        for row in sparql(FILM_GENRES % {"values": values}):
            label = value(row, "koGenre") or value(row, "enGenre")
            if label:
                bucket = genres.setdefault(qid(value(row, "film")), [])
                name = clean_genre(label)
                if name not in bucket:
                    bucket.append(name)
        for film_qid, names in genres.items():
            films[film_qid]["genres"] = names[:MAX_GENRES]
        time.sleep(1)


def lookup_people(qids: set[str]) -> dict[str, dict]:
    people: dict[str, dict] = {}
    for batch in chunks(sorted(qids), 200):
        for row in sparql(PEOPLE % {"values": " ".join(f"wd:{q}" for q in batch)}):
            person = qid(value(row, "person"))
            people.setdefault(person, {
                "name": value(row, "koName") or value(row, "enName") or person,
                "name_en": value(row, "enName"),
                "sitelinks": int(value(row, "plinks")),
            })
    return people


def summary(article_url: str | None) -> tuple[str | None, str | None]:
    if not article_url:
        return None, None
    parsed = urllib.parse.urlparse(article_url)
    title = parsed.path.rsplit("/", 1)[-1]
    data = http_json(f"{parsed.scheme}://{parsed.netloc}/api/rest_v1/page/summary/{title}", timeout=30)
    extract = (data.get("extract") or "").strip()
    return (extract or None), (article_url if extract else None)


def add_summaries(films: dict[str, dict]) -> None:
    def work(film: dict) -> None:
        ko_text, ko_source = summary(film.get("ko_article"))
        en_text, en_source = summary(film.get("en_article"))
        film["overview"], film["overview_source"] = (ko_text, ko_source) if ko_text else (en_text, en_source)
        # Korean leads often describe production only; the English lead usually states the premise.
        film["summary_en"] = en_text if ko_text else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(work, films.values()))


def document(film: dict) -> str:
    """Text that is embedded: title, year, genres, people and the summary."""
    directors = [c["name"] for c in film["credits"] if c["role"] == "director"]
    actors = [c["name"] for c in film["credits"] if c["role"] == "actor"]
    parts = [f"제목: {film['title']}"]
    if film.get("original_title") and film["original_title"] != film["title"]:
        parts.append(f"원제: {film['original_title']}")
    if film.get("release_date"):
        parts.append(f"개봉: {film['release_date'][:4]}")
    if film["genres"]:
        parts.append("장르: " + ", ".join(film["genres"]))
    if directors:
        parts.append("감독: " + ", ".join(directors))
    if actors:
        parts.append("출연: " + ", ".join(actors))
    if film.get("overview"):
        parts.append("줄거리: " + film["overview"])
    if film.get("summary_en"):
        parts.append("Summary: " + film["summary_en"])
    return "\n".join(parts)


def sql_text(text: str | None) -> str:
    return "NULL" if text is None else "'" + text.replace("'", "''") + "'"


def write_sql(films: list[dict], path: Path) -> None:
    lines = ["-- Generated by build_catalog.py. Re-running is idempotent.", "BEGIN;"]
    people: dict[str, dict] = {}
    for film in films:
        for credit in film["credits"]:
            people.setdefault(credit["qid"], credit)
    for film in films:
        genres = ", ".join(film["genres"])[:300] or None
        release = "DATE " + sql_text(film["release_date"]) if film.get("release_date") else "NULL"
        lines.append(
            "INSERT INTO public.movies (tmdb_id, title, original_title, release_date, genres, overview, view_count,"
            " synced_at, created_at) VALUES ("
            f"{film['tmdb_id']}, {sql_text(film['title'][:300])}, {sql_text((film.get('original_title') or '')[:300] or None)}, "
            f"{release}, {sql_text(genres)}, {sql_text((film.get('overview') or '')[:4000] or None)}, 0, now(), now())"
            " ON CONFLICT (tmdb_id) DO UPDATE SET title = EXCLUDED.title, original_title = EXCLUDED.original_title,"
            " release_date = EXCLUDED.release_date, genres = EXCLUDED.genres, overview = EXCLUDED.overview;")
    for person in people.values():
        lines.append(
            "INSERT INTO catalog.people (qid, name, name_en, sitelinks) VALUES ("
            f"{sql_text(person['qid'])}, {sql_text(person['name'])}, {sql_text(person.get('name_en'))}, {person['sitelinks']})"
            " ON CONFLICT (qid) DO UPDATE SET name = EXCLUDED.name, name_en = EXCLUDED.name_en,"
            " sitelinks = EXCLUDED.sitelinks;")
    for film in films:
        tmdb = film["tmdb_id"]
        lines.append(f"DELETE FROM catalog.movie_credits WHERE tmdb_id = {tmdb};")
        lines.append(f"DELETE FROM catalog.movie_genres WHERE tmdb_id = {tmdb};")
        for position, credit in enumerate(film["credits"]):
            lines.append("INSERT INTO catalog.movie_credits (tmdb_id, person_qid, role, position) VALUES ("
                         f"{tmdb}, {sql_text(credit['qid'])}, {sql_text(credit['role'])}, {position})"
                         " ON CONFLICT DO NOTHING;")
        for genre in film["genres"]:
            lines.append(f"INSERT INTO catalog.movie_genres (tmdb_id, genre) VALUES ({tmdb}, {sql_text(genre)})"
                         " ON CONFLICT DO NOTHING;")
        # Keep an existing embedding only while the embedded text is unchanged.
        lines.append(
            "INSERT INTO catalog.movie_docs (tmdb_id, wikidata_qid, doc, source_url) VALUES ("
            f"{tmdb}, {sql_text(film['qid'])}, {sql_text(film['doc'])}, {sql_text(film.get('overview_source'))})"
            " ON CONFLICT (tmdb_id) DO UPDATE SET wikidata_qid = EXCLUDED.wikidata_qid, source_url = EXCLUDED.source_url,"
            " embedding = CASE WHEN catalog.movie_docs.doc = EXCLUDED.doc THEN catalog.movie_docs.embedding END,"
            " doc = EXCLUDED.doc;")
    lines.append("COMMIT;")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=400, help="most-linked films worldwide")
    parser.add_argument("--korean-limit", type=int, default=80, help="most-linked Korean films")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "out")
    args = parser.parse_args()

    films = select_films(args.limit, args.korean_limit)
    print(f"selected {len(films)} films", file=sys.stderr)
    enrich(films)
    add_summaries(films)

    result = []
    for film in films.values():
        film["title"] = film.get("title_ko") or film.get("title_en") or film["qid"]
        film["original_title"] = film.get("title_en")
        film.setdefault("genres", [])
        film.setdefault("credits", [])
        film["doc"] = document(film)
        result.append(film)
    result.sort(key=lambda f: -f["sitelinks"])

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "catalog.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    write_sql(result, args.out / "catalog.sql")
    with_overview = sum(1 for f in result if f.get("overview"))
    print(f"wrote {len(result)} films ({with_overview} with summary) to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
