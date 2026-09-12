# DevGuideSample 공개 GitHub Pages 설계

- 작성일: 2026-09-12
- 상태: 구현 계획 수립 전 사용자 검토
- 대상 저장소: `hellices/devguidesample`
- 기본 공개 URL: `https://hellices.github.io/devguidesample/`

## 1. 배경

이 저장소는 Azure 관련 실제 문제 해결 사례, 일반 기술 가이드, 실행 가능한 실습, 비교·벤치마크·아키텍처 리서치를 함께 보관한다. 현재 `main` 기준으로 검색 가능한 Markdown 문서가 71개이며, 문서는 18개 최상위 영역에 분산되어 있다.

현재 구조에서 확인한 주요 문제는 다음과 같다.

- 문서에 일관된 front matter 메타데이터가 없다.
- 특정 시점의 장애 이력과 계속 갱신해야 할 일반 가이드가 한 문서에 섞여 있다.
- 문서, 실행 코드, 캡처 결과, 생성 산출물이 같은 디렉터리 트리에 혼재한다.
- 루트 README는 일부 실습만 색인하며 전체 문서의 탐색 진입점 역할을 하지 못한다.
- GitHub Pages와 검색용 사이트 구성은 아직 없다.
- 로컬 상대 링크 3개가 현재 깨져 있다.
- 저장소는 공개이지만 README에는 내부 지식 공유 목적이라는 표현이 남아 있어 공개 사이트 기준으로 문구와 안전 규칙을 정비해야 한다.

문서 수와 변경 빈도가 빠르게 증가하고 있으므로 단순한 파일 목록이 아니라 문서 유형별 수명주기, 검색, 분류, 검증을 갖춘 공개 지식 사이트가 필요하다.

## 2. 목표

1. 공개 GitHub Pages 사이트에서 한국어와 영어 기술 용어로 전체 문서를 검색할 수 있게 한다.
2. 문서를 문제 해결 사례, 지속 갱신형 가이드, 실습, 리서치의 네 모음으로 분리한다.
3. 서비스, 증상, 기술 스택, 문서 유형을 기준으로 검색 외 탐색 경로를 제공한다.
4. 일반 가이드에 적용 범위와 마지막 검증일을 명시해 제품 기능 변경에 맞춰 갱신할 수 있게 한다.
5. README, 기여 지침, `AGENTS.md`가 같은 작성 규칙을 가리키도록 한다.
6. Pull Request에서 사이트 빌드, 메타데이터, 내부 링크와 공개 안전성을 검증한다.
7. `main` 병합 후 생성 파일을 저장소에 커밋하지 않고 GitHub Pages에 자동 배포한다.
8. 새 문서는 정해진 폴더와 메타데이터 규칙만 지키면 별도 메뉴 편집 없이 사이트, 모음, 서비스 및 태그 색인에 자동 포함한다.
9. 공개 기술 문서의 제품 동작, 지원 상태와 절차를 Microsoft Learn 공식 문서에 대조하는 검증 하네스를 제공한다.

## 3. 비목표

초기 구현에서는 다음 항목을 포함하지 않는다.

- 로그인 또는 CSA 팀 전용 접근 제어
- 서버 측 검색, 벡터 검색, RAG 또는 질의응답 챗봇
- 사용자 댓글, 평가, 분석용 서버
- 사용자 지정 도메인
- 기존 Markdown 파일 경로 또는 GitHub 링크의 호환성 보존
- 모든 코드 샘플을 사이트 안에서 직접 실행하는 기능
- 로컬 검색 결과가 없을 때 외부 공식 사이트의 결과를 실시간으로 수집하는 서버

## 4. 핵심 결정

| 항목 | 결정 | 근거 |
|---|---|---|
| 사이트 생성기 | Material for MkDocs | 기존 Markdown과 호환되고 한국어를 지원하는 내장 클라이언트 검색을 제공한다. |
| 배포 | GitHub Actions 기반 GitHub Pages | 빌드 결과를 브랜치에 커밋하지 않고 Pages 아티팩트로 배포할 수 있다. |
| 검색 | MkDocs `search` 플러그인, `ko`와 `en` | 별도 외부 검색 서비스 없이 제목, 본문, 섹션을 브라우저에서 검색한다. |
| 분류 색인 | Material `tags`와 빌드 시 생성하는 서비스 색인 | front matter를 기준으로 문서를 자동 모아 수동 목록의 누락을 막는다. |
| 정보 구조 | 문서 유형 우선, 서비스와 태그는 교차 색인 | 문서 수명주기를 분명히 하면서 서비스별 탐색도 제공한다. |
| 내비게이션 | `mkdocs-awesome-nav`와 분산된 `.nav.yml` | 전체 문서 목록을 한 파일에 수동 관리하지 않고 새 문서를 자동 포함한다. |
| 문서 검증 근거 | Microsoft Learn MCP와 명시적 공식 출처 메타데이터 | 작성 에이전트가 최신 Microsoft 공식 문서를 검색하고 원문을 조회한 뒤 기술 주장을 교차 검증한다. |
| MCP 연동 | 워크스페이스 MCP 설정과 repository skill 분리 | 연결 정보와 검증 절차를 각각 관리하고 MCP 도구의 동적 변경에 대응한다. |
| 공개 방식 | 프로젝트 Pages 사이트 | 기본 URL은 `https://hellices.github.io/devguidesample/`이다. |
| 생성물 | `site/`은 Git에서 제외 | 소스 Markdown만 버전 관리한다. |

