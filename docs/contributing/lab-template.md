---
title: 실습 템플릿
description: 재현 가능한 배포·검증·정리 실습 형식입니다.
---

# 실습 템플릿

## Front matter

```yaml
---
title: 실습 제목
description: 배포하고 확인할 동작을 요약한 한 문장
document_type: lab
services: [azure-monitor]
technologies: [bicep]
tags: [deployment, monitoring]
status: verified
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: 관련 Microsoft Learn 원문 제목
    url: https://learn.microsoft.com/azure/azure-monitor/
last_verified: 2026-09-12
review_cycle_days: 90
estimated_time: 45m
cost: paid
cleanup_required: true
---
```

## 본문 순서

```markdown
# 실습 제목
## 목표
## 사전 조건
## 비용과 안전 경계
## 배포
## 시나리오 실행
## 예상 결과
## 검증
## 정리
## 문제 해결
## 공식 참고 자료
```
