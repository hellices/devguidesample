---
title: 기여하기
description: 서비스 중심 topic package와 샘플, 메타데이터, 검증 규칙
---

<p class="dg-eyebrow">CONTRIBUTING</p>

# 공개 문서 작성 계약

이 페이지는 공개 문서 작성 규칙의 단일 기준입니다. 새 문서와 샘플은 모두
`docs/services/` 아래의 topic package에 둡니다. `cases`, `guides`, `labs`,
`research`는 물리 폴더가 아니라 front matter의 `document_type`과 수명주기
정책으로만 유지합니다.

루트 `README.md`, `AGENTS.md`, `CONTRIBUTING.md`는 이 계약의 요약입니다.

## 문서 유형과 수명주기

| `document_type` | 용도 | 유지 방식 |
|---|---|---|
| `case` | 특정 시점의 증상, 관측, 조사, 원인과 해결 결과 | 당시 사실을 보존하고 필요하면 `historical`로 표시 |
| `guide` | 현재 권장하는 진단·구성 절차 | 지원 상태와 버전 변화에 맞춰 같은 문서를 갱신 |
| `lab` | 배포, 실행, 검증, 정리를 재현하는 실습 | 비용·검증·정리 절차까지 재검증 |
| `research` | 선택지, 성능, 아키텍처 비교 | 조사 기준일, 범위와 한계를 보존 |

당시 증거를 보존할 사례와 계속 갱신할 현재 절차는 분리하고
`related_cases`·`related_guides`로 연결합니다. 비교와 적용 절차가 같은
수명주기라면 하나의 `guide` 또는 `research` 안에 함께 둘 수 있습니다.

## canonical topic package

### 독립 topic

자식 문서가 없는 글은 다음 구조를 사용합니다.

```text
docs/services/<service>/<topic>/
├── index.md
└── images/
    └── <rendered-image>
```

`images/`는 페이지에서 직접 렌더링하는 이미지가 있을 때만 만듭니다.

### 연결된 topic

순서가 있는 여러 문서는 하나의 topic package로 묶습니다.

```text
docs/services/<service>/<topic>/
├── index.md
├── <child-a>/
│   └── index.md
├── <child-b>/
│   └── index.md
├── images/
└── samples/
```

루트 `index.md`가 topic entry입니다. entry에는 `topic_order`를 쓰지 않습니다.
직접 자식 문서에는 `topic_order: 1`, `topic_order: 2`처럼 1부터 시작하는
중복 없는 연속 번호를 지정합니다. 손자 문서 구조는 허용하지 않습니다.
`index`는 topic entry를 가리키는 예약어이므로 자식 폴더 slug로 사용할 수
없습니다.

### topic 소유 sample

실행 코드, 배포 매니페스트, 재현 프로젝트와 대용량 결과물은 이를 사용하는
topic 안에 둡니다.

```text
docs/services/<service>/<topic>/samples/<sample>/
├── sample.yml
├── README.md
└── <source-or-artifact-files>
```

`sample.yml` 형식은 다음과 같습니다.

```yaml
title: Event lab
description: Reproduces the monitored incident.
kind: runnable
used_by:
  - index
  - setup
publish:
  - source: assets/architecture.svg
    target: images/architecture.svg
  - source: assets/architecture.svg
    target: setup/images/architecture.svg
```

- `title`, `description`, `kind`는 비어 있지 않은 문자열입니다.
- `kind`는 `runnable` 또는 `artifact`입니다.
- `used_by`는 sample을 표시할 문서 slug의 중복 없는 목록입니다.
- topic entry는 `index`, 자식 문서는 폴더 slug로 지정합니다.
- 각 sample에는 사용·검증·정리 방법을 설명하는 `README.md`가 필요합니다.
- sample이 있는 topic에는 entry `index.md`가 반드시 있어야 합니다.
  자식 문서 아래에 `samples/`를 두거나 topic의 `samples/` 바로 아래에
  파일을 두지 않습니다. sample package 내부의 하위 `samples/` 폴더는
  해당 package의 payload로 취급합니다.
