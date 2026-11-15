# <앱 이름>

<한두 문장: 이 코드가 재현하는 것>. 설명과 측정 결과는 문서에 있습니다.

- 문서: [<topic 제목>](https://hellices.github.io/devguidesample/services/<service>/<topic>/)
- 문서가 참조하는 버전: 문서 레포 `docs/services/<service>/<topic>/samples/<sample>/sample.yml`의 `ref`

## 구성

| 경로 | 내용 |
|---|---|
| `src/`, `build.gradle.kts`, `settings.gradle.kts`, `gradlew` | 애플리케이션 (Gradle Kotlin DSL) |
| `Dockerfile` | 컨테이너 이미지 |
| `azure.yaml`, `infra/` | `azd up`·`azd down`으로 만들고 지우는 Azure 리소스(Bicep) |
| `hooks/` | azd hook 스크립트(manifest 적용, 데이터 적재, GHCR 이미지 import) |
| `deploy/` | Kubernetes manifest, DB 스크립트 등 hook이 쓰는 배포 파일 |
| `.github/workflows/ci.yml` | PR·main: 테스트와 이미지 빌드 확인(push 없음) |
| `.github/workflows/release.yml` | `vX.Y.Z` 태그: 테스트 → GHCR push → build provenance |

## 실행과 정리

```bash
azd up      # 리소스 생성, 이미지 준비, 배포
azd down --purge
```

## 릴리스

1. 변경을 `main`에 merge합니다.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`로 태그를 올립니다.
3. release workflow 요약의 `ref`, `commit`, `image` 값을 문서 레포 `sample.yml`에 옮기고 submodule을 같은 commit으로 맞춥니다.

공개 저장소입니다. 실제 구독·테넌트 ID, 비밀, 내부 호스트명을 커밋하지 않으며 GitHub secret scanning과 push protection을 켭니다.
