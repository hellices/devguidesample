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

## 3. 비목표

초기 구현에서는 다음 항목을 포함하지 않는다.

- 로그인 또는 CSA 팀 전용 접근 제어
- 서버 측 검색, 벡터 검색, RAG 또는 질의응답 챗봇
- 사용자 댓글, 평가, 분석용 서버
- 사용자 지정 도메인
- 기존 Markdown 파일 경로 또는 GitHub 링크의 호환성 보존
- 모든 코드 샘플을 사이트 안에서 직접 실행하는 기능

## 4. 핵심 결정

| 항목 | 결정 | 근거 |
|---|---|---|
| 사이트 생성기 | Material for MkDocs | 기존 Markdown과 호환되고 한국어를 지원하는 내장 클라이언트 검색을 제공한다. |
| 배포 | GitHub Actions 기반 GitHub Pages | 빌드 결과를 브랜치에 커밋하지 않고 Pages 아티팩트로 배포할 수 있다. |
| 검색 | MkDocs `search` 플러그인, `ko`와 `en` | 별도 외부 검색 서비스 없이 제목, 본문, 섹션을 브라우저에서 검색한다. |
| 분류 색인 | Material `tags`와 빌드 시 생성하는 서비스 색인 | front matter를 기준으로 문서를 자동 모아 수동 목록의 누락을 막는다. |
| 정보 구조 | 문서 유형 우선, 서비스와 태그는 교차 색인 | 문서 수명주기를 분명히 하면서 서비스별 탐색도 제공한다. |
| 내비게이션 | `mkdocs-awesome-nav`와 분산된 `.nav.yml` | 전체 문서 목록을 한 파일에 수동 관리하지 않고 새 문서를 자동 포함한다. |
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
│   ├── assets/
│   └── superpowers/specs/
├── samples/
│   └── <service>/<topic>/
├── scripts/docs/
│   ├── generate_indexes.py
│   └── validate_metadata.py
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

`docs/superpowers/specs/`는 설계 기록용이며 공개 내비게이션과 검색 인덱스에서 제외한다. `docs-taxonomy.yml`은 서비스, 기술과 태그의 허용 식별자를 관리하는 단일 기준 파일이다.

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

URL과 디렉터리 이름은 소문자 kebab-case 영문을 사용한다.

```text
/cases/aks/pod-database-query-latency/
/guides/aks/file-io-diagnosis/
/labs/azure-monitor/sre-agent-event-lab/
/research/ai-search/chunking-strategies/
```

제목과 본문은 한국어를 기본으로 하되 제품명, API, 오류 메시지 등 검색에 유용한 공식 영문 용어를 함께 표기한다.

### 6.4 서비스와 태그 색인 생성

`scripts/docs/generate_indexes.py`는 공개 문서의 front matter를 읽어 서비스별 문서 목록을 빌드 시 생성한다. `mkdocs-gen-files`를 사용해 가상 Markdown 페이지를 만들기 때문에 생성된 색인 파일은 작업 트리나 Git에 남기지 않는다. 태그 색인은 Material의 `tags` 플러그인이 생성한다.

새 문서는 올바른 `services`와 `tags`만 지정하면 해당 색인에 자동 포함된다. 사람이 서비스별 문서 목록을 중복 편집하지 않는다.

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

서비스, 기술과 태그 식별자는 `docs-taxonomy.yml`과 기여 지침에서 관리한다. 같은 대상을 `aks`, `azure-kubernetes-service`처럼 중복 생성하지 않는다. 새 식별자가 필요하면 문서와 같은 PR에서 taxonomy를 갱신한다.

### 7.2 문제 해결 사례

사례 문서는 특정 시점의 사실과 의사결정을 보존한다.

추가 필드:

