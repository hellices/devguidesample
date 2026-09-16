# Java LTS 버전 선택과 현대화 가이드 설계

## 목적

운영 중인 Java 8 또는 17 서비스를 Java 21 또는 25로 전환하려는 백엔드
팀이 다음 질문에 답할 수 있는 공개 기술 가이드를 작성한다.

- Java 8, 17, 21, 25에서 실무에 영향을 주는 주요 변화는 무엇인가?
- 신규 서비스와 기존 서비스는 어떤 LTS 버전을 선택해야 하는가?
- 최신 JDK가 성능에 유리할 수 있는 이유와 보장할 수 없는 부분은 무엇인가?
- 버전을 올린 뒤 어떤 순서와 코드 패턴으로 현대화해야 하는가?

## 산출물

- canonical topic:
  `docs/services/application-development/java-lts-version-selection/index.md`
- 문서 유형: `guide`
- 대표 서비스: `application-development`
- 기술: `java`
- 태그: `evaluate`, `migrate`, `optimize`
- sample과 이미지는 추가하지 않는다.
- 기존 taxonomy 값으로 충분하므로 새 서비스, 기술, 태그는 추가하지 않는다.

## 대상 독자와 전제

주 독자는 Java 8 또는 17 기반의 운영 서비스를 보유하고 있으며, 지원 기간,
호환성, 성능과 개발 생산성을 함께 고려해 다음 LTS를 선택해야 하는 백엔드
개발·플랫폼 팀이다. 특정 클라우드, 프레임워크 또는 JDK 배포판에 종속되지
않는 결정을 돕는다.

문서에서 “LTS”는 Java SE 또는 OpenJDK 프로젝트가 모든 배포판에 일괄
부여하는 속성이 아니라 JDK 공급자의 지원 정책이라는 점을 먼저 밝힌다.
지원 기간은 실제로 선택한 배포판의 정책을 별도로 확인하도록 안내한다.

## 콘텐츠 구조

### 1. 결론과 빠른 선택표

문서 첫 부분에서 조건별 기본 선택을 제시한다.

- Java 8: 애플리케이션이나 상용 제품 제약으로 즉시 이전할 수 없는 기존
  시스템에만 유지한다.
- Java 17: 의존성 또는 플랫폼이 21 이상을 아직 인증하지 않은 경우의
  호환성 전환점으로 사용한다.
- Java 21: 생태계 성숙도와 현대 기능의 균형을 중시하는 기존 서비스의
  보수적인 기본 선택으로 사용한다.
- Java 25: 런타임·프레임워크·관측 도구가 지원하고 검증을 통과한 신규
  서비스 또는 장기 운영 서비스의 우선 후보로 사용한다.

이는 절대 규칙이 아니다. 배포판 지원 기간, 프레임워크 최소·최대 버전,
라이브러리와 에이전트 호환성, 롤백 가능성, 워크로드 벤치마크를 최종
결정 조건으로 둔다.

### 2. 버전별 주요 기능

모든 JEP를 나열하지 않고, 코딩 방식이나 운영 특성을 바꾸는 기능만 네
범주로 요약한다.

| 버전 | 언어·모델링 | 표준 API | 동시성 | JVM·GC |
|---|---|---|---|---|
| 8 | lambda, method reference, default method | Stream, Optional, `java.time` | `CompletableFuture` | Metaspace, 당시 기본 GC 변화 |
| 17 | record, sealed class, pattern matching for `instanceof`, switch expression, text block | 표준 HTTP Client 등 9~17의 누적 변화 | 기존 executor 중심 | G1 성숙, 저지연 GC 선택지와 컨테이너 인식 개선 |
| 21 | record pattern, pattern matching for `switch` | sequenced collections | virtual thread | generational ZGC |
| 25 | 22~25에서 확정된 API·언어 기능과 25의 주요 기능 | 최신 표준 API 변화 | scoped value 등 확정 상태를 확인한 기능 | compact object headers 등 25의 주요 런타임 변화 |

각 항목은 최종 확정 기능과 preview/incubator 기능을 명시적으로 구분한다.
Java 17과 21, 25는 직전 LTS 이후 누적된 기능이라는 점도 표에 표시한다.
정확한 JEP 번호와 최종 상태는 집필 시 공식 원문으로 다시 확인한다.

### 3. 최신 버전이 성능에 유리할 수 있는 이유

성능을 “버전 번호만 올리면 자동 향상”으로 설명하지 않는다. 다음 경로를
분리해 설명한다.

- JIT와 런타임 최적화가 장기 실행 처리량과 코드 생성 품질에 미치는 영향
- G1, ZGC 등 GC 개선이 pause time, 처리량, 힙 크기와 메모리 사용량에
  미치는 영향