## 5. 저장소 구조

```text
devguidesample/
├── docs/
│   ├── index.md
│   ├── cases/
│   │   └── <service>/<topic>/
│   │       ├── index.md
│   │       └── images/
│   ├── guides/
│   │   └── <service>/<topic>/
│   │       ├── index.md
│   │       └── images/
│   ├── labs/
│   │   └── <service>/<topic>/index.md
│   ├── research/
│   │   └── <service>/<topic>/index.md
│   ├── services/
│   ├── tags.md
│   ├── overrides/
│   ├── contributing/
│   │   ├── index.md
│   │   ├── case-template.md
│   │   ├── guide-template.md
│   │   ├── lab-template.md
│   │   └── research-template.md
│   └── assets/
├── samples/
│   └── <service>/<topic>/
├── project/
│   ├── specs/
│   └── plans/
├── scripts/docs/
│   ├── generate_indexes.py
│   ├── validate_metadata.py
│   └── validate_sources.py
├── .vscode/
│   └── mcp.json
├── .github/skills/
│   └── verify-with-microsoft-learn/
│       └── SKILL.md
├── .github/workflows/
│   ├── docs-ci.yml
│   └── pages.yml
├── .github/pull_request_template.md
├── README.md
├── CONTRIBUTING.md
├── AGENTS.md
├── docs-taxonomy.yml
├── mkdocs.yml
└── requirements-docs.txt
```

각 공개 문서는 `index.md`와 그 문서 전용 `images/`를 함께 두는 page bundle 형태를 사용한다. 실행 코드, 배포 매니페스트, 대용량 샘플 데이터는 `samples/`에 두고 문서에서 GitHub 소스 링크로 연결한다.

`project/specs/`와 `project/plans/`는 저장소 작업 기록용이며 공개 문서 소스인 `docs/`와 분리한다. `docs-taxonomy.yml`은 서비스, 기술, 태그, 문서 유형과 상태의 허용 식별자를 관리하는 단일 기준 파일이다. 생성기와 검증기는 이 파일을 읽으며 같은 목록을 코드에 다시 하드코딩하지 않는다.

`.vscode/mcp.json`은 Microsoft Learn 원격 MCP 서버 연결만 정의한다. `.github/skills/verify-with-microsoft-learn/SKILL.md`는 연결된 MCP를 사용해 기술 문서를 검증하는 절차를 정의한다. 현재 `.gitignore`의 `.github/skills/` 전체 제외 규칙은 이 repository skill 디렉터리만 명시적으로 추적하도록 allowlist 형태로 바꾼다. 개인용 또는 생성된 다른 skill은 계속 무시한다.

## 6. 사이트 정보 구조

### 6.1 전역 내비게이션

사이트는 다음 최상위 메뉴를 제공한다.

1. 홈
2. 문제 해결 사례
3. 일반 가이드
4. 실습
5. 리서치
6. 서비스별 찾기
7. 태그
8. 기여하기

모든 페이지의 상단에는 검색과 GitHub 저장소 링크를 배치한다. 문서 페이지 왼쪽에는 현재 모음과 서비스 기준 내비게이션을, 오른쪽에는 문서 내 목차를 표시한다.

### 6.2 홈

홈은 저장소 파일 목록을 복제하지 않고 다음 진입점을 제공한다.

- 가장 눈에 띄는 위치의 검색
- 네 문서 모음 설명과 링크
- AKS, Azure AI Search, Azure Monitor, Azure 데이터 서비스 등 주요 서비스 링크
- 문서 유형 선택 안내
- 기여 지침 링크

초기 버전에서는 동적 인기 순위나 사용 통계를 만들지 않는다.

### 6.3 URL 규칙

URL과 디렉터리 이름은 소문자 kebab-case 영문을 사용한다. Azure 제품의 서비스 slug는 `azure-`와 공식 전체 제품명을 사용하고, Microsoft 제품과 오픈소스는 각각 공식 제품명과 프로젝트명을 그대로 kebab-case로 변환한다.

```text
/cases/azure-kubernetes-service/pod-database-query-latency/
/guides/azure-kubernetes-service/file-io-diagnosis/
/labs/azure-monitor/sre-agent-event-lab/
/research/azure-ai-search/chunking-strategies/
```

