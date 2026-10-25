---
title: 리서치 템플릿
description: 비교·벤치마크·아키텍처 조사 형식입니다.
---

# 리서치 템플릿

## Front matter

```yaml
---
title: 비교 대상과 핵심 차이·결론을 담은 제목
description: 질문, 비교 대상과 결론을 요약한 한 문장
document_type: research
services: [azure-ai-search]
technologies: [rag]
tags: [evaluate]
status: current
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: 관련 Microsoft Learn 원문 제목
    url: https://learn.microsoft.com/azure/search/
published_at: 2026-09-12
---
```

## 본문 순서

대괄호는 해당 절에서 다룰 내용의 역할입니다.
[제목 작성 기준](index.md#content-first-headings)에 따라 실제 본문의 핵심을
담은 제목으로 바꿉니다. 관측된 차이와 해석의 한계를 제목에서도 구분합니다.

```markdown
# [비교 대상과 핵심 차이·결론]
## [비교할 대상과 판단할 질문]
## [결과가 유효한 버전·환경·기준일]
## [비교에 사용한 방법과 조건]
## [관측된 차이와 근거]
## [요구 조건에 따른 선택 기준]
## [해석을 제한하는 조건과 미확인 사항]
## 공식 출처
```
