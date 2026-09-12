---
title: 기여하기
description: DevGuideSample 문서 유형, 구조, 검증과 공개 안전성 규칙입니다.
---

# 기여하기

이 페이지가 공개 문서 작성 규칙의 기준입니다. 루트 `CONTRIBUTING.md`와 `AGENTS.md`는 이 규칙의 짧은 진입점과 실행 계약만 제공합니다.

## 문서 유형 선택

| 질문 | 모음 | 수명주기 |
|---|---|---|
| 특정 시점에 무엇이 발생했고 어떻게 해결했나? | 문제 해결 사례 (`cases`) | 당시 사실을 보존하고 필요하면 `historical`로 표시 |
| 지금 같은 문제를 어떻게 진단·구성해야 하나? | 일반 가이드 (`guides`) | 제품 변화에 맞춰 같은 문서를 갱신 |
| 독자가 리소스를 배포해 재현할 수 있나? | 실습 (`labs`) | 비용, 검증, 정리 절차까지 재검증 |
| 선택지·성능·아키텍처를 어떤 기준으로 비교했나? | 리서치 (`research`) | 조사 기준일과 한계를 보존 |

실제 장애 이력과 재사용 가능한 절차가 섞여 있으면 두 문서로 분리합니다. 사례에는 당시 환경·관측·결과를, 가이드에는 현재 지원 범위·권장 절차·검증·롤백을 두고 `related_cases`와 `related_guides`로 연결합니다.

## 폴더만으로 자동 게시하기

```text
docs/<collection>/<service>/<topic>/
├── index.md
└── images/
```

URL에 쓰이는 폴더 이름은 소문자 kebab-case 영문으로 작성합니다. Azure 제품의 `<service>`는 `azure-`와 공식 전체 제품명을 조합합니다(예: `azure-kubernetes-service`, `azure-database-for-mysql`). Microsoft 제품은 공식 명칭을 보존하므로 이름이 `Microsoft`로 시작하면 `microsoft-` slug를 사용합니다(예: `microsoft-foundry`). 오픈소스와 그 밖의 제품은 임의의 공급자 접두사를 붙이지 않고 공식 프로젝트·제품명을 사용합니다.

문서를 위 경로에 넣고 유효한 front matter를 작성하면 다음 빌드에서 자동으로 Pages에 포함됩니다.

- Awesome Nav가 폴더에서 메뉴를 발견합니다.
- 생성기가 문서 유형별·서비스별 색인에 추가합니다.
- Material tags가 태그를 페이지와 태그 색인에 표시하고 검색 미리보기에 포함합니다.
- Material search가 한국어와 영어 제목·본문·섹션을 전체 텍스트로 색인합니다.

개별 문서 추가를 위해 `mkdocs.yml`, `docs/.nav.yml`, README 또는 수동 목록을 수정하지 않습니다. 새 서비스·기술·태그 식별자가 필요할 때만 `docs-taxonomy.yml`을 같은 PR에서 한 번 갱신합니다.

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