제목과 본문은 한국어를 기본으로 하되 제품명, API, 오류 메시지 등 검색에 유용한 공식 영문 용어를 함께 표기한다.

### 6.4 서비스와 태그 색인 생성

`scripts/docs/generate_indexes.py`는 공개 문서의 front matter를 읽어 서비스별 문서 목록을 빌드 시 생성한다. `mkdocs-gen-files`를 사용해 가상 Markdown 페이지를 만들기 때문에 생성된 색인 파일은 작업 트리나 Git에 남기지 않는다. 태그 색인은 Material의 `tags` 플러그인이 생성한다.

새 문서는 올바른 `services`와 `tags`만 지정하면 해당 색인에 자동 포함된다. 사람이 서비스별 문서 목록을 중복 편집하지 않는다.

### 6.5 자동 내비게이션 계약

`mkdocs.yml`에는 문서별 `nav` 목록을 두지 않는다. 루트 `docs/.nav.yml`은 홈, 네 모음, 생성 색인과 기여 페이지의 안정적인 최상위 순서만 선언하고 `"*"` glob 또는 `append_unmatched: true`로 나머지 디렉터리와 페이지를 자동 발견한다. 개별 문서 경로를 `.nav.yml`에 열거하지 않는다.

새 공개 문서가 Pages와 메뉴에 포함되는 조건은 다음 세 가지뿐이다.

1. `docs/<collection>/<service>/<topic>/index.md`에 둔다.
2. 유효한 공통 및 문서 유형별 front matter를 작성한다.
3. 서비스 또는 태그 식별자가 새 값이면 `docs-taxonomy.yml`에 한 번 등록한다.

빌드 시 `mkdocs-awesome-nav`가 폴더 트리에서 메뉴를 만들고, `mkdocs-gen-files`가 같은 front matter에서 모음·서비스 색인을 생성하며, Material `tags` 플러그인이 태그 색인을 생성한다. 문서 추가를 위해 `mkdocs.yml`, 루트 내비게이션, README 또는 별도 문서 목록을 수정하지 않는다.

폴더 또는 페이지의 표시 이름과 정렬을 특별히 바꿔야 할 때만 해당 폴더에 작은 `.nav.yml`을 둔다. 이 파일은 하위 파일 목록이 아니라 `title`, `order` 같은 표시 재정의만 담는다. 이 예외도 새 문서가 자동 포함되는 기본 동작을 막지 않아야 한다.

## 7. 콘텐츠 모델

### 7.1 공통 front matter

모든 공개 문서는 다음 필드를 가진다.

```yaml
---
title: AKS Pod 데이터베이스 지연 분석
description: AKS에서 발생하는 데이터베이스 호출 지연의 진단과 해결 방법
document_type: guide
services:
  - aks
  - azure-mysql
technologies:
  - nodejs
tags:
  - latency
  - connection-pool
  - networking
status: current
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: Azure Kubernetes Service documentation
    url: https://learn.microsoft.com/azure/aks/
---
```

| 필드 | 규칙 |
|---|---|
| `title` | 한 페이지 안에서 내용을 명확히 구분하는 제목 |
| `description` | 검색 결과에 사용할 한 문장 요약 |
| `document_type` | `case`, `guide`, `lab`, `research` 중 하나 |
| `services` | 기여 지침에 정의한 통제된 서비스 식별자 목록 |
| `technologies` | 언어, SDK, 런타임, 도구 식별자 목록 |
| `tags` | 증상, 패턴, 작업 유형을 나타내는 통제된 소문자 kebab-case 목록 |
| `status` | 문서 유형별 허용 상태 중 하나 |
| `verification_status` | 공식 원문과 의미를 대조했으면 `verified`, 추가 검토가 필요하면 `needs-review` |
| `sources_checked_at` | 기술 주장을 공식 출처와 마지막으로 대조한 날짜 |
| `official_sources` | 제목과 HTTPS URL로 구성된 공식 근거 목록. 공개 기술 문서는 Microsoft Learn URL을 하나 이상 포함한다. |

서비스, 기술과 태그 식별자는 `docs-taxonomy.yml`과 기여 지침에서 관리한다. 같은 대상을 `aks`, `azure-kubernetes-service`처럼 중복 생성하지 않는다. 새 식별자가 필요하면 문서와 같은 PR에서 taxonomy를 갱신한다.

홈, 생성 색인, 기여 지침과 템플릿을 제외한 모든 공개 기술 문서는 `official_sources`를 가진다. 현재 저장소의 Azure 중심 범위에서는 Microsoft 제품 동작이나 지원 상태를 설명하는 모든 문서가 `learn.microsoft.com`의 관련 원문을 하나 이상 포함해야 한다. Kubernetes, CNCF 프로젝트 또는 SDK의 세부 동작처럼 Microsoft Learn이 최종 권위가 아닌 주장에는 `kubernetes.io`, `cncf.io` 또는 해당 프로젝트 공식 문서를 추가하되 Microsoft Learn 교차 검증을 생략하지 않는다. 사례의 환경별 관측값과 타임라인은 공식 문서가 증명하는 사실로 취급하지 않고 별도 증거로 구분한다.

