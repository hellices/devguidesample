# Eviction and TTL diagrams

이 문서에서 사용하는 직접 작성한 그림의 Excalidraw 원본과 SVG입니다. 빌드할 때 `sample.yml`의 `publish` 목록에 따라 SVG가 문서의 `images/`로 게시됩니다.

| 원본 | 게시 이미지 | 내용 |
|---|---|---|
| `eviction-flow.excalidraw` | `images/eviction-flow.svg` | 메모리 한도에 도달했을 때 정책별 쓰기 처리 흐름 |
| `approximated-lru.excalidraw` | `images/approximated-lru.svg` | Redis 근사 LRU의 샘플링과 후보 풀 동작 |
| `ttl-lifecycle.excalidraw` | `images/ttl-lifecycle.svg` | TTL의 설정·연장·제거·만료 수명주기 |

## 수정 방법

1. [excalidraw.com](https://excalidraw.com) 또는 VS Code Excalidraw 확장에서 `.excalidraw` 파일을 엽니다.
2. 그림을 수정하고 같은 이름의 SVG로 내보내 이 폴더의 SVG를 교체합니다.
3. 저장소 루트에서 `mkdocs build --strict`를 실행해 게시 결과를 확인합니다.

Azure Managed Redis 아키텍처 PNG는 Microsoft Learn의 [Azure Managed Redis architecture](https://learn.microsoft.com/azure/redis/architecture) 그림이며, 같은 파일을 중복 저장하지 않도록 `cluster-failover-recovery/clustering-policies-and-migration/images/`의 파일을 참조합니다.
