# HorizonDB 문서 계층 정리 설계

## 목적

Azure HorizonDB topic을 처음부터 순서대로 읽을 때 같은 설명을 반복하지 않고, 독자가 소개 → 기술 상세 → 재현 실습 → 실행 코드 순서로 자연스럽게 이동하게 한다.

## 문서별 책임

1. `movielog-graph-vector/index.md`는 topic entry다. HorizonDB의 제품 성격, 벡터·그래프 결합 가치, 대표 기능, MovieLog 결과와 대표 실측값, 다음 문서 선택만 설명한다.
2. `vector-graph-features/index.md`는 기술 가이드다. pgvector 거리 연산, index 선택, DiskANN, AGE 저장·질의, graph-augmented RAG, Learn과 실습 cluster 차이를 상세히 설명한다. MovieLog 구현은 기술을 설명하는 짧은 예시에만 쓴다.
3. `movielog-lab/index.md`는 실습 해설이다. 학습 목표, 아키텍처와 데이터 흐름, 실행 후 확인할 항목, 구현을 읽는 순서와 관측 결과를 설명한다. 복사해 실행할 명령, 파일 목록, 환경값과 장애 대응은 외부 sample 저장소의 README와 `docs/deploy.md`가 소유한다.
4. `sample-movielog-horizondb` 저장소는 실행 가능한 코드와 정확한 배포·테스트 절차의 단일 출처다.

## 읽기 순서

상위 문서 첫 부분에서 다음 경로를 명시한다.

1. HorizonDB와 적용 결과를 빠르게 이해한다.
2. 벡터·그래프 기능의 선택 기준과 제약을 기술 가이드에서 읽는다.
3. MovieLog로 데이터 흐름과 검증 지점을 실습 문서에서 따라간다.
4. 실행할 때 고정 버전 sample README와 배포 문서를 사용한다.

## 편집 원칙

- 기존 관측값과 공식 출처는 새 사실을 만들지 않고 해당 책임 문서로 이동하거나 링크한다.
- 상위 문서에는 세부 SQL, DiskANN parameter, AGE 저장 구조, 앱 class와 배포 단계 목록을 두지 않는다.
- 기술 가이드에는 배포 방법, 앱 화면 구현과 운영 절차를 두지 않는다.
- 실습 문서에는 sample README와 같은 clone·로그인·`azd` 명령, 저장소 파일 목록, 릴리스 절차를 반복하지 않는다.
- 기존 URL과 주요 anchor를 가능한 한 유지한다.
- 모든 절 제목은 저장소의 핵심 용어 명사구 기준을 따른다.

## 검증

저장소가 요구하는 docs pytest, metadata/source/link/public-safety validator, strict MkDocs build, search-index validator를 모두 실행한다. 렌더링된 목차가 소개 → 기술 상세 → 실습 순서를 보여 주고, 문서 간 링크와 고정 버전 sample 링크가 유효해야 한다.