### 7.2 문제 해결 사례

사례 문서는 특정 시점의 사실과 의사결정을 보존한다.

추가 필드:

```yaml
document_type: case
occurred_at: 2026-03-10
resolved_at: 2026-03-12
status: resolved
related_guides:
  - /guides/azure-kubernetes-service/file-io-diagnosis/
```

허용 상태는 `unresolved`, `resolved`, `historical`이다.

본문 순서:

1. 요약
2. 발생 환경과 영향
3. 증상과 관측 데이터
4. 조사 과정 또는 타임라인
5. 근본 원인
6. 해결 방법
7. 검증 결과
8. 재발 방지와 교훈
9. 관련 최신 가이드
10. 참고 자료

제품 동작이 바뀌더라도 당시 사실을 현재 동작에 맞게 다시 쓰지 않는다. 대신 상태를 `historical`로 변경하거나 상단 안내문과 최신 가이드 링크를 추가한다.

### 7.3 일반 가이드

가이드는 현재 시점에 재사용할 수 있는 권장 절차를 제공하며 제품 기능 변경에 따라 같은 문서를 갱신한다.

추가 필드:

```yaml
document_type: guide
status: current
last_verified: 2026-09-12
review_cycle_days: 180
applies_to:
  - AKS 1.34+
related_cases:
  - /cases/azure-kubernetes-service/pod-database-query-latency/
```

허용 상태는 `current`, `needs-review`, `deprecated`이다.

본문 순서:

1. 목표
2. 적용 범위와 지원 버전
3. 사전 조건
4. 권장 아키텍처 또는 선택 근거
5. 구성·운영 절차
6. 검증 방법
7. 롤백과 트러블슈팅
8. 제약 사항과 버전별 차이
9. 관련 사례
10. 공식 참고 자료

가이드가 대체되면 삭제하지 않고 `deprecated` 상태와 대체 문서 링크를 표시한다. `last_verified`는 실제 절차나 동작을 재검증했을 때만 갱신한다.

### 7.4 실습

실습은 재현 가능한 실행 흐름과 비용·안전 경계를 가진다.

추가 필드:

```yaml
document_type: lab
status: verified
last_verified: 2026-09-12
estimated_time: 45m
cost: paid
cleanup_required: true
```

허용 상태는 `verified`, `needs-review`, `broken`, `archived`이다.

본문에는 목표, 사전 조건, 비용과 안전, 배포, 시나리오, 예상 결과, 검증, 정리, 문제 해결을 포함한다.

### 7.5 리서치

리서치는 조사 기준 시점과 근거를 명시한다.

추가 필드:

```yaml
document_type: research
status: current
published_at: 2026-08-24
sources_checked_at: 2026-08-24
official_sources:
  - title: Microsoft Learn article title
    url: https://learn.microsoft.com/...
```

허용 상태는 `current`, `superseded`, `archived`이다.

본문에는 질문, 조사 범위와 기준일, 방법, 결과, 권고, 한계, 출처를 포함한다.

### 7.6 혼합 문서 분리

실제 장애 이력과 재사용 가능한 해결 절차가 섞인 기존 문서는 두 문서로 분리한다.

```text
cases/aks/netapp-file-io-wait/
└── 당시 환경, 관측값, 조사, 근본 원인과 해결 결과

guides/aks/file-io-diagnosis/
└── 현재 유효한 진단 절차, 권장 설정, 검증과 롤백
```

두 페이지는 `related_guides`와 `related_cases`로 연결한다. 사례는 이력을 보존하고 가이드는 제품 변경에 맞춰 갱신한다.

## 8. 검색과 분류

Material for MkDocs의 내장 `search` 플러그인을 사용한다.

- 검색 언어는 `ko`와 `en`을 활성화한다.
- 제목, 본문, 섹션 제목을 검색 결과에 포함한다. `description`은 페이지 상단 요약으로 렌더링해 검색 인덱스에도 포함한다.
- 검색 결과는 해당 문서 섹션 앵커로 이동한다.
- 검색 제안과 결과 강조를 활성화한다.
- 태그는 각 문서에 렌더링해 전체 텍스트 인덱스에도 들어가게 하고, 별도 태그 색인에서 태그별 문서를 탐색할 수 있게 한다.
- 서비스와 태그는 별도 색인 페이지에서 교차 탐색에 사용한다.
- 설계 문서, 원시 캡처 타임라인, 알림 원문, 템플릿 내부 예제는 검색에서 제외한다.
- 검색 인덱스는 빌드 결과에 포함되며 브라우저에서 동작한다.

