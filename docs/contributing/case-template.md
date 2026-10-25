---
title: 문제 해결 사례 템플릿
description: 시점 고정 문제 해결 이력을 작성하는 형식입니다.
---

# 문제 해결 사례 템플릿

## Front matter

```yaml
---
title: 발생한 문제와 확인된 대응·결과를 담은 제목
description: 증상, 영향과 해결을 요약한 한 문장
document_type: case
services: [azure-kubernetes-service]
technologies: [kubernetes]
tags: [diagnose]
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

대괄호는 해당 절에서 다룰 내용의 역할입니다.
[제목 작성 기준](index.md#content-first-headings)에 따라 실제 본문의 핵심을
담은 제목으로 바꿉니다. 원인이 확정되지 않았다면 제목에서도 가설로 구분합니다.

```markdown
# [발생한 문제와 확인된 대응·결과]
## [핵심 증상과 복구 상태]
## [장애가 발생한 구성과 영향 범위]
## [로그와 수치에서 확인된 증상]
## [원인 판단에 영향을 준 사건의 순서]
## [확인된 원인 또는 검증 중인 가설]
## [복구를 위해 적용한 조치]
## [조치 후 관측된 변화와 남은 문제]
## [재발을 막기 위한 조건과 조치]
## 관련 최신 가이드
## 참고 자료
```