```yaml
document_type: case
occurred_at: 2026-03-10
resolved_at: 2026-03-12
status: resolved
related_guides:
  - /guides/aks/file-io-diagnosis/
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
  - /cases/aks/pod-database-query-latency/
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
- 서비스와 태그는 별도 색인 페이지에서 교차 탐색에 사용한다.
- 설계 문서, 원시 캡처 타임라인, 알림 원문, 템플릿 내부 예제는 검색에서 제외한다.
- 검색 인덱스는 빌드 결과에 포함되며 브라우저에서 동작한다.

현재 문서 규모에서는 외부 Algolia, Typesense 또는 서버 측 검색을 도입하지 않는다.

## 9. 빌드와 배포

### 9.1 Pull Request 검사

`.github/workflows/docs-ci.yml`은 문서 또는 사이트 구성 변경이 포함된 Pull Request에서 다음 순서로 실행한다. 같은 워크플로의 예약 실행은 배포 없이 문서 신선도 보고만 수행한다.

1. 저장소 체크아웃
2. 고정된 문서 빌드 의존성 설치
3. front matter 스키마와 통제 어휘 검사
4. 내부 문서 링크와 이미지 경로 검사
5. 이미지 대체 텍스트 검사
6. `mkdocs build --strict`

PR 검사는 Pages 배포 권한을 갖지 않는다.

### 9.2 `main` 배포

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

### 9.3 재현성

- `requirements-docs.txt`에 문서 도구 버전을 고정한다.
- GitHub Actions는 검토된 버전 또는 변경 불가능한 커밋 참조를 사용한다.
- 로컬과 CI 모두 같은 `mkdocs build --strict` 명령을 사용한다.

## 10. 문서 신선도

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

## 11. README, 기여 지침과 에이전트 규칙

### 11.1 README

루트 README는 다음 내용만 간결하게 제공한다.

- 저장소와 공개 사이트의 목적
- GitHub Pages 사이트 링크
- 네 문서 모음 설명
- 로컬 미리보기 명령
- 기여 지침 링크
- 공개 정보 취급 주의사항

전체 문서 목록은 README에 수동으로 복제하지 않는다.

### 11.2 기여 지침

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

### 11.3 `AGENTS.md`

루트 `AGENTS.md`는 자동화 에이전트가 따라야 할 실행 가능한 규칙을 담는다.

- 새 문서 작성 전 `document_type` 결정
- 올바른 모음과 서비스 디렉터리 선택
- 유형별 필수 메타데이터와 섹션 준수
- 사례의 역사적 사실과 가이드의 현재 권고 분리
- 문서 전용 이미지는 page bundle의 `images/`에 저장
- 실행 코드는 `samples/`에 저장
- 상대 링크와 이미지 대체 텍스트 사용
- 공개 부적합 정보 제거
- 변경 후 검증 명령 실행
- 상세 규칙의 기준 문서인 기여 페이지 참조

기여 지침과 `AGENTS.md`에 동일한 긴 내용을 중복하지 않는다. `AGENTS.md`는 필수 계약과 명령을 요약하고, 설명과 예시는 기여 페이지에서 관리한다.

## 12. 공개 안전성

공개 사이트에 게시하는 모든 콘텐츠는 다음 정보를 포함하지 않아야 한다.

- 고객·조직·사용자 실명
- 구독 ID, 테넌트 ID, 리소스의 실제 전체 식별자
- 액세스 키, 토큰, 인증서, 연결 문자열
- 내부 전용 URL, IP 주소, 호스트명
- 원문 로그에 포함된 개인정보나 기밀 데이터
- 공개 승인을 받지 않은 고객 구성도와 화면 캡처

예시는 문서 전반에서 일관된 가상 값으로 치환한다. 자동 비밀 탐지와 함께 사람의 공개 안전성 검토를 PR 체크리스트에 포함한다. 자동 검사만으로 익명화를 보장할 수 있다고 간주하지 않는다.

## 13. 기존 콘텐츠 마이그레이션

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

## 14. 검증 기준

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

## 15. 위험과 대응

| 위험 | 대응 |
|---|---|
| 공개 과정에서 민감 정보 노출 | 자동 비밀 탐지와 사람의 익명화 검토를 모두 요구한다. |
| 대량 이동으로 링크 손상 | 마이그레이션 단위마다 엄격 빌드와 링크 검사를 실행한다. |
| 문서 분류가 모호함 | 사건 시점의 사실이면 사례, 현재 재사용할 절차이면 가이드로 분리하고 둘 다 필요하면 두 페이지로 만든다. |
| 가이드가 제품 변화에 뒤처짐 | 검증일, 검토 주기, 상태 배너와 예약 보고를 사용한다. |
| 전체 nav 수동 관리 비용 | `mkdocs-awesome-nav`의 분산 `.nav.yml`과 자동 포함을 사용한다. |
| 검색 인덱스 크기 증가 | 초기에는 로컬 검색을 사용하고 실제 성능 문제가 관측될 때만 외부 검색을 평가한다. |

## 16. 확정된 사용자 결정

- 사이트는 외부 공개용이다.
- 기존 Markdown 경로를 보존할 필요가 없다.
- 루트 README에서 새 GitHub Pages 사이트를 소개한다.
- 기여 지침을 별도 사이트 페이지로 제공한다.
- Markdown 작성 규칙을 `AGENTS.md`에도 실행 가능한 형태로 정리한다.
- 실제 문제 해결 이력과 지속 갱신형 일반 가이드를 별도 모음과 문서 형식으로 관리한다.
- GitHub Pages는 Material for MkDocs와 GitHub Actions 기반으로 구성한다.