현재 문서 규모에서는 외부 Algolia, Typesense 또는 서버 측 검색을 도입하지 않는다.

따라서 초기 버전의 필수 검색 범위는 다음과 같다.

- 제목, 본문과 섹션의 한국어·영어 전체 텍스트 검색
- 태그 이름 검색 및 태그별 문서 목록 탐색
- 서비스별 문서 목록 탐색

### 8.1 선택적 공식 사이트 검색 연결

로컬 결과가 없을 때 Microsoft Learn, CNCF와 Kubernetes 공식 사이트로 탐색을 이어 주는 기능은 초기 완료 조건에 포함하지 않는다. 정적 Pages 브라우저에서 MCP를 직접 호출하거나 각 사이트를 크롤링하지 않는다.

후속 기능으로 구현할 때는 `docs-search-providers.yml`에 제공자 이름, 공식 도메인과 검색 URL 템플릿을 선언하고, 검색 UI는 이 데이터에서 외부 검색 링크를 만든다. 제공자별 URL을 JavaScript에 하드코딩하지 않는다. 실제 외부 문서 제목과 직접 링크까지 로컬 결과처럼 보여 주려면 각 사이트의 이용 정책과 공식 색인 제공 여부를 확인한 뒤 예약 빌드에서 제목·URL 전용 색인을 생성하는 별도 설계를 거친다. CORS를 우회하기 위한 비공식 프록시나 검색 결과 스크래핑은 사용하지 않는다.

## 9. Microsoft Learn 기반 문서 검증 하네스

### 9.1 MCP 연결

Microsoft 공식 문서가 안내하는 원격 Streamable HTTP 엔드포인트를 워크스페이스 MCP 설정에 등록한다.

```json
{
  "servers": {
    "microsoft.docs.mcp": {
      "type": "http",
      "url": "https://learn.microsoft.com/api/mcp"
    }
  }
}
```

이 연결은 인증 없이 사용할 수 있는 공개 Microsoft Learn 콘텐츠를 대상으로 한다. MCP 엔드포인트는 일반 REST API가 아니므로 스크립트가 HTTP 응답 형식을 직접 가정하지 않는다. 클라이언트는 세션 시작 시 `tools/list`로 현재 도구와 스키마를 조회하고, repository skill은 도구의 설명을 기준으로 검색과 원문 조회를 선택한다. 알려진 도구 이름은 설명과 예시에만 사용할 수 있으며 하네스 코드의 고정 라우팅 조건으로 사용하지 않는다.

### 9.2 Repository skill

`.github/skills/verify-with-microsoft-learn/SKILL.md`는 공개 기술 문서를 새로 만들거나 기술 내용을 변경할 때 적용한다. skill은 다음 순서를 강제한다.

1. 변경 문서에서 제품 동작, 지원 여부, 제한, 버전, 구성 단계와 CLI/API 사용법 같은 검증 대상 주장을 추출한다.
2. 연결 시 발견한 Microsoft Learn 검색 도구로 제품명과 핵심 주장별 문서를 찾는다.
3. 검색 요약만 신뢰하지 않고 선택한 Microsoft Learn 원문을 전체 조회한다.
4. 문서의 주장과 공식 원문의 적용 범위, 버전, 전제 조건 및 지원 상태를 비교한다.
5. 불일치하면 현재 문서를 수정하거나, 의도적인 역사 기록이면 사례 문서에 시점과 차이를 명시한다.
6. 사용한 원문의 제목과 정규 URL을 `official_sources`에 기록하고 `sources_checked_at`을 실제 확인일로 갱신한다.
7. Microsoft Learn만으로 판단할 수 없는 Kubernetes·CNCF·오픈소스 세부 사항은 해당 프로젝트 공식 원문으로 한 번 더 검증한다.
8. 검증하지 못한 주장을 통과한 것으로 표시하지 않고 `verification_status: needs-review`와 이유를 보고한다.

skill은 검색 결과의 내용을 그대로 문서에 복사하지 않으며, 출처 URL만 추가하는 형식적 검사를 검증 완료로 간주하지 않는다. 사람과 에이전트가 같은 규칙을 사용하도록 기여 페이지와 루트 `AGENTS.md`에서 이 skill을 필수 절차로 연결한다.

### 9.3 결정적 CI와 의미 검증의 경계

`validate_sources.py`와 GitHub Actions는 다음 항목을 결정적으로 검사한다.

- 공개 기술 문서에 `sources_checked_at`과 `official_sources`가 있는지
- 모든 공개 기술 문서에 유효한 `https://learn.microsoft.com/` URL이 하나 이상 있는지
- 출처 항목에 제목이 있고 URL의 호스트가 선언된 공식 출처 정책에 맞는지
- 출처 확인일이 미래가 아니며 `verification_status`와 검토 주기 규칙에 맞는지
- 변경된 기술 문서가 필요한 검증 메타데이터를 함께 갱신했는지