- sample 원본 폴더는 공개 안전성 검사를 받지만 MkDocs 사이트와 검색 색인에는
  복사되지 않습니다. 문서에서는 생성되는 sample card 또는 GitHub 소스
  링크로 연결합니다.
- 페이지와 sample에서 같은 이미지나 파일을 사용하는 경우 원본은 sample에만
  보관하고 선택적 `publish` 목록에 명시합니다. `source`는 sample package,
  `target`은 소유 topic 루트 기준 상대 경로입니다. 위 예의 페이지 링크는
  각각 `images/architecture.svg`이며 실제 target 파일을 중복 저장하지 않습니다.
- 빌드는 선언한 파일만 원본 바이트 그대로 target에 게시합니다. 텍스트와
  Markdown 파일도 독립 문서나 검색 항목이 아닌 다운로드 자산으로 유지합니다.
  `downloads/index.md` 같은 원본 자산은 해당 파일 경로로 직접 링크합니다.
  `downloads/`처럼 문서 디렉터리로 줄여 쓰면 다운로드 자산을 가리키지 않습니다.
  명시한 target은 숨김 파일이나 숨김 폴더 아래의 파일도 게시하지만,
  선언하지 않은 숨김 파일과 sample 원본 폴더는 계속 제외합니다.
  페이지 본문과 링크 텍스트는 기존처럼 검색됩니다. `used_by`는 sample card의
  표시 위치만 결정하며 `publish`와 독립적입니다.
- `publish`는 생략하거나 빈 목록으로 둘 수 있습니다. 각 항목의 `source`와
  `target`은 비어 있지 않은 문자열이어야 합니다. 절대 경로, `..`, 역슬래시,
  소유 경계를 벗어나는 심볼릭 링크와 존재하지 않는 원본은 허용하지 않습니다.
  target은 `samples/` 아래, canonical 문서와 HTML 출력 경로, 이미 존재하는 파일이나
  디렉터리를 가리킬 수 없습니다. 하나의 원본을 여러 target으로 게시할 수
  있지만 각 target에는 하나의 선언만 허용합니다.
  target 파일은 다른 target이나 canonical 출력 파일의 상위·하위 경로와도
  충돌할 수 없습니다. 기존 파일을 target의 상위 디렉터리처럼 사용할 수 없으며,
  기존 디렉터리 아래에 새 파일을 게시하는 것은 허용합니다.

최상위 `samples/`에는 공개 콘텐츠를 추가하지 않습니다.

## 경로와 redirect 규칙

모든 `<service>`, `<topic>`, `<child>`, `<sample>` slug는 소문자
kebab-case를 사용합니다. Azure 제품의 `<service>`는 `azure-`와 공식 전체
제품명을 조합합니다. 이름이 `Microsoft`로 시작하는 제품은 `microsoft-`
slug를 사용하고, 그 밖의 제품은 공식 프로젝트·제품명을 kebab-case로
표현합니다.

이전 공개 URL을 보존해야 하면 canonical 문서 front matter에 추가합니다.

```yaml
redirect_from:
  - guides/<service>/<old-topic>/index.md
```

redirect 경로는 `cases`, `guides`, `labs`, `research` 중 하나로 시작하는
기존 4단계 `index.md` 경로여야 합니다. 해당 경로에 원본 Markdown을 다시
만들지 않습니다. 빌드가 redirect page를 생성하며 검색과 서비스/topic
탐색에서는 제외합니다.
이전 collection/service 색인 주소도 유지하며, 현재 소속과 이전 소속이
겹치면 canonical 문서를 중복 없이 합칩니다. 이 호환 색인에서는 topic
카드와 함께 해당 자식 문서로 바로 가는 링크도 제공합니다.

