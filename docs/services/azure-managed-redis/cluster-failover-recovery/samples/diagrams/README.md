# Clustering policy diagrams

장애 사례와 클러스터링 정책 가이드에서 사용하는 직접 작성한 그림의 Excalidraw 원본과 SVG입니다. 빌드할 때 `sample.yml`의 `publish` 목록에 따라 SVG가 각 문서의 `images/`로 게시됩니다.

| 원본 | 게시 이미지 | 내용 |
|---|---|---|
| `clustering-policies.excalidraw` | `images/clustering-policies.svg`, `clustering-policies-and-migration/images/clustering-policies.svg` | OSS·Enterprise·Non-clustered 정책별 연결 모델 |
| `migration-flow.excalidraw` | `clustering-policies-and-migration/images/migration-flow.svg` | Azure Cache for Redis에서 옮길 때 정책 선택 흐름 |
| `failover-incident.excalidraw` | `images/failover-incident.svg` | 노드 교체 후 `createCluster`가 복구되지 않은 과정 |

## 수정 방법

1. [excalidraw.com](https://excalidraw.com) 또는 VS Code Excalidraw 확장에서 `.excalidraw` 파일을 엽니다.
2. 그림을 수정하고 같은 이름의 SVG로 내보내 이 폴더의 SVG를 교체합니다.
3. 저장소 루트에서 `mkdocs build --strict`를 실행해 게시 결과를 확인합니다.

Azure Managed Redis와 Azure Cache for Redis 아키텍처 PNG는 Microsoft Learn의 [Azure Managed Redis architecture](https://learn.microsoft.com/azure/redis/architecture) 그림이므로 가이드의 `clustering-policies-and-migration/images/`에만 있습니다.