CI가 출처 URL 존재만으로 본문의 의미적 정확성을 보장한다고 주장하지 않는다. 실제 주장 비교는 MCP를 사용할 수 있는 작성·리뷰 에이전트가 repository skill에 따라 수행하고, CI는 그 결과가 남긴 구조화된 메타데이터와 문서 상태를 검사한다. 향후 GitHub Actions에서 인증된 에이전트 실행 환경을 안정적으로 제공할 수 있을 때만 의미 검증을 필수 원격 잡으로 승격한다.

## 10. 빌드와 배포

### 10.1 Pull Request 검사

`.github/workflows/docs-ci.yml`은 문서 또는 사이트 구성 변경이 포함된 Pull Request에서 다음 순서로 실행한다. 같은 워크플로의 예약 실행은 배포 없이 문서 신선도 보고만 수행한다.

1. 저장소 체크아웃
2. 고정된 문서 빌드 의존성 설치
3. front matter 스키마와 통제 어휘 검사
4. 공식 출처 필드와 Microsoft Learn URL 정책 검사
5. 내부 문서 링크와 이미지 경로 검사
6. 이미지 대체 텍스트 검사
7. 생성 내비게이션과 색인에 변경 문서가 포함되는지 검사
8. `mkdocs build --strict`

PR 검사는 Pages 배포 권한을 갖지 않는다.

### 10.2 `main` 배포

`.github/workflows/pages.yml`은 `main`에 문서 또는 사이트 구성 변경이 병합될 때 실행한다.

```text
checkout
  -> dependency install
  -> metadata/link validation
  -> mkdocs build --strict
  -> configure Pages
  -> upload site/ as Pages artifact
  -> deploy to github-pages environment
```

워크플로 권한은 최소 범위로 제한한다.

```yaml
permissions:
  contents: read
  pages: write
  id-token: write
```

동시 배포는 Pages 전용 concurrency group으로 직렬화한다. 생성된 `site/` 디렉터리와 검색 인덱스는 커밋하지 않는다. 별도 `gh-pages` 브랜치도 사용하지 않는다.

### 10.3 재현성

- `requirements-docs.txt`에 문서 도구 버전을 고정한다.
- GitHub Actions는 검토된 버전 또는 변경 불가능한 커밋 참조를 사용한다.
- 로컬과 CI 모두 같은 `mkdocs build --strict` 명령을 사용한다.

## 11. 문서 신선도

가이드와 실습은 `last_verified`와 `review_cycle_days`를 사용한다.

- 새 가이드와 실습은 두 값을 반드시 포함한다.
- 사이트는 모든 가이드와 실습에 현재 `status`와 `last_verified`를 표시한다.
- `status: needs-review`인 문서는 페이지 상단에 검토 필요 안내를 표시한다.
- 오래된 문서 한 개 때문에 전체 Pages 배포를 차단하지 않는다.
- 변경된 문서의 필수 값 누락이나 잘못된 날짜는 PR을 차단한다.
- `docs-ci.yml`의 예약 실행은 주기적으로 검토 기한이 지난 문서 목록을 Actions 요약에 출력한다.
- 검토 기한이 지난 문서를 확인한 유지관리자는 실제 검증을 수행하거나 `status: needs-review`로 변경한다.
- 제품 동작을 재검증하지 않은 단순 문구 수정은 `last_verified`를 갱신하지 않는다.

초기 구현에서는 자동 이슈 생성이나 담당자 알림 시스템을 추가하지 않는다.

## 12. README, 기여 지침과 에이전트 규칙

### 12.1 README

루트 README는 다음 내용만 간결하게 제공한다.

- 저장소와 공개 사이트의 목적
- GitHub Pages 사이트 링크
- 네 문서 모음 설명
- 로컬 미리보기 명령
- 기여 지침 링크
- 공개 정보 취급 주의사항

전체 문서 목록은 README에 수동으로 복제하지 않는다.

### 12.2 기여 지침

사이트의 `docs/contributing/index.md`를 상세 작성 규칙의 기준 문서로 사용한다. 루트 `CONTRIBUTING.md`는 GitHub에서 쉽게 찾을 수 있는 짧은 진입점이며 상세 페이지를 연결한다.

기여 지침에는 다음을 포함한다.

- 문서 유형 선택 기준
- 유형별 front matter와 본문 템플릿
- 서비스와 태그 통제 어휘
- 파일명, URL, 이미지, 링크 규칙
- 코드 블록, Mermaid, 표와 접기 영역 규칙
- 이미지 대체 텍스트와 접근성 기준
- 로컬 미리보기와 검증 명령
- 사례와 일반 가이드를 분리하는 기준
- 공개 전 익명화와 보안 체크리스트
- Microsoft Learn MCP 검증 절차와 공식 출처 작성 규칙
- 문서를 올바른 폴더에 추가한 뒤 자동 메뉴·색인 포함을 확인하는 방법

