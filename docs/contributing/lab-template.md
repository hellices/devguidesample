---
title: 실습 템플릿
description: 재현 가능한 배포·검증·정리 실습 형식입니다.
---

# 실습 템플릿

## Front matter

```yaml
---
title: 재현할 동작과 확인할 결과를 담은 제목
description: 배포하고 확인할 동작을 요약한 한 문장
document_type: lab
services: [azure-monitor]
technologies: [bicep]
tags: [deploy, operate]
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

대괄호는 해당 절에서 다룰 내용의 역할입니다.
[제목 작성 기준](index.md#content-first-headings)에 따라 실제 본문의 핵심을
담은 제목으로 바꾸고, 실행 대상과 관측할 결과를 구체적으로 밝힙니다.

```markdown
# [재현할 동작과 확인할 결과]
## [실습으로 확인하려는 동작]
## [준비할 환경과 권한]
## [비용이 발생하는 자원과 실행 제한]
## [배포할 구성 요소와 순서]
## [주입할 조건과 실행할 작업]
## [예상되는 응답·로그·관측값]
## [예상 결과와 실제 결과의 판정 기준]
## [삭제할 자원과 정리 완료 조건]
## [대표 오류와 대응 조치]
## 공식 참고 자료
```
