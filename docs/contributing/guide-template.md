---
title: 일반 가이드 템플릿
description: 계속 검증하고 갱신하는 기술 가이드 형식입니다.
---

# 일반 가이드 템플릿

## Front matter

```yaml
---
title: 가이드 제목
description: 목표와 적용 범위를 요약한 한 문장
document_type: guide
services: [azure-kubernetes-service]
technologies: [kubernetes]
tags: [diagnostics]
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

```markdown
# 가이드 제목
## 목표
## 적용 범위와 지원 버전
## 사전 조건
## 권장 아키텍처와 선택 근거
## 구성과 운영 절차
## 검증 방법
## 롤백과 트러블슈팅
## 제약 사항과 버전별 차이
## 관련 사례
## 공식 참고 자료
```
