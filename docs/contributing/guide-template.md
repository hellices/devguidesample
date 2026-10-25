---
title: 일반 가이드 템플릿
description: 계속 검증하고 갱신하는 기술 가이드 형식입니다.
---

# 일반 가이드 템플릿

## Front matter

```yaml
---
title: 해결할 문제와 핵심 조치를 담은 제목
description: 목표와 적용 범위를 요약한 한 문장
document_type: guide
services: [azure-kubernetes-service]
technologies: [kubernetes]
tags: [diagnose]
status: current
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: 관련 Microsoft Learn 원문 제목
    url: https://learn.microsoft.com/azure/aks/
last_verified: 2026-09-12
review_cycle_days: 180
applies_to: [AKS 1.34+]
related_cases: []
---
```

## 본문 순서

대괄호는 해당 절에서 다룰 내용의 역할입니다.
[제목 작성 기준](index.md#content-first-headings)에 따라 실제 본문의 핵심을
담은 제목으로 바꾸고, 독자가 어떤 판단이나 조치를 해야 하는지 드러냅니다.

```markdown
# [해결할 문제와 핵심 조치]
## [해결하려는 문제와 목표 상태]
## [적용 가능한 구성·버전과 제외 범위]
## [실행에 필요한 환경·권한·접근 조건]
## [선택한 구성과 그 이유]
## [구성할 대상과 핵심 운영 조치]
## [성공을 판단할 관측값과 조건]
## [실패 조건별 복구·롤백 조치]
## [적용을 제한하는 조건과 버전별 차이]
## 관련 사례
## 공식 참고 자료
```
