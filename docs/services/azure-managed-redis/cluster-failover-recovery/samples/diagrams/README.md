# Failover incident diagram

장애 사례의 설명 모델을 담은 Excalidraw 원본과 SVG입니다. 원문 관측을 설명하는 가설이며 당시 클라이언트 내부 상태를 모두 입증한 자료는 아닙니다. 빌드할 때 `sample.yml`의 `publish`에 따라 사례의 `images/`로 게시됩니다.

| 원본 | 게시 이미지 | 내용 |
|---|---|---|
| `failover-incident.excalidraw` | `images/failover-incident.svg` | 노드 교체 후 `createCluster`가 복구되지 않은 과정 |

## 수정 방법

1. [excalidraw.com](https://excalidraw.com) 또는 VS Code Excalidraw 확장에서 `.excalidraw` 파일을 엽니다.
2. 그림을 수정하고 같은 이름의 SVG로 내보내 이 폴더의 SVG를 교체합니다.
3. 저장소 루트에서 `mkdocs build --strict`를 실행해 게시 결과를 확인합니다.

정책별 연결 그림은 [정책 topic의 diagram sample](../../../clustering-policies/samples/diagrams/README.md)에서만 관리합니다. 정책 선택 흐름과 중복되던 마이그레이션 그림은 제거하고 [독립 마이그레이션 가이드](../../../migration-from-azure-cache/index.md)로 연결합니다.
