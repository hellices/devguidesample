"""
Azure AI Search 동의어(Synonym Map) 효과 비교 테스트
=====================================================

목적: 동의어 맵(`온누리상품권 ↔ 온누리 상품권 ↔ 온누리` 등)을 등록하면
     검색 정확도(recall)가 얼마나 올라가는지, 그리고 동의어가 분석기를
     "대체"하는 게 아니라 "보완"한다는 점을 실측으로 보여준다.

분석기 구성 결정 (모든 분석기 나열 대신 '일부'만 선정):
  - 목적이 '분석기 재비교'가 아니라 '동의어 효과' 검증이므로,
    최적 분석기(ko.microsoft)와 기본값(standard.lucene) 2종만 대조한다.
  - ko.lucene(n-gram 노이즈) / keyword(검색 부적합)는 동의어 효과를
    흐리므로 제외.
  - 각 분석기를 동의어 ON/OFF 로 색인해 2 x 2 = 4개 필드로 비교한다.

인덱스: analyzer-compare-idx-v2 (env INDEX_NAME_V2 로 재정의 가능)
동의어 맵: promo-synonyms

필드 구성:
  content_msft          → ko.microsoft            (동의어 X)
  content_msft_syn      → ko.microsoft + 동의어    (동의어 O)
  content_standard      → standard.lucene         (동의어 X)
  content_standard_syn  → standard.lucene + 동의어 (동의어 O)

실행:
  .\.venv\Scripts\python.exe synonym_test.py
"""

import json
import os
import time
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchableField,
    SearchIndex,
    SimpleField,
    SearchFieldDataType,
    SynonymMap,
)
from dotenv import load_dotenv

load_dotenv()

ENDPOINT = os.environ["SEARCH_ENDPOINT"]
ADMIN_KEY = os.environ["SEARCH_ADMIN_KEY"]
INDEX_NAME = os.environ.get("INDEX_NAME_V2", "analyzer-compare-idx-v2")
SYNONYM_MAP_NAME = "promo-synonyms"

CRED = AzureKeyCredential(ADMIN_KEY)

# 동의어 규칙(solr 등가 형식): 한 줄의 단어들은 서로 완전 동치로 취급된다.
#   예) '온누리' 로 검색해도 '온누리상품권' 문서가 잡히고, 그 반대도 성립.
SYNONYM_RULES = [
    "온누리상품권, 온누리 상품권, 온누리",   # 표기/띄어쓰기 변형 + 축약
    "지역사랑상품권, 지역화폐",              # 별칭(문서에 없는 표현)으로도 회수
    "문화상품권, 컬처랜드",                  # 외래어 별칭
]

# 동의어 ON/OFF 를 나눈 4개 필드
FIELDS = {
    "content_msft": ("ko.microsoft", False),
    "content_msft_syn": ("ko.microsoft", True),
    "content_standard": ("standard.lucene", False),
    "content_standard_syn": ("standard.lucene", True),
}

# 쿼리별 기대 정답(사람이 봤을 때 잡혀야 하는 문서 id)
#   기프트카드/지역화폐는 '문서에 없는' 동의어 → 동의어 맵이 있어야만 회수 가능
EXPECTED = {
    "상품권": {"1", "2", "3", "4", "5", "6"},
    "온누리": {"1", "2", "4", "5"},
    "온누리상품권": {"1", "2", "4", "5"},
    "지역화폐": {"3"},                              # = 지역사랑상품권 (문서에 없는 별칭)
    "컬처랜드": {"3"},                              # = 문화상품권 (문서에 없는 외래어 별칭)
}
TEST_QUERIES = list(EXPECTED.keys())


def load_data() -> list[dict]:
    return json.loads((Path(__file__).parent / "sample_data.json").read_text(encoding="utf-8"))


def create_synonym_map() -> None:
    client = SearchIndexClient(ENDPOINT, CRED)
    # ⚠️ synonyms 는 '규칙 문자열의 리스트'를 넘겨야 한다.
    #    단일 문자열("\n".join(...))을 넘기면 SDK가 글자 단위로 분해해 맵이 깨진다.
    sm = SynonymMap(name=SYNONYM_MAP_NAME, synonyms=SYNONYM_RULES)
    client.create_or_update_synonym_map(sm)
    print(f"[synonym] 동의어 맵 '{SYNONYM_MAP_NAME}' 등록 ({len(SYNONYM_RULES)}개 규칙)")
    for rule in SYNONYM_RULES:
        print(f"    - {rule}")