`document_type`은 collection 호환 색인과 수명주기 요구사항을 선택하지만
물리 경로를 결정하지 않습니다. `services/`, `explore/`와 collection 호환
색인은 빌드가 생성합니다. `tags/`, `articles/`는 `explore/`로 이동하는
검색 제외 redirect입니다. 개별 문서를 추가하기 위해
`mkdocs.yml`, `docs/.nav.yml`, README 또는 수동 문서 목록을 수정하지
않습니다.

## 글 찾기와 실용 태그

대메뉴는 **홈 · 서비스별 보기 · 글 찾기 · 기여하기**입니다. 글 찾기는
모든 주제를 canonical topic 카드로 묶고 실제 catalog에서 계산한
**주제 수 · 문서 수**를 함께 표시합니다. 여러 문서가 있는 topic도
카드 하나이며 각 문서로 직접 연결합니다.

- 서비스, 목적·주제별 태그, 기술은 front matter 값과 정확히 일치해야 합니다.
- 태그 하나를 선택하면 해당 태그가 붙은 문서만 표시합니다. 여러 태그,
  서비스, 기술은 **같은 문서에 AND**로 적용합니다. 서로 다른 자식의
  태그를 합쳐서 일치한다고 판단하지 않습니다.
- 제목·설명 검색도 같은 문서에 적용합니다. 본문 검색은 사이트의 별도
  전체 텍스트 검색을 사용합니다.
- 일치하지 않는 문서 행과 일치 문서가 없는 topic 카드는 숨깁니다.
  JavaScript가 없으면 안내와 함께 모든 topic과 문서 링크를 표시합니다.
- 선택 조건은 반복 가능한 `tag`, `service`, `technology`, `q` query로
  공유합니다. 알 수 없는 필터 값은 경고 후 제외하고 초기화하면 선택과
  검색어, query를 모두 지웁니다.
- 문서와 카드의 태그 링크는 `explore/?tag=<slug>`로 연결합니다.

문서의 `tags`는 아래 통제 값에서 **1–4개** 선택합니다. 중복을 제거하고
목적 태그를 주제 태그보다 먼저 배치합니다. 기술 분류와 중복되는
`kubernetes`는 태그가 아니라 `technologies`로 지정합니다.

| 그룹 | 값 |
|---|---|
| 목적 | `design` 설계 · `build` 구현 · `deploy` 배포 · `diagnose` 진단 · `optimize` 최적화 · `operate` 운영 · `secure` 보안 · `evaluate` 비교·검증 · `migrate` 마이그레이션 |
| 주제 | `ai-agents` AI agents · `networking` 네트워킹 · `identity` ID·권한 · `storage` 스토리지 |

태그를 추가할 때는 `docs-taxonomy.yml`의 `tags`와 `tag_groups`를 함께
수정하고 실제 문서에 적용합니다. 각 태그는 그룹 하나에 정확히 한 번
등장해야 하며 미사용 태그는 허용하지 않습니다. `legacy_tag_redirects`는
이전 `/tags/<slug>/` 주소를 새 필터로 변환하는 taxonomy 소유 매핑입니다.
예를 들어 `authentication`은 `identity`와 `secure` 두 태그로,
`kubernetes`는 기술 필터로 이동합니다. 이 redirect는 검색·메뉴에서
제외하며 문서마다 legacy 태그를 저장하지 않습니다.

## 세 가지 작성 workflow

### 1. 독립 topic 추가

1. `docs/services/<service>/<topic>/index.md`를 만듭니다.
2. 공통 front matter와 선택한 `document_type`의 필수 필드를 채웁니다.
3. 렌더링 이미지가 있으면 같은 bundle의 `images/`에 두고 의미 있는 대체
   텍스트를 작성합니다.
4. 새 taxonomy 값이 있을 때만 `docs-taxonomy.yml`을 수정합니다.
5. 필수 검증을 모두 실행합니다.

### 2. 연결된 topic 추가 또는 확장

1. topic entry를 `docs/services/<service>/<topic>/index.md`에 둡니다.
2. 직접 자식마다 `<child>/index.md`를 만들고 연속 `topic_order`를
   지정합니다.
