---
title: 기여하기
description: 재현할 수 있는 환경과 코드, 판단의 근거를 갖춘 기술 기록을 기여하는 방법
---

<p class="dg-eyebrow">CONTRIBUTING</p>

# 코드와 근거를 함께 남겨주세요

어떤 환경에서 무엇을 관측했고, 왜 그 방법을 선택했는지까지 적어주세요. 다음 사람이 같은 조건을 재현하고, 자신의 환경에도 적용할 수 있는지 판단하는 데 도움이 됩니다.

<div class="dg-contribution-steps" markdown="1">

1. **글의 성격을 고릅니다.** 특정 시점의 문제 해결, 재사용할 절차, 직접 해보는 실습, 선택지를 비교한 분석 중 어디에 해당하는지 정합니다.
2. **환경과 근거를 남깁니다.** 코드·관측값·공식 출처를 정리하고, 확인하지 못한 부분은 구분합니다.
3. **공개 전에 검증합니다.** 링크와 빌드 결과를 확인하고 실제 환경의 식별자나 비밀이 남아 있지 않은지 살펴봅니다.

</div>

이 페이지가 공개 문서 작성 규칙의 기준입니다. 루트 `CONTRIBUTING.md`와 `AGENTS.md`는 핵심 규칙과 실행할 검증 명령을 안내합니다.

## 문서 유형 선택

| 질문 | 모음 | 수명주기 |
|---|---|---|
| 특정 시점에 무엇이 발생했고 어떻게 해결했나? | 트러블슈팅 (`cases`) | 당시 사실을 보존하고 필요하면 `historical`로 표시 |
| 지금 같은 문제를 어떻게 진단·구성해야 하나? | 구현 가이드 (`guides`) | 제품 변화에 맞춰 같은 문서를 갱신 |
| 독자가 리소스를 배포해 재현할 수 있나? | 실습 (`labs`) | 비용, 검증, 정리 절차까지 재검증 |
| 선택지·성능·아키텍처를 어떤 기준으로 비교했나? | 비교·분석 (`research`) | 조사 기준일과 한계를 보존 |

문서 유형은 폴더·메타데이터와 보존·갱신 정책을 위한 내부 분류입니다. 독자 메뉴와 카드에는 유형을 표시하지 않고, 같은 서비스의 글을 유형 구분 없이 함께 보여줍니다.

`guides`와 `research`에는 서로 연결된 비교·분석과 적용 절차를 함께 담을 수 있습니다. 비교와 구현이 함께 있다는 이유만으로 글을 나누지 않고, 문서의 주된 목적에 맞춰 유형을 선택합니다.

당시의 증거를 보존할 장애 이력과 계속 갱신할 현재 절차처럼 수명주기가 다르면 두 문서로 분리합니다. 사례에는 당시 환경·관측·결과를, 가이드에는 현재 지원 범위·권장 절차·검증·롤백을 두고 `related_cases`와 `related_guides`로 연결합니다.

## 폴더만으로 자동 게시하기

```text
docs/<collection>/<service>/<topic>/
├── index.md
└── images/
```

URL에 쓰이는 폴더 이름은 소문자 kebab-case 영문으로 작성합니다. Azure 제품의 `<service>`는 `azure-`와 공식 전체 제품명을 조합합니다(예: `azure-kubernetes-service`, `azure-database-for-mysql`). Microsoft 제품은 공식 명칭을 보존하므로 이름이 `Microsoft`로 시작하면 `microsoft-` slug를 사용합니다(예: `microsoft-foundry`). 오픈소스와 그 밖의 제품은 임의의 공급자 접두사를 붙이지 않고 공식 프로젝트·제품명을 사용합니다.

문서를 위 경로에 넣고 유효한 front matter를 작성하면 다음 빌드에서 자동으로 Pages에 포함됩니다.

- Awesome Nav의 glob fallback이 원본 페이지를 발견하고, 빌드 훅이 URL을 바꾸지 않은 채 서비스별 메뉴에 배치합니다.
- 생성기가 서비스별·태그별·전체 글 목록과 기존 문서 유형별 색인을 갱신합니다.
- 생성기와 훅이 문서·카드의 태그 링크와 태그별 목록을 만듭니다. Material tags는 메타데이터 처리를 유지하되 기본 태그·목록 UI는 표시하지 않습니다.
- Material search가 한국어와 영어 제목·본문·섹션을 전체 텍스트로 색인합니다.

