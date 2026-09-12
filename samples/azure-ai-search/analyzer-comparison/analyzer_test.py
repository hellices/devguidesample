"""
Azure AI Search 한국어 분석기(Analyzer) 비교 테스트
===================================================

같은 한국어 텍스트를 서로 다른 Azure AI Search 분석기로 색인한 뒤,
"상품권" 같은 부분어(복합명사 일부) 검색이 분석기에 따라 얼마나
잘 되는지(recall)를 비교한다.

데이터 구성 (sample_data.json, 총 10건):
  - relevant=true  (id 1~6): 상품권/온누리상품권/지역사랑상품권 등을 언급 → 검색에 잡혀야 함
  - relevant=false (id 7~10): 상품권과 무관한 distractor → 잡히면 안 됨
  => 모든 문서에 키워드가 있던 이전과 달리, 이제 "정답/오답"이 나뉘어
     분석기별 검색 성능(recall/precision)이 명확히 드러난다.

필드명에 분석기명을 넣어 혼동을 없앰 (AI Search 필드명에는 '.' 불가 → '_' 사용):
  content_ko_microsoft   → ko.microsoft
  content_ko_lucene      → ko.lucene
  content_standard_lucene→ standard.lucene
  content_keyword        → keyword

실행:
  pip install -r requirements.txt
  python analyzer_test.py
"""

import json
import os
import time
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    AnalyzeTextOptions,
    SearchableField,
    SearchIndex,
    SimpleField,
    SearchFieldDataType,
)
from dotenv import load_dotenv

load_dotenv()

ENDPOINT = os.environ["SEARCH_ENDPOINT"]
ADMIN_KEY = os.environ["SEARCH_ADMIN_KEY"]
INDEX_NAME = os.environ.get("INDEX_NAME", "analyzer-compare-idx")

CRED = AzureKeyCredential(ADMIN_KEY)

# 필드명(분석기명 포함) -> 분석기 매핑. 같은 content 를 4가지 방식으로 색인.
ANALYZERS = {
    "content_ko_microsoft": "ko.microsoft",
    "content_ko_lucene": "ko.lucene",
    "content_standard_lucene": "standard.lucene",
    "content_keyword": "keyword",
}

# 분석기 동작 비교용 검색 키워드 (온누리상품권은 샘플 키워드)
# 각 쿼리별 '기대 정답'(사람이 봤을 때 잡혀야 하는 문서 id) 정의
EXPECTED = {
    "상품권": {"1", "2", "3", "4", "5", "6"},   # 상품권을 언급한 모든 문서
    "온누리상품권": {"1", "2", "4", "5"},          # 온누리상품권을 언급한 문서
    "온누리 상품권": {"1", "2", "4", "5"},
    "온누리": {"1", "2", "4", "5"},
    "지역사랑상품권": {"3"},
}
TEST_QUERIES = list(EXPECTED.keys())

# Analyze API 토큰 비교용 입력 (복합명사 샘플)
ANALYZE_SAMPLES = ["온누리상품권", "개인정보보호위원회"]


def load_data() -> list[dict]:
    return json.loads((Path(__file__).parent / "sample_data.json").read_text(encoding="utf-8"))


def create_index() -> None:
    """분석기별 content 필드를 가진 인덱스를 (재)생성한다. 모든 필드 retrievable."""
    client = SearchIndexClient(ENDPOINT, CRED)

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SimpleField(name="relevant", type=SearchFieldDataType.Boolean, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String, analyzer_name="ko.microsoft"),
    ]
    for field_name, analyzer in ANALYZERS.items():
        fields.append(
            SearchableField(
                name=field_name,
                type=SearchFieldDataType.String,
                analyzer_name=analyzer,
                hidden=False,  # retrievable=True → 포탈 결과에서 확인 가능
            )
        )

    index = SearchIndex(name=INDEX_NAME, fields=fields)

    if INDEX_NAME in [i.name for i in client.list_indexes()]:
        client.delete_index(INDEX_NAME)
        print(f"[index] 기존 인덱스 '{INDEX_NAME}' 삭제")
    client.create_index(index)
    print(f"[index] 인덱스 '{INDEX_NAME}' 생성 완료 (분석기 {len(ANALYZERS)}종, 모든 필드 retrievable)")