### 12.3 `AGENTS.md`

루트 `AGENTS.md`는 자동화 에이전트가 따라야 할 실행 가능한 규칙을 담는다.

- 새 문서 작성 전 `document_type` 결정
- 올바른 모음과 서비스 디렉터리 선택
- 유형별 필수 메타데이터와 섹션 준수
- 사례의 역사적 사실과 가이드의 현재 권고 분리
- 문서 전용 이미지는 page bundle의 `images/`에 저장
- 실행 코드는 `samples/`에 저장
- 상대 링크와 이미지 대체 텍스트 사용
- 공개 부적합 정보 제거
- 기술 주장 변경 시 `verify-with-microsoft-learn` skill을 사용하고 공식 출처 메타데이터 갱신
- 변경 후 검증 명령 실행
- 상세 규칙의 기준 문서인 기여 페이지 참조

기여 지침과 `AGENTS.md`에 동일한 긴 내용을 중복하지 않는다. `AGENTS.md`는 필수 계약과 명령을 요약하고, 설명과 예시는 기여 페이지에서 관리한다.

## 13. 공개 안전성

공개 사이트에 게시하는 모든 콘텐츠는 다음 정보를 포함하지 않아야 한다.

- 고객·조직·사용자 실명
- 구독 ID, 테넌트 ID, 리소스의 실제 전체 식별자
- 액세스 키, 토큰, 인증서, 연결 문자열
- 내부 전용 URL, IP 주소, 호스트명
- 원문 로그에 포함된 개인정보나 기밀 데이터
- 공개 승인을 받지 않은 고객 구성도와 화면 캡처

예시는 문서 전반에서 일관된 가상 값으로 치환한다. 자동 비밀 탐지와 함께 사람의 공개 안전성 검토를 PR 체크리스트에 포함한다. 자동 검사만으로 익명화를 보장할 수 있다고 간주하지 않는다.

## 14. 기존 콘텐츠 마이그레이션

마이그레이션은 다음 원칙을 따른다.

1. 기존 문서를 사례, 가이드, 실습, 리서치로 분류한다.
2. 단일 유형 문서는 가능한 한 `git mv`로 이동해 이력을 보존한다.
3. 혼합 문서는 사례와 일반 가이드로 분리하고 상호 링크한다.
4. 문서 전용 이미지는 page bundle로 이동한다.
5. 실행 코드와 인프라 파일은 `samples/`로 이동하고 사이트에서 GitHub 링크로 연결한다.
6. 캡처 원시 산출물과 생성 로그는 내비게이션과 검색에서 제외한다.
7. 외부 공개에 부적합한 식별자와 화면을 익명화한다.
8. 기존 URL 호환성은 유지하지 않으며 새로운 사이트 URL을 기준으로 링크를 갱신한다.

현재 확인된 깨진 링크도 마이그레이션 중 처리한다.

| 원본 문서 | 깨진 대상 |
|---|---|
| `aisearch/custom_vectorization/01_custom_embedding_guide.md` | `indexer_vs_pushapi.png` |
| `aks/spot_gpu_kaito_llm.md` | `workspace-phi4-mini.yaml` |
| `aks/workload_identity_databricks_keyless.md` | `../apim/databricks_keyless_managed_identity.md` |

`.azure/`, `.devcontainer/`, 설계 기록과 저장소 운영 문서는 공개 가이드 모음에 자동 포함하지 않는다.

## 15. 검증 기준

다음 조건을 모두 만족하면 초기 사이트 구축이 완료된 것으로 본다.

1. `https://hellices.github.io/devguidesample/`에서 사이트가 공개된다.
2. 한국어 문구와 영문 제품명으로 검색했을 때 관련 제목과 본문 섹션이 노출된다.
3. 사례, 가이드, 실습, 리서치의 네 모음과 서비스·태그 색인이 제공된다.
4. 공개 문서가 유형에 맞는 필수 front matter를 가진다.
5. 사례형과 가이드형 템플릿이 분명히 다르며 혼합 문서는 분리된다.
6. README, 기여 페이지와 `AGENTS.md`가 사이트 구조와 작성 규칙을 안내한다.
7. Pull Request에서 메타데이터, 링크, 이미지 대체 텍스트와 엄격 빌드가 검사된다.
8. `main` 병합 시 Pages 아티팩트가 자동 배포된다.
9. 저장소에 생성된 `site/` 또는 검색 인덱스가 추적되지 않는다.
10. 공개 사이트에 알려진 비밀이나 실제 고객 식별 정보가 포함되지 않는다.
11. 새 문서를 규칙에 맞는 폴더에 추가하면 문서별 nav 수정 없이 메뉴, 모음, 서비스 및 태그 색인에 나타난다.
12. 태그 이름과 한국어·영어 본문으로 관련 문서를 찾을 수 있다.
13. 워크스페이스에서 Microsoft Learn MCP를 연결할 수 있고 repository skill이 검색, 원문 조회, 주장 비교와 출처 기록을 안내한다.
14. 공개 기술 문서는 Microsoft Learn 공식 근거와 마지막 확인일을 가지며 CI가 이를 검사한다.