대메뉴는 **홈 · 서비스별 보기 · 태그별 보기 · 전체 글 · 기여하기**입니다. 사이드바의 주요 글 경로는 **서비스별 보기 → 서비스 → 문서**이며, 모든 수명주기 유형의 글을 함께 배치합니다. 문서 이름은 front matter의 `title`, 서비스 이름은 taxonomy를 사용합니다. bundle 폴더를 별도 메뉴 단계로 노출하지 않고, 각 그룹은 접고 펼칠 수 있으며 현재 읽는 문서의 경로만 기본으로 열립니다. 큰 화면에서는 전체 사이드바를, 작은 화면에서는 햄버거 메뉴를 제공합니다. 메뉴 데이터는 빌드 결과에 포함되므로 브라우저가 Markdown을 다시 읽어 구성하지 않습니다.

서비스 목록은 front matter의 `services`에 지정한 모든 서비스를 반영합니다. 여러 서비스와 관련된 글은 각 서비스 목록에서 찾을 수 있지만, 사이드바에는 bundle 경로의 `<service>`를 대표 서비스로 삼아 원본 글을 한 번만 배치합니다. 서비스 제목은 유형을 섞은 해당 서비스의 글 목록으로 연결되고, 하위 메뉴의 문서 링크는 기존 원문 URL을 그대로 사용합니다.

태그 탐색은 **태그별 보기 → 해당 태그의 글 목록 → 원문** 순서입니다. 문서 상단과 카드의 태그도 검색 화면이 아니라 같은 태그별 목록으로 연결합니다. 목록에는 해당 태그가 front matter의 `tags`에 정확히 지정된 글만 포함합니다. 태그 개요에는 실제로 사용된 태그와 각 태그의 실제 글 수를 자동으로 표시하며, `전체 글`에는 각 원본 글을 한 번만 표시합니다.

`services/index.md`·`services/<slug>/index.md`, `tags/index.md`·`tags/<slug>.md`, `articles/index.md`는 빌드 시 생성됩니다. 기존 유형별 색인과 `docs/<collection>/<service>/index.md`에 해당하는 서비스 색인, 기존 원문·서비스 URL도 호환성을 위해 유지하지만 유형별 대메뉴는 만들지 않습니다. 작성자는 이 색인 파일이나 별도의 `docs/tags.md`를 직접 추가하지 않습니다.

개별 문서 추가를 위해 `mkdocs.yml`, `docs/.nav.yml`, README 또는 수동 목록을 수정하지 않습니다. 새 서비스·기술·태그 식별자가 필요할 때만 `docs-taxonomy.yml`을 같은 PR에서 한 번 갱신합니다.

| 추가하거나 바꾸려는 것 | 작성자가 수정할 곳 |
|---|---|
| 기존 서비스·태그를 사용하는 새 글 | 해당 bundle의 `index.md` |
| 글에서 보여줄 이미지 | 해당 bundle의 `images/` |
| 처음 사용하는 서비스·기술·태그 | 새 글과 `docs-taxonomy.yml` |
| 메뉴·목록·검색에 새 글 노출 | 별도 수정 없음 — 빌드가 처리 |

홈에 소개할 글은 해당 문서의 front matter에 `featured: true`를 지정합니다. 홈의 대표 글은 이 메타데이터에서 최대 세 편을 고르며, 지정한 글이 없으면 문서 유형별로 글을 골라 보여줍니다. 이때 문서 유형은 내부 선택 기준이며, 독자 메뉴나 카드에서 유형을 구분해 표시하지 않습니다. 빌드가 문서·서비스·사용된 태그 수와 서비스·태그·전체 글 탐색 카드도 자동으로 생성합니다. 홈이나 생성기에 특정 문서·서비스·태그 목록을 하드코딩하지 않습니다.

## 공통 front matter