- compact object headers 같은 메모리 레이아웃 변화가 객체가 많은
  워크로드에 미칠 수 있는 영향
- virtual thread가 blocking I/O 서비스의 동시성 비용을 줄일 수 있지만
  CPU-bound 연산 자체를 빠르게 만들지는 않는다는 경계
- 컨테이너 자원 인식과 진단 기능 개선이 운영 안정성에 주는 간접 효과

워크로드, 힙 크기, GC, JVM 옵션, 워밍업, 프레임워크 버전이 다르면 결과가
달라지므로 숫자로 된 보편적 향상률은 제시하지 않는다.

### 4. 버전 업그레이드와 현대화 패턴

업그레이드를 두 단계로 분리한다.

1. **호환성 단계**: 목표 JDK에서 기존 동작을 유지한다. 빌드 도구,
   프레임워크, 라이브러리, Java agent, 제거된 모듈·API, 강한 캡슐화,
   JVM 옵션을 먼저 점검하고 회귀·부하 테스트를 통과시킨다.
2. **현대화 단계**: 안정 기능을 작은 변경 단위로 도입한다. 기능 전환과
   런타임 전환을 한 번에 섞지 않아 회귀 원인과 롤백 경계를 명확히 한다.

본문에는 다음 전후 패턴을 짧은 코드로 제시한다.

- 불변 DTO와 값 객체: 보일러플레이트 class에서 `record`로 전환
- 닫힌 도메인 모델: 상속 가능한 class 계층에서 `sealed` 계층으로 전환
- 타입 분기: cast 중심 `instanceof` 연쇄에서 pattern matching으로 전환
- 값 계산 분기: statement형 `switch`에서 exhaustive switch expression으로
  전환
- blocking I/O fan-out: 고정 thread pool을 무조건 크게 만드는 방식에서
  virtual-thread-per-task 실행기로 전환

virtual thread 예제에는 요청별 무제한 외부 호출을 허용하지 않고 semaphore,
connection pool 또는 대상 시스템의 용량에 맞춘 별도 동시성 제한이
필요하다고 설명한다. preview 기능은 운영 기본 패턴에서 제외하고 별도
참고로만 다룬다.

### 5. 측정과 도입 체크리스트

동일한 애플리케이션과 트래픽으로 다음을 비교하도록 한다.

- 처리량과 오류율
- p50, p95, p99 latency
- 시작 시간과 warm-up 구간
- CPU 사용량, RSS, heap 사용량
- GC pause, allocation rate, collection 빈도

기준 JDK와 목표 JDK에서 프레임워크·의존성, 컨테이너 제한, JVM 옵션,
GC와 테스트 데이터를 기록한다. 운영 반영은 canary 또는 점진적 배포로
진행하고 JDK 이미지와 JVM 옵션을 함께 되돌릴 수 있는 롤백 조건을 둔다.

## 주장과 출처 원칙

- 언어와 JVM 기능은 OpenJDK JEP 원문과 JDK 릴리스 자료를 우선한다.
- LTS 지원 기간은 특정 공급자의 공식 지원 정책으로 한정해 표현한다.
- 저장소의 현재 출처 검증 계약을 만족하도록 Microsoft Learn의 Java
  지원 자료를 포함하고, OpenJDK의 공식 GitHub JEP 원문을 함께 사용한다.
- 실제로 전문을 확인한 문서만 `official_sources`에 기록한다.
- 중요한 기능 상태와 적용 범위를 모두 확인한 경우에만
  `verification_status: verified`로 표시한다. 확인이 불완전하면
  `needs-review`로 남긴다.
- 출처 확인 기준일은 `2026-09-16`으로 기록한다.

## 비목표

- Java 8 이후 모든 JEP의 완전한 목록
- 특정 JDK 배포판의 가격 또는 전체 지원 기간 비교
- Spring Boot, Jakarta EE 등 프레임워크별 상세 호환성 행렬
- 근거 데이터가 없는 보편적 성능 향상률
- preview 기능을 사용하는 운영 코드 권장
- 실행 가능한 벤치마크 sample 제공

## 검증

내용 작성 뒤 다음을 확인한다.

1. 각 기능의 도입 버전과 final/preview/incubator 상태를 공식 원문과
   대조한다.
2. 버전 선택 문구가 조건부 권장이고 배포판 지원 정책을 일반화하지
   않았는지 검토한다.
3. 코드 예제가 해당 기능이 final인 최소 버전과 일치하는지 확인한다.
4. 저장소 루트에서 필수 문서 검증을 모두 실행한다.

```text
python -m pytest tests/docs -q
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
python scripts/docs/audit_pre_pages.py
```

생성된 `site/`와 검색 인덱스 산출물은 커밋하지 않는다.
