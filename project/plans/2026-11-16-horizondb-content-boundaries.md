# HorizonDB Content Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HorizonDB topic을 소개, 기술 상세, 실습 해설, 실행 sample의 네 계층으로 정리해 중복 없이 순서대로 읽게 한다.

**Architecture:** topic entry는 제품 가치와 탐색 경로만 소유하고, 기능 guide는 HorizonDB 기술 계약을, lab은 MovieLog 데이터 흐름과 검증 포인트를 소유한다. 외부 sample README와 배포 문서는 실행 명령과 저장소 운영 절차의 단일 출처로 유지한다.

**Tech Stack:** MkDocs Material, Markdown, 저장소 docs validator, pytest

## Global Constraints

- 기존 공개 URL과 주요 anchor를 유지한다.
- 새 Azure 제품 주장을 추가하지 않는다. 기존 `verification_status: needs-review`를 유지한다.
- 제목은 핵심 용어 명사구로 쓴다.
- sample 링크는 `v2.7.1` 고정 ref를 유지한다.
- 생성된 `site/`는 커밋하지 않는다.

---

### Task 1: Topic entry를 소개와 읽기 허브로 축소

**Files:**
- Modify: `docs/services/azure-horizondb/movielog-graph-vector/index.md`

**Interfaces:**
- Consumes: 기존 자식 문서 anchor와 sample `v2.7.1` 링크
- Produces: 소개 → 기술 가이드 → 실습 → sample의 읽기 경로

- [ ] **Step 1:** 첫 절에 HorizonDB의 가치, MovieLog 결과, 대표 측정값을 유지한다.
- [ ] **Step 2:** 벡터·그래프·AI 기능은 요약 표로 줄이고 세부 설명을 기술 가이드로 연결한다.
- [ ] **Step 3:** MovieLog 구현은 적용 구성과 결과만 남기고 데이터 모델·앱 구현은 실습으로 연결한다.
- [ ] **Step 4:** 기존 주요 anchor와 공식 출처를 확인한다.

### Task 2: 기술 가이드의 책임을 HorizonDB 기능 상세로 한정

**Files:**
- Modify: `docs/services/azure-horizondb/movielog-graph-vector/vector-graph-features/index.md`

**Interfaces:**
- Consumes: entry의 기능 요약 링크
- Produces: pgvector·DiskANN·AGE 선택과 동작의 상세 설명

- [ ] **Step 1:** 서두에 대상 독자와 앞뒤 읽기 순서를 명시한다.
- [ ] **Step 2:** MovieLog 중복 설명을 실측 근거 또는 짧은 적용 예시로만 남긴다.
- [ ] **Step 3:** 배포·앱 구현 설명은 lab 링크로 대체한다.
- [ ] **Step 4:** 기존 기술 anchor와 Learn 차이 표를 유지한다.

### Task 3: 실습 문서를 학습 흐름과 검증 중심으로 축소

**Files:**
- Modify: `docs/services/azure-horizondb/movielog-graph-vector/movielog-lab/index.md`

**Interfaces:**
- Consumes: entry의 MovieLog 적용 요약과 sample `v2.7.1`
- Produces: 아키텍처 → 데이터 준비 → 검색 → 그래프 → 관측의 실습 해설

- [ ] **Step 1:** 실행 명령은 sample README와 배포 문서 링크로 대체한다.
- [ ] **Step 2:** 데이터 모델과 작성 순서는 학습·검증에 필요한 수준으로 유지한다.
- [ ] **Step 3:** 코드 전문과 class 목록은 고정 버전 코드 링크와 읽기 순서로 대체한다.
- [ ] **Step 4:** 그래프 화면·관측 결과와 정리 검증은 유지한다.

### Task 4: 문서 계약과 렌더링 검증

**Files:**
- Test: `tests/docs`

**Interfaces:**
- Consumes: Tasks 1–3의 Markdown
- Produces: 배포 가능한 strict MkDocs site

- [ ] **Step 1:** `python -m pytest tests/docs -q`를 실행해 실패 0건을 확인한다.
- [ ] **Step 2:** metadata, source, link, public-safety validator를 실행해 exit code 0을 확인한다.
- [ ] **Step 3:** `mkdocs build --strict`와 search-index validator를 실행해 exit code 0을 확인한다.
- [ ] **Step 4:** `git diff --check`와 변경 파일 diff를 검토한다.
- [ ] **Step 5:** conventional docs commit을 만들고 branch를 push한 뒤 PR을 연다.
- [ ] **Step 6:** PR에 Copilot review를 요청하고 CI 상태를 확인한다.