def create_index() -> None:
    client = SearchIndexClient(ENDPOINT, CRED)

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SimpleField(name="relevant", type=SearchFieldDataType.Boolean, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String, analyzer_name="ko.microsoft"),
    ]
    for field_name, (analyzer, use_syn) in FIELDS.items():
        fields.append(
            SearchableField(
                name=field_name,
                type=SearchFieldDataType.String,
                analyzer_name=analyzer,
                synonym_map_names=[SYNONYM_MAP_NAME] if use_syn else None,
                hidden=False,
            )
        )

    index = SearchIndex(name=INDEX_NAME, fields=fields)
    if INDEX_NAME in [i.name for i in client.list_indexes()]:
        client.delete_index(INDEX_NAME)
        print(f"[index] 기존 인덱스 '{INDEX_NAME}' 삭제")
    client.create_index(index)
    print(f"[index] 인덱스 '{INDEX_NAME}' 생성 (분석기 2종 x 동의어 ON/OFF = 4필드)")


def upload_docs() -> None:
    docs = []
    for item in load_data():
        doc = {"id": item["id"], "title": item["title"], "relevant": item["relevant"]}
        for field_name in FIELDS:
            doc[field_name] = item["content"]
        docs.append(doc)

    client = SearchClient(ENDPOINT, INDEX_NAME, CRED)
    result = client.upload_documents(documents=docs)
    ok = sum(1 for r in result if r.succeeded)
    print(f"[upload] {ok}/{len(docs)} 건 업로드 성공 (정답 6건 / distractor 4건)")


def _search_ids(client: SearchClient, query: str, field: str) -> list[str]:
    results = client.search(
        search_text=query,
        search_fields=[field],
        select=["id"],
        query_type="simple",
        search_mode="all",
    )
    return sorted((r["id"] for r in results), key=int)


def search_hits() -> None:
    client = SearchClient(ENDPOINT, INDEX_NAME, CRED)
    print(f"\n{'='*84}\n[Search] 동의어 ON/OFF 별 검색 히트 비교 (매칭 문서 id, searchMode=all)\n{'='*84}")
    labels = {
        "content_msft": "msft",
        "content_msft_syn": "msft+syn",
        "content_standard": "standard",
        "content_standard_syn": "standard+syn",
    }
    for query in TEST_QUERIES:
        print(f"\n  쿼리: \"{query}\"  (기대정답: {', '.join(sorted(EXPECTED[query], key=int))})")
        for field_name in FIELDS:
            ids = _search_ids(client, query, field_name)
            print(f"    {labels[field_name]:<14} : {', '.join(ids) if ids else '-'}")


def recall_report() -> None:
    client = SearchClient(ENDPOINT, INDEX_NAME, CRED)
    distractors = {d["id"] for d in load_data() if not d["relevant"]}

    print(f"\n{'='*84}\n[결론] 동의어 맵이 recall 에 미치는 효과 (기대정답 대비 회수율)\n{'='*84}")
    cols = ["msft", "msft+syn", "standard", "standard+syn"]
    header = f"  {'쿼리':<14}" + "".join(f"{c:<16}" for c in cols)
    print(header)
    print("  " + "-" * (len(header) - 2))

    perfect = {f: 0 for f in FIELDS}
    for query, expected in EXPECTED.items():
        row = f"  {query:<14}"
        for field_name in FIELDS:
            found = set(_search_ids(client, query, field_name))
            hit = len(found & expected)
            fp = found & distractors
            mark = "✓" if hit == len(expected) and not fp else " "
            if hit == len(expected) and not fp:
                perfect[field_name] += 1
            cell = f"{hit}/{len(expected)}{'+오탐' if fp else ''}{mark}"
            row += f"{cell:<16}"
        print(row)

    print("  " + "-" * (len(header) - 2))
    summary = f"  {'완벽(전체'+str(len(EXPECTED))+'쿼리)':<14}" + "".join(
        f"{str(perfect[f])+'/'+str(len(EXPECTED)):<16}" for f in FIELDS
    )
    print(summary)
    print("\n  => 동의어 맵은 '문서에 없는 표현'(예: 지역화폐 → 지역사랑상품권)까지 회수하게 해준다 (0→3).")
    print("     단, 조사가 붙은 토큰(지역사랑상품권'과')을 못 떼는 standard 는 동의어를 줘도 회수 실패:")
    print("     동의어는 좋은 분석기를 '대체'하지 못하고 '보완'한다. 최적 조합 = ko.microsoft + 동의어.")
    print("     주의: 별칭이 형태소로 분해되면(컬처랜드 → 컬처/랜드) 동의어가 발동하지 않을 수 있다.")


def main() -> None:
    create_synonym_map()
    create_index()
    upload_docs()
    time.sleep(3)  # 인덱싱 반영 대기
    search_hits()
    recall_report()


if __name__ == "__main__":
    main()