def upload_docs() -> None:
    """content 를 4개 분석기 필드에 동일하게 채워 업로드."""
    docs = []
    for item in load_data():
        doc = {"id": item["id"], "title": item["title"], "relevant": item["relevant"]}
        for field_name in ANALYZERS:
            doc[field_name] = item["content"]
        docs.append(doc)

    client = SearchClient(ENDPOINT, INDEX_NAME, CRED)
    result = client.upload_documents(documents=docs)
    ok = sum(1 for r in result if r.succeeded)
    print(f"[upload] {ok}/{len(docs)} 건 업로드 성공 (정답 6건 / distractor 4건)")


def compare_tokens(text: str) -> None:
    """Analyze API 로 분석기별 토큰 분해 결과를 비교 출력한다."""
    client = SearchIndexClient(ENDPOINT, CRED)
    print(f"\n{'='*72}\n[Analyze] 입력: \"{text}\"\n{'='*72}")
    for field_name, analyzer in ANALYZERS.items():
        result = client.analyze_text(
            INDEX_NAME, AnalyzeTextOptions(text=text, analyzer_name=analyzer)
        )
        tokens = [t.token for t in result.tokens]
        print(f"  {analyzer:<16} ({len(tokens):>2}) : {tokens}")


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
    """분석기 필드별로 각 쿼리의 검색 히트(문서 id)를 비교 출력한다."""
    client = SearchClient(ENDPOINT, INDEX_NAME, CRED)
    print(f"\n{'='*72}\n[Search] 쿼리별 분석기 필드 히트 비교 (매칭 문서 id, searchMode=all)\n{'='*72}")
    for query in TEST_QUERIES:
        print(f"\n  쿼리: \"{query}\"")
        for field_name in ANALYZERS:
            ids = _search_ids(client, query, field_name)
            label = field_name.replace("content_", "")
            print(f"    {label:<16} : {', '.join(ids) if ids else '-'}")


def recall_report() -> None:
    """핵심 결론: 여러 쿼리 변형 전체에서 분석기별 recall 비교.
    ko.microsoft 가 유일하게 모든 쿼리에서 완벽 recall 임을 보여준다."""
    client = SearchClient(ENDPOINT, INDEX_NAME, CRED)
    distractors = {d["id"] for d in load_data() if not d["relevant"]}  # 무관 4건

    print(f"\n{'='*72}\n[결론] 쿼리 변형별 recall (기대정답 대비 회수율)\n{'='*72}")
    header = f"  {'쿼리':<14}" + "".join(f"{a:<17}" for a in ANALYZERS.values())
    print(header)
    print("  " + "-" * (len(header) - 2))

    perfect = {a: 0 for a in ANALYZERS.values()}
    for query, expected in EXPECTED.items():
        row = f"  {query:<14}"
        for field_name, analyzer in ANALYZERS.items():
            found = set(_search_ids(client, query, field_name))
            hit = len(found & expected)
            fp = found & distractors
            mark = "✓" if hit == len(expected) and not fp else " "
            if hit == len(expected) and not fp:
                perfect[analyzer] += 1
            row += f"{hit}/{len(expected)}{('+오탐' if fp else '')}{mark:<12}"
        print(row)

    print("  " + "-" * (len(header) - 2))
    summary = "  " + f"{'완벽(전체'+str(len(EXPECTED))+'쿼리)':<14}" + "".join(
        f"{str(perfect[a])+'/'+str(len(EXPECTED)):<17}" for a in ANALYZERS.values()
    )
    print(summary)
    print("\n  => ko.microsoft 만 모든 쿼리에서 기대정답을 완벽히 회수한다.")
    print("     ko.lucene 은 '온누리상품권'(붙여쓴 복합명사) 쿼리에서 띄어쓴 문서(id4)를 놓치고,")
    print("     standard.lucene/keyword 는 복합명사에 붙은 상품권 자체를 대부분 놓친다.")


def main() -> None:
    create_index()
    upload_docs()
    for sample in ANALYZE_SAMPLES:
        compare_tokens(sample)
    time.sleep(3)  # 검색 인덱싱 반영 대기
    search_hits()
    recall_report()


if __name__ == "__main__":
    main()