```yaml
---
title: AKS 네트워크 진단
description: AKS 네트워크 문제를 진단하는 현재 절차
document_type: guide
services: [azure-kubernetes-service]
technologies: [kubernetes]
tags: [networking, troubleshooting]
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

`services`, `technologies`, `tags`와 유형별 `status`는 `docs-taxonomy.yml`의 값을 사용합니다. 제목은 한국어여도 제품명, API, 명령과 오류 메시지는 공식 영문 표기를 함께 써 검색 가능하게 합니다.

유형별 전체 형식은 [사례 템플릿](case-template.md), [가이드 템플릿](guide-template.md), [실습 템플릿](lab-template.md), [리서치 템플릿](research-template.md)을 사용합니다.

## Microsoft Learn MCP로 기술 주장 검증하기

워크스페이스의 `.vscode/mcp.json`은 공식 Microsoft Learn MCP 서버를 연결합니다. Microsoft 또는 Azure의 제품 동작, 지원 상태, 제한, 버전, 구성 단계나 CLI/API 사용법을 작성할 때 repository skill `verify-with-microsoft-learn`을 사용합니다.

1. 변경한 문장에서 검증 가능한 주장을 나눕니다.
2. MCP가 현재 제공하는 도구 설명을 조회하고 Microsoft Learn을 검색합니다.
3. 검색 요약으로 끝내지 않고 관련 원문 전체를 가져옵니다.
4. 적용 범위, 전제 조건, 버전, 지원 상태와 제한을 본문의 주장과 비교합니다.
5. 실제 사용한 원문의 제목과 정규 URL을 `official_sources`에 기록하고 `sources_checked_at`을 확인일로 갱신합니다.
6. 모든 중요한 주장이 맞을 때만 `verification_status: verified`로 표시합니다.

Kubernetes나 CNCF 프로젝트 구현처럼 Microsoft Learn이 최종 권위가 아닌 세부 사항은 `kubernetes.io`, `cncf.io` 또는 해당 프로젝트 공식 원문도 추가합니다. 검증을 끝내지 못한 문서는 `verification_status: needs-review`로 표시합니다. 자동 CI는 필드와 도메인을 검사하지만 본문의 의미를 대신 판단하지 않습니다.

## 본문과 파일 규칙

- 페이지마다 하나의 H1을 사용하고 H2/H3 순서를 건너뛰지 않습니다.
- 코드 블록에는 언어를 지정하고 비밀·실제 식별자를 넣지 않습니다.
- 문서 간 링크는 `.md` 소스 상대 경로를, 페이지 이미지는 `images/<file>` 상대 경로를 사용합니다.
- 모든 이미지에 내용을 설명하는 대체 텍스트를 작성합니다.
- 실행 코드와 배포 파일은 `samples/<service>/<topic>/`에 두고 GitHub 파일 링크로 연결합니다.
- 원시 로그, 캡처 타임라인과 생성 결과는 문서가 아니라 sample/evidence로 보관합니다.

## 공개 안전성

고객·조직·사용자 실명, 구독·테넌트 ID, 키·토큰·인증서·연결 문자열, 내부 URL·IP·호스트명, 개인정보가 포함된 로그와 승인되지 않은 고객 화면을 게시하지 않습니다. `validate_public_safety.py`가 환경 고유 식별자의 대표 패턴을 검사하지만, 자동 검사와 별개로 사람이 원문과 이미지를 확인해야 합니다.

`.azure/`의 개인별 작업 상태, `.claude/`, `.DS_Store`, `sim-env.json`, 실습 실행으로 생성된 `evidence/`는 커밋하지 않습니다. 공유 개발 설정과 `.env.example` 같은 예제 입력은 유지하고, 공개할 관측 자료는 비식별화한 뒤 문서 또는 샘플 자료로 별도 정리합니다. 이미 Git이 추적 중인 로컬 파일은 `.gitignore`에 추가하는 것만으로 제외되지 않으므로, 파일을 로컬에 보존한 채 추적을 해제해야 합니다.

## 로컬 검증

```powershell
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
```

`main`에 병합되면 GitHub Actions가 같은 검사를 다시 실행하고 생성된 `site/`을 Pages artifact로 배포합니다. 생성 HTML과 검색 인덱스는 Git에 커밋하지 않습니다.