## 16. 위험과 대응

| 위험 | 대응 |
|---|---|
| 공개 과정에서 민감 정보 노출 | 자동 비밀 탐지와 사람의 익명화 검토를 모두 요구한다. |
| 대량 이동으로 링크 손상 | 마이그레이션 단위마다 엄격 빌드와 링크 검사를 실행한다. |
| 문서 분류가 모호함 | 사건 시점의 사실이면 사례, 현재 재사용할 절차이면 가이드로 분리하고 둘 다 필요하면 두 페이지로 만든다. |
| 가이드가 제품 변화에 뒤처짐 | 검증일, 검토 주기, 상태 배너와 예약 보고를 사용한다. |
| 전체 nav 수동 관리 비용 | `mkdocs-awesome-nav`의 분산 `.nav.yml`과 자동 포함을 사용한다. |
| 검색 인덱스 크기 증가 | 초기에는 로컬 검색을 사용하고 실제 성능 문제가 관측될 때만 외부 검색을 평가한다. |
| MCP 도구 이름이나 스키마 변경 | 연결 시 `tools/list`로 동적 발견하고 도구별 요청 형식을 코드에 고정하지 않는다. |
| URL만 추가하고 실제 내용을 검증하지 않음 | skill이 검색 후 원문 조회와 주장 비교를 요구하며 CI 메타데이터 검사는 의미 검증을 대체하지 않는다고 명시한다. |
| 외부 공식 검색을 정적 사이트에서 무리하게 통합 | 초기 범위에서는 공식 검색 링크만 확장점으로 설계하고, 제목 색인은 정책 확인 후 예약 빌드 방식으로 별도 구현한다. |

## 17. 공식 설계 근거

- [Microsoft Learn MCP Server overview](https://learn.microsoft.com/en-us/training/support/mcp): 공개 원격 서버, Streamable HTTP 엔드포인트, 인증 요구 사항과 제한을 확인했다.
- [Get started with the Microsoft Learn MCP Server](https://learn.microsoft.com/en-us/training/support/mcp-get-started): 워크스페이스 연결, 권장 에이전트 지침과 검색·원문·코드 샘플 도구 사용 방식을 확인했다.
- [Microsoft Learn MCP Server developer reference](https://learn.microsoft.com/en-us/training/support/mcp-developer-reference): 엔드포인트 구성 형식과 도구 목록을 세션마다 조회해야 한다는 계약을 확인했다.
- [Best practices for using the Microsoft Learn MCP Server](https://learn.microsoft.com/en-us/training/support/mcp-best-practices): 도구 이름, 매개변수와 동작을 하드코딩하지 않고 `tools/list`로 동적 발견해야 한다는 지침을 확인했다.
- [Add and manage MCP servers in VS Code](https://code.visualstudio.com/docs/agent-customization/mcp-servers): `.vscode/mcp.json`의 `servers` 구조, 소스 관리 가능한 워크스페이스 설정과 Agent Host 전달 동작을 확인했다.

## 18. 확정된 사용자 결정

- 사이트는 외부 공개용이다.
- 기존 Markdown 경로를 보존할 필요가 없다.
- 루트 README에서 새 GitHub Pages 사이트를 소개한다.
- 기여 지침을 별도 사이트 페이지로 제공한다.
- Markdown 작성 규칙을 `AGENTS.md`에도 실행 가능한 형태로 정리한다.
- 실제 문제 해결 이력과 지속 갱신형 일반 가이드를 별도 모음과 문서 형식으로 관리한다.
- GitHub Pages는 Material for MkDocs와 GitHub Actions 기반으로 구성한다.
- 문서와 메뉴는 폴더·메타데이터 기반으로 자동 포함하며 문서별 하드코딩을 최소화한다.
- 태그 기반 탐색과 한국어·영어 전체 텍스트 검색을 필수로 제공한다.
- 문서 검증 하네스는 Microsoft Learn 공식 문서를 반드시 참조하고 이를 위한 MCP 연결과 repository skill을 제공한다.
- Azure 서비스 폴더는 `azure-`와 공식 전체 제품명으로 통일하고, Microsoft 제품과 오픈소스는 공식 명칭을 사용한다.
- 내부 설계와 구현 계획은 `project/specs/`와 `project/plans/`에 두어 공개 Pages 소스와 분리한다.
- 로컬 검색 결과가 없을 때 Microsoft Learn, CNCF와 Kubernetes 공식 검색으로 연결하는 기능은 선택 사항이다.
