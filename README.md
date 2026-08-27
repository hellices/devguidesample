# DevGuideSample

> Microsoft CSA(Customer Success Architect) 팀을 위한 Azure 기술 가이드 및 이슈 해결 사례 저장소

## 📌 저장소 소개

이 저장소는 한국 지역에서 발생하는 다양한 Azure 관련 기술 이슈와 솔루션을 체계적으로 정리하고 공유하기 위한 목적으로 만들어졌습니다. Microsoft CSA 팀이 고객 지원 과정에서 경험한 실제 사례와 베스트 프랙티스를 문서화하여, 팀원들 간의 지식 공유와 빠른 문제 해결을 돕습니다.

## 📚 문서 목록

아래 표는 저장소 구조에서 자동으로 생성됩니다. **문서를 추가할 때 이 표를 직접 고치지 마세요.**
생성 규칙과 갱신 방법은 [문서 작성 규칙](AGENTS.md)에 있습니다.

<!-- BEGIN:categories -->
| 카테고리 | 문서 | 들어가는 곳 |
|---|---:|---|
| [`aifoundry`](aifoundry/) | 3 | — |
| [`aisearch`](aisearch/) | 7 | [Azure AI Search Custom Web API를 활용한 외부 임베딩 모델 통합 벡터화 가이드](aisearch/custom_vectorization/02_custom_vectorization.md) |
| [`aisearch-v2`](aisearch-v2/) | 1 | [Azure AI Search 한국어 분석기(Analyzer) 비교 가이드](aisearch-v2/README.md) |
| [`aks`](aks/) | 14 | — |
| [`appgw`](appgw/) | 2 | — |
| [`architect`](architect/) | 1 | — |
| [`automation`](automation/) | 1 | — |
| [`azureblob`](azureblob/) | 1 | — |
| [`cosmosdb`](cosmosdb/) | 3 | — |
| [`develop`](develop/) | 1 | — |
| [`hdinsight`](hdinsight/) | 1 | — |
| [`loadtest`](loadtest/) | 1 | — |
| [`memory`](memory/) | 9 | [Agent Memory 가이드 모음](memory/README.md) |
| [`monitor`](monitor/) | 19 | [Azure SRE Agent 소개](monitor/azure-sre-agent.md) |
| [`mysql`](mysql/) | 2 | — |
| [`ptu_lb`](ptu_lb/) | 2 | [PTU LB Test Docs](ptu_lb/README.md) |
| [`redis`](redis/) | 7 | [Azure Cache for Redis → Azure Managed Redis 마이그레이션](redis/azure-cache-to-managed-redis-migration.md) |
<!-- END:categories -->

"들어가는 곳"은 그 카테고리의 `README.md`이거나, 같은 카테고리의 다른 문서를 여럿 링크하는 문서입니다.
`—`는 아직 낱개 문서만 있다는 뜻이므로, 각 디렉터리를 직접 열어 보세요.

## 🧪 실습 랩

문서만 읽는 가이드와 달리, 실제 Azure 리소스를 배포해 직접 돌려 보는 실습입니다. 각 랩은 자체 `azure.yaml`을 가지고 있어 `azd up` 한 번으로 환경이 만들어집니다.

<!-- BEGIN:labs -->
| 랩 | 무엇을 확인하나 |
|---|---|
| [Azure SRE Agent 이벤트 기반 장애 분석 실습](monitor/sre-agent-event-lab/README.md) | Azure Container Apps에 장애를 세 번 주입하고, Azure Monitor 경고를 받은 Azure SRE Agent가 실제로 조사·결론까지 도달하는지 확인합니다 |
<!-- END:labs -->

각 랩의 README가 사전 조건, 배포, 정리 절차를 안내합니다. **실습을 마치면 반드시 각 랩의 정리 절차를 따라 리소스를 삭제하세요.**

새 랩은 `azure.yaml`과 `README.md`를 갖춘 디렉터리를 만들면 위 표에 자동으로 들어갑니다.

## 🎯 활용 플랜

### 1. 지식 베이스로 활용
- 과거에 해결했던 이슈를 빠르게 검색하고 참고
- 유사한 문제 발생 시 검증된 솔루션 적용
- 신규 팀원 온보딩 시 학습 자료로 활용

### 2. 베스트 프랙티스 공유
- 실제 프로덕션 환경에서 검증된 구성 및 설정 공유
- Azure 서비스별 최적화 전략 문서화
- 성능 튜닝 사례 및 트러블슈팅 가이드 제공

### 3. 협업 및 확장
- 팀원들이 새로운 이슈 해결 사례를 지속적으로 추가
- 코드 예제와 함께 상세한 설명 제공
- 한국 고객 환경에 특화된 가이드 작성

## 📝 기여 방법

문서를 어디에 두고, 제목·문체·표·링크를 어떻게 쓰는지는 **[AGENTS.md](AGENTS.md)** 한 곳에 정리돼 있습니다.
사람이 쓸 때도 AI 에이전트에게 시킬 때도 같은 파일을 봅니다.

새 문서를 올리기 전에 다음 두 가지만 확인하세요.

```bash
python3 scripts/gen_index.py      # README 인덱스 갱신
python3 scripts/check_docs.py     # 링크·앵커·표·문체 검사
```

## 🎓 대상 독자

- Microsoft Customer Success Architect (CSA)
- Azure 기술 지원 엔지니어
- Azure 클라우드 아키텍트
- Azure 서비스를 사용하는 개발자

## 🔗 관련 리소스

- [Microsoft Learn](https://learn.microsoft.com/ko-kr/)
- [Azure Documentation](https://learn.microsoft.com/ko-kr/azure/)
- [Azure Architecture Center](https://learn.microsoft.com/ko-kr/azure/architecture/)

이 저장소의 내용은 Microsoft CSA 팀 내부 지식 공유를 목적으로 합니다.
