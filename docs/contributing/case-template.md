---
title: 문제 해결 사례 템플릿
description: 시점 고정 문제 해결 이력을 작성하는 형식입니다.
---

# 문제 해결 사례 템플릿

## Front matter

```yaml
---
title: 사례 제목
description: 증상, 영향과 해결을 요약한 한 문장
document_type: case
services: [aks]
technologies: [kubernetes]
tags: [troubleshooting]
status: resolved
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: 관련 Microsoft Learn 원문 제목
    url: https://learn.microsoft.com/azure/aks/
occurred_at: 2026-09-01
resolved_at: 2026-09-02
related_guides: []
---
```

## 본문 순서

```markdown
# 사례 제목
## 요약
## 발생 환경과 영향
## 증상과 관측 데이터
## 조사 과정과 타임라인
## 근본 원인
## 해결 방법
## 검증 결과
## 재발 방지와 교훈
## 관련 최신 가이드
## 참고 자료
```