3. 이전 URL이 있으면 각 canonical 문서에 고유한 `redirect_from`을
   기록합니다.
4. topic 안의 링크는 canonical `.md` 상대 경로로 작성합니다.
5. entry 목차, 이전·다음 이동, 서비스 메뉴가 자동 생성되는지 strict build로
   확인합니다.

### 3. sample 추가

1. `docs/services/<service>/<topic>/samples/<sample>/`을 만듭니다.
2. `sample.yml`과 `README.md`를 먼저 작성하고 `used_by` 소유 문서를
   지정합니다.
3. 코드·매니페스트·결과물을 같은 sample 폴더에 둡니다.
4. 실제 식별자와 비밀을 가상 값으로 치환합니다.
5. public-safety 검사가 sample을 검사하고 strict build의 `site/`에는 sample
   원본 폴더가 없는지 확인합니다. `publish`를 사용하면 선언한 target만
   게시되며 원본과 바이트가 같은지도 확인합니다.

## 공통 front matter

```yaml
---
title: AKS 네트워크 진단
description: AKS 네트워크 문제를 진단하는 현재 절차
document_type: guide
services: [azure-kubernetes-service]
technologies: [kubernetes]
tags: [diagnose, networking]
status: current
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: Azure Kubernetes Service documentation
    url: https://learn.microsoft.com/azure/aks/
last_verified: 2026-09-12
review_cycle_days: 180
applies_to: [AKS 1.34+]
---
```

`services`, `technologies`, `tags`와 유형별 `status`는
`docs-taxonomy.yml`의 값을 사용합니다. 유형별 전체 형식은
[사례 템플릿](case-template.md), [가이드 템플릿](guide-template.md),
[실습 템플릿](lab-template.md), [리서치 템플릿](research-template.md)을
사용합니다. 홈에 소개할 topic entry에는 `featured: true`를 지정할 수
있습니다.

## 공식 출처 검증

Microsoft 또는 Azure의 동작, 지원 상태, 제한, 버전, 구성 단계나 CLI/API
사용법을 추가하거나 바꿀 때 repository skill `verify-with-microsoft-learn`을
사용합니다. Microsoft Learn 검색 결과만 인용하지 말고 선택한 원문 전체를
확인하여 주장, 적용 범위와 전제 조건을 비교합니다.

실제로 확인한 원문의 제목과 정규 URL을 `official_sources`에 기록하고
`sources_checked_at`을 확인일로 갱신합니다. 중요한 주장을 모두 확인했을
때만 `verification_status: verified`로 표시합니다. 검증을 완료하지 못하면
`verification_status: needs-review`로 남깁니다. Kubernetes·CNCF 세부
동작은 필요한 경우 upstream 공식 문서도 함께 확인합니다.

## 본문과 공개 안전성

- 페이지마다 하나의 H1을 사용하고 H2/H3 순서를 건너뛰지 않습니다.
- 문서 링크는 canonical `.md` 상대 경로를 사용합니다.
- 렌더링 이미지는 같은 bundle의 `images/`에 두고 대체 텍스트를 씁니다.
- 고객·조직·사용자 실명, 구독·테넌트 ID, 키·토큰·인증서·연결 문자열,
  내부 URL·IP·호스트명, 개인정보가 포함된 로그와 승인되지 않은 화면을
  게시하지 않습니다.
- 실제 식별자는 문서와 sample 전체에서 일관된 가상 값으로 치환합니다.
- `.azure/`, `.claude/`, `.DS_Store`, `sim-env.json`, 실행 중 생성된
  `evidence/`는 커밋하지 않습니다.

## 필수 검증

저장소 루트에서 다음을 모두 실행합니다.

```powershell
python -m pytest tests/docs -q
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
```

생성된 `site/`과 검색 인덱스는 커밋하지 않습니다. 실패한 검증을 무시하지
않습니다.
