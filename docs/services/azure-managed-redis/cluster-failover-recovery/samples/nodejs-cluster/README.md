# Node.js cluster failover sample

이 sample은 [재연결 실패 사례](../../index.md)의 이전 연결 설정을
살펴보는 실험 자료입니다. 5.x 계열 클라이언트와 짧은 연결 timeout을
보존하므로 현재 운영 환경에 그대로 배포하는 템플릿이 아닙니다.
현재 연결 구현은 [Node.js 가이드](../../../clustering-policies/nodejs/index.md)를
사용합니다.

## 사용과 검증

1. [실행 안내](cluster_example/README.md)에 따라 `cluster_example/`에서
   `npm ci`로 lockfile의 의존성을 설치합니다.
2. 별도 테스트 캐시의 `REDIS_URL`, `REDIS_ACCESS_KEY`와 실행 모드를
   설정합니다. `REDIS_MODE`는 코드 분기이며 캐시의 실제 정책을 바꾸지 않습니다.
3. 상태 확인 후 읽기·쓰기 테스트의 성공·실패와 복구 시점을 관찰합니다.
   모니터링 API가 Azure의 유지보수나 노드 교체를 발생시키는 것은 아닙니다.

과거 동작 비교용 자료이므로 새 버전의 복구 성능이나 사건의 원인을
이 sample만으로 입증하지 않습니다. 실제 운영 환경이나 업무 데이터에
테스트를 실행하지 않습니다.

## 정리

실행한 Node.js 프로세스를 종료하고 해당 실험에서 만든 테스트 키만
정리합니다. 별도로 만든 테스트 캐시를 더 이상 사용하지 않으면 삭제하고,
접근 키나 로그를 저장소에 남기지 않습니다.
