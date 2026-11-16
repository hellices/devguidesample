---
title: 기여하기
description: 서비스 중심 topic package와 샘플, 메타데이터, 검증 규칙
---

<p class="dg-eyebrow">CONTRIBUTING</p>

# 공개 문서 작성 계약

이 페이지는 공개 문서 작성 규칙의 단일 기준입니다. 새 기술 문서와 샘플은
`docs/services/` 아래의 topic package에 둡니다. 자동 생성되는
`Azure Daily Update`만 아래에서 정의한 전용 아카이브 경로를 사용합니다.
`cases`, `guides`, `labs`, `research`는 물리 폴더가 아니라 front matter의
`document_type`과 수명주기 정책으로만 유지합니다.

루트 `README.md`, `AGENTS.md`, `CONTRIBUTING.md`는 이 계약의 요약입니다.

## 문서 유형과 수명주기

| `document_type` | 용도 | 유지 방식 |
|---|---|---|
| `case` | 특정 시점의 증상, 관측, 조사, 원인과 해결 결과 | 당시 사실을 보존하고 필요하면 `historical`로 표시 |
| `guide` | 현재 권장하는 진단·구성 절차 | 지원 상태와 버전 변화에 맞춰 같은 문서를 갱신 |
| `lab` | 배포, 실행, 검증, 정리를 재현하는 실습 | 비용·검증·정리 절차까지 재검증 |
| `research` | 선택지, 성능, 아키텍처 비교 | 조사 기준일, 범위와 한계를 보존 |

당시 증거를 보존할 사례와 계속 갱신할 현재 절차는 분리하고
`related_cases`·`related_guides`로 연결합니다. 비교와 적용 절차가 같은
수명주기라면 하나의 `guide` 또는 `research` 안에 함께 둘 수 있습니다.

## canonical topic package

### 독립 topic

자식 문서가 없는 글은 다음 구조를 사용합니다.

```text
docs/services/<service>/<topic>/
├── index.md
└── images/
    └── <rendered-image>
```

`images/`는 페이지에서 직접 렌더링하는 이미지가 있을 때만 만듭니다.

### 연결된 topic

순서가 있는 여러 문서는 하나의 topic package로 묶습니다.

```text
docs/services/<service>/<topic>/
├── index.md
├── <child-a>/
│   └── index.md
├── <child-b>/
│   └── index.md
├── images/
└── samples/
```

루트 `index.md`가 topic entry입니다. entry에는 `topic_order`를 쓰지 않습니다.
직접 자식 문서에는 `topic_order: 1`, `topic_order: 2`처럼 1부터 시작하는
중복 없는 연속 번호를 지정합니다. 손자 문서 구조는 허용하지 않습니다.
`index`는 topic entry를 가리키는 예약어이므로 자식 폴더 slug로 사용할 수
없습니다.

<!-- GitHub uses the named anchor; MkDocs uses the heading ID below. -->
<a name="topic-entry-message"></a>

### topic entry 구성: 핵심 메시지, 실제 결과, 자식 문서 링크 { #topic-entry-message }

topic entry는 독자가 이 주제를 끝까지 읽을지, 직접 해 볼지 결정하는
페이지입니다. 실습 절차를 처음부터 늘어놓지 말고, 이 주제로 무엇을 전달하려는지와
그 결과가 실제로 어떻게 보이는지를 먼저 보여 줍니다.

1. **첫 절 본문에서 핵심 메시지를 한 흐름으로 제시합니다.** "무엇을 하면 어떤
   결과가 나온다"를 2–4단계로 요약합니다. 독자가 entry만 읽어도 주제의 결론을
   알 수 있어야 합니다. 절 제목은 [핵심 용어 제목](#content-first-headings)
   기준을 따릅니다(예: `핵심 흐름: meter 기록 → 자동 수집 → Copilot 대시보드`).
2. **메시지 바로 곁에 실제 결과를 보여 줍니다.** 실제로 실행해 얻은 캡처, 측정값,
   다이어그램을 첫 화면 가까이에 두어 흥미와 신뢰를 줍니다. 만들어 낸 예시 화면이나
   실행하지 않은 결과는 쓰지 않으며, 캡처의 식별자는 공개 안전성 기준대로
   제거합니다.
3. **각 단계는 짧은 코드·구성 발췌와 근거 캡처로 설명합니다.** 방법이 여러
   가지면 선택 기준과 흐름만 비교합니다. 전체 명령, 환경 준비, 문제 해결, 비용
   측정은 자식 문서에 둡니다.
4. **실습·벤치마크 같은 상세 문서는 한두 문장과 링크로 안내합니다.** 무엇을
   재현하는지, 걸리는 시간과 비용 여부만 밝히고 절차를 entry에 다시 쓰지 않습니다.
   자식 문서는 entry의 메시지를 반복하지 않고 entry로 연결합니다.
5. **주제의 핵심 흐름이 아닌 제약은 하단에 짧게 두고 전담 문서로 연결합니다.**
   버전 호환 문제, 임시 우회, 알려진 버그는 entry 아래쪽의 별도 절에 기준일과 함께
   요약하고 원인과 대응은 해당 문서로 보냅니다. entry를 제약 설명으로 시작하지
   않습니다.

독립 topic도 첫 절에서 1–2의 순서를 따릅니다. 이 구성의 예는
[Micrometer 비즈니스 지표와 GitHub Copilot 기반 Grafana 대시보드](../services/azure-monitor/aks-spring-boot-micrometer-grafana/index.md)
topic입니다.

### topic 소유 sample

실행 코드, 배포 매니페스트, 재현 프로젝트와 대용량 결과물은 이를 사용하는
topic 안에 둡니다.

```text
docs/services/<service>/<topic>/samples/<sample>/
├── sample.yml
├── README.md
└── <source-or-artifact-files>
```

`sample.yml` 형식은 다음과 같습니다.

```yaml
title: Event lab
description: Reproduces the monitored incident.
kind: runnable
used_by:
  - index
  - setup
publish:
  - source: assets/architecture.svg
    target: images/architecture.svg
  - source: assets/architecture.svg
    target: setup/images/architecture.svg
```

- `title`, `description`, `kind`는 비어 있지 않은 문자열입니다.
- `kind`는 `runnable`, `artifact`, `external` 중 하나입니다. `external`의 추가 필드와
  구성은 [외부 코드 레포 sample](#external-sample)을 따릅니다.
- `used_by`는 sample을 표시할 문서 slug의 중복 없는 목록입니다.
- topic entry는 `index`, 자식 문서는 폴더 slug로 지정합니다.
- `external`을 제외한 각 sample에는 사용·검증·정리 방법을 설명하는 `README.md`가
  필요합니다.
- sample이 있는 topic에는 entry `index.md`가 반드시 있어야 합니다.
  자식 문서 아래에 `samples/`를 두거나 topic의 `samples/` 바로 아래에
  파일을 두지 않습니다. sample package 내부의 하위 `samples/` 폴더는
  해당 package의 payload로 취급합니다.
- sample 원본 폴더는 공개 안전성 검사를 받지만 MkDocs 사이트와 검색 색인에는
  복사되지 않습니다. 문서에서는 생성되는 sample card 또는 GitHub 소스
  링크로 연결합니다.
- 페이지와 sample에서 같은 이미지나 파일을 사용하는 경우 원본은 sample에만
  보관하고 선택적 `publish` 목록에 명시합니다. `source`는 sample package,
  `target`은 소유 topic 루트 기준 상대 경로입니다. 위 예의 페이지 링크는
  각각 `images/architecture.svg`이며 실제 target 파일을 중복 저장하지 않습니다.
- 빌드는 선언한 파일만 원본 바이트 그대로 target에 게시합니다. 텍스트와
  Markdown 파일도 독립 문서나 검색 항목이 아닌 다운로드 자산으로 유지합니다.
  `downloads/index.md` 같은 원본 자산은 해당 파일 경로로 직접 링크합니다.
  `downloads/`처럼 문서 디렉터리로 줄여 쓰면 다운로드 자산을 가리키지 않습니다.
  공개 target의 경로 구성 요소는 어느 깊이에서도 `.`으로 시작할 수 없습니다.
  [Pages artifact 패키징](https://github.com/actions/upload-pages-artifact/blob/v5/action.yml)이
  기본적으로 숨김 파일과 숨김 디렉터리를 제외하므로, 이런 target은 빌드 전에 거부합니다.
  sample 원본 payload 내부의 숨김 파일은 허용하며 원본 폴더는 계속 게시에서 제외합니다.
  페이지 본문과 링크 텍스트는 기존처럼 검색됩니다. `used_by`는 sample card의
  표시 위치만 결정하며 `publish`와 독립적입니다.
- `publish`는 생략하거나 빈 목록으로 둘 수 있습니다. 각 항목의 `source`와
  `target`은 비어 있지 않은 문자열이어야 합니다. 절대 경로, `..`, 역슬래시,
  소유 경계를 벗어나는 심볼릭 링크와 존재하지 않는 원본은 허용하지 않습니다.
  target은 `samples/` 아래, canonical 문서와 HTML 출력 경로, 이미 존재하는 파일이나
  디렉터리를 가리킬 수 없습니다. 하나의 원본을 여러 target으로 게시할 수
  있지만 각 target에는 하나의 선언만 허용합니다.
  target 파일은 다른 target이나 canonical 출력 파일의 상위·하위 경로와도
  충돌할 수 없습니다. 기존 파일을 target의 상위 디렉터리처럼 사용할 수 없으며,
  기존 디렉터리 아래에 새 파일을 게시하는 것은 허용합니다.

### 외부 코드 레포 sample { #external-sample }

컨테이너 이미지로 빌드해 배포하는 애플리케이션 코드는 문서 레포가 아니라 앱별 공개 코드
레포에 둡니다. 문서 레포에는 코드 레포를 가리키는 `sample.yml`과, 같은 버전에 고정한 git
submodule만 남깁니다. GitHub에서 topic 폴더를 열면 submodule이 `source @ <commit>` 링크로 보이고,
사이트의 sample card는 코드·릴리스 링크와 이미지 이름을 함께 보여 줍니다.

| sample 종류 | 문서 레포에 두는 것 | 용도 |
|---|---|---|
| `external` | `sample.yml`, `source` submodule | 애플리케이션 소스, Dockerfile, azd 구성처럼 빌드·릴리스하는 코드 |
| `runnable` | 실행 파일 전체 | 짧은 스크립트, manifest, azd 구성만으로 재현하는 실습 |
| `artifact` | 결과물 원본 | 대시보드 JSON, 다이어그램 원본처럼 페이지에 게시하는 파일 |

새로 만드는 애플리케이션은 `external`로 시작합니다. 기존 `runnable` 애플리케이션은 그 앱을
크게 바꿀 때 옮깁니다.

#### 코드 레포 구성

코드 레포는 문서 레포와 같은 owner의 공개 레포입니다. 레포 목록과 검색 결과에서 문서용 예제
코드임이 바로 드러나도록 다음을 지킵니다.

- 이름은 `sample-<app>`이며 `<app>`은 앱과 변형을 소문자 kebab-case로 씁니다. 예:
  [`sample-movielog-horizondb`](https://github.com/hellices/sample-movielog-horizondb).
- 레포 설명은 `[Sample]`로 시작하고 운영용이 아니라는 점을 적으며, website에 문서 주소를 넣습니다.
- `sample` topic을 붙이고 README 첫머리에 샘플 레포라는 안내와 문서 링크를 둡니다.

저장소 루트의
[`.github/templates/external-sample-repo/`](https://github.com/hellices/devguidesample/tree/main/.github/templates/external-sample-repo)를
복사해 시작합니다.

```text
<owner>/sample-<app>/
├── README.md                     # 목적, 문서 링크, azd up·down, 릴리스 절차
├── src/, build.gradle.kts, settings.gradle.kts, gradlew
├── Dockerfile
├── azure.yaml, infra/            # azd + Bicep
├── hooks/                        # azd hook (manifest 적용, 데이터 적재, 이미지 import)
├── deploy/                       # hook이 쓰는 Kubernetes manifest, DB 스크립트
└── .github/workflows/
    ├── ci.yml                    # PR·main: 테스트, 이미지 빌드 확인(push 없음)
    └── release.yml               # vX.Y.Z 태그: 테스트 → GHCR push → build provenance
```

- [sample 빌드·배포 도구](#sample-tooling) 기준(azd, Gradle Kotlin DSL)은 코드 레포에도 그대로
  적용합니다.
- 코드 레포의 모든 코드는 PR로 들어가며 Copilot 코드 리뷰를 거칩니다. 레포를 만들면 README만 둔 첫 커밋
  뒤에 기본 브랜치 ruleset을 먼저 겁니다: PR 필수, CI `test` 통과, **Automatically request Copilot code
  review**(`Review new pushes` 포함), 강제 push·삭제 금지. 그다음 앱 코드를 PR로 올려 전체 리뷰를 받습니다.
  근거: [Configuring automatic code review by GitHub Copilot](https://docs.github.com/copilot/how-tos/use-copilot-agents/request-a-code-review/configure-automatic-review).
  이미 리뷰 없이 들어간 코드는 빈 커밋 base 브랜치를 향한 리뷰 전용 PR로 전체 diff를 리뷰받고, 지적은 별도 PR로
  반영한 뒤 리뷰 전용 PR은 닫습니다.
- 릴리스 이미지는 GitHub 호스팅 runner의 release workflow가 빌드해
  `ghcr.io/<owner>/sample-<app>:<version>`으로 게시하고 build provenance를 남깁니다. workflow 요약에
  문서가 고정할 `ref`, `commit`, `image` 값이 출력됩니다.
- workflow의 action은 태그 대신 full commit SHA로 고정하고 주석에 릴리스 이름을 남깁니다. release workflow는
  `packages: write` 권한을 쓰므로, 태그가 옮겨져도 검증하지 않은 action 코드가 실행되지 않게 합니다. 근거:
  [Secure use reference](https://docs.github.com/actions/reference/security/secure-use#using-third-party-actions).
- GitHub 문서는 처음 게시한 패키지의 기본 공개 범위를 private으로 설명합니다. 2026-11-15
  `sample-movielog-horizondb`의 첫 릴리스에서는 공개 레포의 release workflow가 게시한 패키지를
  게시 직후 로그인 없이 pull할 수 있었습니다. 그러므로 첫 릴리스 뒤 로그인하지 않은 상태에서
  manifest를 받아 보고, 실패하면 패키지 설정에서 Public으로 바꿉니다. Public 패키지는 익명으로
  pull할 수 있습니다. 근거:
  [Configuring a package's access control and visibility](https://docs.github.com/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).

  ```bash
  REPO=<owner>/sample-<app>
  TOKEN="$(curl -fsS "https://ghcr.io/token?scope=repository:$REPO:pull" | jq -r .token)"
  curl -fsS -o /dev/null -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.oci.image.index.v1+json" "https://ghcr.io/v2/$REPO/manifests/<version>"
  ```
- 공개 안전성 기준은 코드 레포에도 같습니다. 이 레포의 공개 안전성 검사는 submodule 안을
  보지 않으므로 코드 레포에서 GitHub secret scanning과 push protection을 켭니다.

#### 문서 레포 sample package

```text
docs/services/<service>/<topic>/samples/<sample>/
├── sample.yml
└── source/            # git submodule → <repository> @ <commit>
```

```yaml
title: MovieLog app
description: Spring Boot app for the topic, released as a container image.
kind: external
repository: https://github.com/<owner>/sample-<app>
ref: v2.6.4                                   # SemVer 릴리스 태그
commit: <40자리 commit SHA>                    # 태그가 가리키는 commit, submodule 위치
image: ghcr.io/<owner>/sample-<app>:2.6.4@sha256:<digest>   # 선택
used_by:
  - index
```

- `README.md`, 코드와 `publish`는 두지 않습니다. 페이지에 게시할 파일은 별도 `artifact`
  sample에 둡니다.
- `repository`는 끝에 `.git`을 붙이지 않습니다. `image`를 적으면 GHCR namespace가 `repository` owner의 소문자와
  같아야 합니다.
- `source` submodule은 `.gitmodules` URL이 `repository`와 같고(끝의 `.git`은 대소문자와 상관없이 붙여도 됩니다) gitlink가 `commit`과
  같아야 합니다.
  `docs/services` 아래의 다른 위치에는 submodule을 두지 않습니다.
- 사이트와 문서 CI는 submodule을 checkout하지 않습니다. 로컬에서 코드를 함께 보려면
  `git submodule update --init <sample>/source`를 실행합니다.

처음 연결할 때:

```bash
git submodule add https://github.com/<owner>/sample-<app>.git \
  docs/services/<service>/<topic>/samples/<sample>/source
git -C docs/services/<service>/<topic>/samples/<sample>/source checkout v2.6.4
git add .gitmodules docs/services/<service>/<topic>/samples/<sample>
```

#### 코드 참조와 버전 갱신

문서 본문은 핵심 코드를 짧게 발췌하고, 원문은 고정한 버전의 permalink로 연결합니다.

```markdown
[`VectorSearchRepository.search`](https://github.com/<owner>/sample-<app>/blob/v2.6.4/src/main/java/.../VectorSearchRepository.java#L40-L72)
```

`github.com/<owner>/sample-<app>/(blob|tree|raw|commit)/<ref>`와 `raw.githubusercontent.com` 링크는
`sample.yml`의 `ref` 또는 `commit`만 쓸 수 있으며 `main` 같은 branch 링크는 링크 검사에서
거부됩니다. `refs/tags/<tag>` 형식, `http`·프로토콜 상대 주소와 호스트 대소문자는 같은 링크로
보며, `refs/heads/<branch>`는 태그와 이름이 같아도 branch로 보고 거부합니다. 같은 코드 레포를 여러 topic이 서로 다른 버전으로 쓰면 각 문서는 자기 topic의 버전을
따릅니다. 레포 첫 화면이나 릴리스 페이지(`/releases/tag/<ref>`) 링크는 그대로 둘 수 있습니다.

`validate_links.py`는 `git ls-remote`로 코드 레포를 조회해 `ref` 태그가 `commit`을 가리키는지, 태그와 같은
이름의 branch가 없는지도 확인합니다. GitHub의 `/blob/<name>/` 링크는 같은 이름의 태그와 branch를 구분하지
않기 때문입니다. 이 검사에는 GitHub 접속이 필요하며, 코드 레포에는 `refs/heads/v*` branch 생성과 `refs/tags/v*`
태그의 갱신·삭제를 막는 ruleset을 함께 겁니다. 그래도 태그가 다른 commit으로 옮겨지면 이 검사가 `sample.yml`의
`commit`과 달라진 것을 오류로 알리므로, 태그 permalink는 문서 PR에서 고정한 commit과 같은 코드를 가리킵니다. 검사를
통과한 `commit`으로 sample 카드의 코드 링크(`/tree/<commit>`)를 만들고, 릴리스
링크는 `ref`를 씁니다.

새 버전을 문서에 반영할 때는 다음을 한 PR에서 함께 바꿉니다.

1. 코드 레포에서 `origin/main`에 `vX.Y.Z` 태그를 올리고 release workflow 요약의 값을 확인합니다. release
   workflow는 Docker 태그로 쓸 수 없는 build metadata(`+...`)가 붙은 태그를 게시 전에 거부합니다.
2. `git -C <sample>/source fetch --tags && git -C <sample>/source checkout vX.Y.Z` 뒤
   `git add <sample>/source`로 submodule을 옮깁니다.
3. `sample.yml`의 `ref`, `commit`, `image`와 본문 permalink의 버전을 바꿉니다.
4. 측정값이나 캡처가 바뀌었으면 문서 본문도 함께 고칩니다.

#### 이미지 배포

문서의 재현 절차는 코드 레포의 azd 구성을 씁니다. 릴리스 이미지를 그대로 배포할 때는 azd hook에서
`az acr import`로 GHCR 이미지를 digest로 지정해 실습 Azure Container Registry로 복사합니다.
import는 Docker 없이 레지스트리 사이에서 이미지를 복사하며, 대상 레지스트리에
`Container Registry Data Importer and Data Reader` 역할이 필요합니다. private endpoint나 방화벽
규칙이 있는 레지스트리는 신뢰할 수 있는 서비스 접근을 허용해야 합니다. 근거:
[Import container images to a container registry](https://learn.microsoft.com/azure/container-registry/container-registry-import-images).
템플릿의 `hooks/import-image.sh`가 이 단계를 수행하며 자격 증명을 넘기지 않으므로 GHCR 패키지가
Public이어야 합니다.

### sample 빌드·배포 도구 { #sample-tooling }

runnable sample과 external sample의 코드 레포는 Azure 배포를 `azd`, Java 빌드를 Gradle Kotlin DSL로
통일합니다. 컨테이너 이미지는 runnable sample이면 Azure Container Registry 서버 빌드로 만들고, external
sample이면 코드 레포의 release workflow가 GHCR에 게시한 이미지를 배포 때 `az acr import`로 digest를 지정해
ACR에 복사합니다. external sample의 이미지는 ACR에서 다시 빌드하지 않습니다. 새로 추가하거나
배포 방식을 바꾸는 sample에 적용하며, 기존 sample은 해당 sample을 고칠 때
맞춥니다.

| 대상 | 기준 | 사용하지 않는 방식 |
|---|---|---|
| Azure 리소스와 앱 배포 | `azure.yaml`과 `infra/`(Bicep)를 두고 `azd up`으로 만들고 `azd down`으로 정리합니다. external sample은 이 파일과 hook을 문서 레포가 아니라 코드 레포 루트에 둡니다. | README에 나열한 단독 `az` 생성 명령 |
| azd 밖의 단계 | Kubernetes manifest 적용, 데이터 적재, 미리 보기 API 호출은 `azure.yaml` hook(`preprovision`, `postprovision`, `postdeploy` 등) 스크립트로 실행합니다. | 수동으로 이어 붙이는 명령 순서 |
| runnable 이미지: azd 서비스 빌드 | `azure.yaml`의 서비스로 배포하는 이미지는 `docker.remoteBuild: true`로 ACR에서 빌드합니다. | 로컬 `docker build`·`docker push`, ACR 빌드 실패 뒤 azd가 대신 수행한 로컬 빌드, 같은 이미지를 hook에서 다시 빌드 |
| runnable 이미지: hook 빌드 | fallback 없이 ACR 빌드만 허용할 이미지는 hook 스크립트에서 `az acr build --platform linux/amd64`로 빌드하고, 배포 단계(Kubernetes manifest 등)가 그 이미지를 참조하게 합니다. | 같은 이미지를 `docker.remoteBuild` 서비스로도 빌드 |
| external 컨테이너 이미지 | hook에서 `az acr import`로 GHCR 릴리스 이미지를 digest로 지정해 ACR에 복사합니다. | 같은 코드를 ACR이나 로컬에서 다시 빌드한 이미지 |
| Java 프로젝트 | `build.gradle.kts`, `settings.gradle.kts`와 Gradle Wrapper(`gradlew`)를 커밋합니다. | Maven `pom.xml`, Groovy `build.gradle` |

- 이미지 하나는 두 경로 중 하나로만 빌드합니다. `docker.remoteBuild: true`는 ACR 원격 빌드가 실패하면 로컬 Docker나
  Podman으로 다시 빌드합니다. 이 fallback으로 만든 이미지는 기준에 맞지 않으므로, 배포 출력에서
  이미지가 ACR에서 빌드됐는지 확인하고 원격 빌드 실패를 고친 뒤 다시 배포합니다.
  fallback 자체를 막아야 하면 그 이미지를 azd 서비스에서 빼고 hook 빌드 경로를 사용합니다.
  근거: [Azure Developer CLI schema reference](https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-schema)의
  `docker` 속성.
- `azd up`은 `preprovision` hook보다 먼저 Bicep 필수 입력을 검사합니다. hook이
  채우는 매개변수에는 `''` 같은 기본값을 둡니다.
- 위 기준을 따를 수 없는 단계(Bicep 형식이 없는 미리 보기 리소스 등)는 hook
  스크립트로 감싸고 README에 이유를 적습니다.

최상위 `samples/`에는 공개 콘텐츠를 추가하지 않습니다.

## 경로와 redirect 규칙

모든 `<service>`, `<topic>`, `<child>`, `<sample>` slug는 소문자
kebab-case를 사용합니다. Azure 제품의 `<service>`는 `azure-`와 공식 전체
제품명을 조합합니다. 이름이 `Microsoft`로 시작하는 제품은 `microsoft-`
slug를 사용하고, 그 밖의 제품은 공식 프로젝트·제품명을 kebab-case로
표현합니다.

이전 공개 URL을 보존해야 하면 canonical 문서 front matter에 추가합니다.

```yaml
redirect_from:
  - guides/<service>/<old-topic>/index.md
```

redirect 경로는 `cases`, `guides`, `labs`, `research` 중 하나로 시작하는
기존 4단계 `index.md` 경로 또는 이동 전의
`services/<service>/<topic>[/<child>]/index.md` 경로입니다.
현재 canonical 문서와 충돌하거나 둘 이상의 문서가 같은 이전 주소를
소유할 수 없습니다. redirect의 Markdown·HTML 경로와 sample 게시 자산도
서로 겹칠 수 없습니다. 해당 경로에 원본 Markdown을 다시 만들지 않습니다.
빌드가 redirect page를 생성하며 검색과 서비스/topic 탐색에서는 제외합니다.
JavaScript를 사용할 수 있으면 query와 fragment를 유지해서 이동하고,
그렇지 않으면 meta refresh와 직접 링크로 canonical 문서에 접근합니다.
문서를 분리할 때는 이전의 주요 fragment에 대응하는 섹션이나 새 문서로
가는 안내를 목적지에 남깁니다.
이전 collection/service 색인 주소도 유지하며, 현재 소속과 이전 소속이
겹치면 canonical 문서를 중복 없이 합칩니다. 이 호환 색인에서는 topic
카드와 함께 해당 자식 문서로 바로 가는 링크도 제공합니다.
서비스 문서의 이전 주소로는 collection 호환 색인을 만들지 않습니다.

`document_type`은 collection 호환 색인과 수명주기 요구사항을 선택하지만
물리 경로를 결정하지 않습니다. `services/`, `explore/`와 collection 호환
색인은 빌드가 생성합니다. `tags/`, `articles/`는 `explore/`로 이동하는
검색 제외 redirect입니다. 개별 문서를 추가하기 위해
`mkdocs.yml`, `docs/.nav.yml`, README 또는 수동 문서 목록을 수정하지
않습니다.

## 글 찾기와 실용 태그

대메뉴는 **홈 · Azure Daily Update · 서비스별 보기 · 글 찾기 ·
기여하기**입니다. 글 찾기는 모든 주제를 canonical topic 카드로 묶고 실제
catalog에서 계산한 **주제 수 · 문서 수**를 함께 표시합니다. 여러 문서가
있는 topic도 카드 하나이며 각 문서로 직접 연결합니다.

### 일일 업데이트 아카이브

`Azure Daily Update`는 자동화가 생성하는 시계열 뉴스 아카이브입니다.
일자별 원본은 `docs/azure-daily-update/YYYY-MM-DD/index.md`에 두고,
`/azure-daily-update/` 색인은 빌드가 생성합니다. 이 페이지들은
서비스 topic package가 아니므로 `document_type`과 taxonomy 값을 선언하지
않습니다.

각 일자별 페이지에는 `title`, `description`, `report_date`,
`generated_at` front matter를 지정합니다. `report_date`는 디렉터리의
`YYYY-MM-DD`와 같아야 하며 실제 달력 날짜여야 합니다. 날짜가 아닌 하위
경로는 사이트와 검색 색인에서 제외합니다.

각 보고서의 첫 `##` 제목 앞 요약 목록에는 `AI & Apps`, `Infra`,
`Database`, `총계`, `핵심 한 줄`을 각각 한 번 작성합니다. 분야별 건수와
총계는 0 이상의 `N건` 형식이며 총계는 세 분야의 합과 같아야 합니다.
`핵심 한 줄`은 여러 줄과 인라인 Markdown을 사용할 수 있습니다. 빌드는
이 값을 검증하여 최근 카드에 날짜·총계·분야별 건수·핵심 한 줄을
표시합니다.

색인에는 자료가 있는 **최신 발행일 3개**만 최신순으로 표시합니다.
오늘부터 3일 이내로 제한하는 방식이 아니므로 발행이 없는 날이 있어도
최근 자료를 읽을 수 있습니다. 이전 문서와 날짜별 주소는 그대로 유지합니다.

- 아카이브 색인은 본문에 달력과 검색을 표시하며 왼쪽 메뉴에 같은 달력을
  중복하지 않습니다. 일자별 페이지의 왼쪽 메뉴에는 빠른 날짜 이동을 위한
  작은 달력과 색인 링크를 표시합니다. 다른 페이지에서는 아카이브 진입
  링크만 표시합니다.
- 달력은 색인에서 최신 발행 월, 일자별 페이지에서 읽고 있는 문서의 월로
  시작합니다. 자료가 있는 날은 링크·강조색·밑줄로, 현재 문서는 별도
  배경색으로 구분합니다. 자료가 없는 날은 클릭할 수 없습니다.
- 이전·다음 버튼은 자료가 있는 발행 월 사이를 이동합니다. 월 선택
  목록으로 연도가 다른 자료에도 바로 접근할 수 있습니다.
- 아카이브 검색은 전체 기간의 날짜·제목·요약·본문을 대상으로 합니다.
  공백으로 나눈 검색어를 같은 문서에 AND로 적용하며, 결과는 최신순으로
  10개씩 펼칩니다. 상단 사이트 전체 검색과 독립적이며 `q`를 변경하지 않습니다.
  결과에는 검색어 주변 본문을 최대 2곳, 각 말줄임표 포함 180자 이내로
  발췌하고 생략된 부분은 말줄임표로 표시합니다. 날짜·제목·요약과 발췌문의 일치 문구를
  강조하여 검색된 이유를 보여줍니다. 본문이 일치하지 않으면 기존 요약을
  유지하며, 일치 횟수와 무관하게 발행일 최신순으로 정렬합니다.
  발췌문은 빌드 시 Markdown 서식을 제거하고 문단 경계를 보존한 텍스트를
  우선 사용합니다. 링크 URL 등 원문에서만 일치하는 검색어가 있으면 발췌
  자리 하나를 확보하여 원문 주변을 표시합니다.
- 빌드는 달력용 `assets/daily-updates-calendar.json`과 검색용
  `assets/daily-updates.json`을 자동 생성합니다. 달력 데이터에는 날짜·제목·URL만
  포함하므로 일자별 문서를 읽을 때 전체 아카이브 본문을 내려받지 않습니다.
  본문을 포함한 검색 데이터는 아카이브 색인에서만 불러오고, 검색용 텍스트를
  처음 한 번 정규화하여 재사용합니다. 날짜 목록이나 검색 데이터를 수동으로
  관리하지 않습니다.
- JavaScript가 꺼져 있으면 색인의 전체 발행일 목록으로 접근합니다.
  데이터를 불러오지 못하면 오류 안내를 표시하고, 이미 표시된 날짜 링크와
  최근 글은 계속 사용할 수 있습니다. 모든 일자별 본문은 사이트 전체
  검색에도 포함됩니다.

### 주제 필터와 태그

- 서비스, 목적·주제별 태그, 기술은 front matter 값과 정확히 일치해야 합니다.
- 태그 하나를 선택하면 해당 태그가 붙은 문서만 표시합니다. 여러 태그,
  서비스, 기술은 **같은 문서에 AND**로 적용합니다. 서로 다른 자식의
  태그를 합쳐서 일치한다고 판단하지 않습니다.
- 제목·설명 검색도 같은 문서에 적용합니다. 본문 검색은 사이트의 별도
  전체 텍스트 검색을 사용합니다.
- 일치하지 않는 문서 행과 일치 문서가 없는 topic 카드는 숨깁니다.
  JavaScript가 없으면 안내와 함께 모든 topic과 문서 링크를 표시합니다.
- 선택 조건은 반복 가능한 `tag`, `service`, `technology`, `text` query로
  공유합니다. 예를 들어 `explore/?tag=design&text=Agent&text=Memory`는
  `design` 태그와 두 검색어가 모두 일치하는 문서만 표시합니다.
- `q`는 Material의 사이트 전체 검색 전용입니다. 글 찾기는 이를 자신의
  검색어나 잘못된 필터로 취급하지 않으며 URL을 갱신할 때 현재 `q` 값을
  보존합니다. 전체 검색 창을 닫아도 글 찾기의 `text` 조건은 지워지지 않습니다.
- 상단 전체 검색은 키 입력뿐 아니라 한글 IME 확정, 마우스 붙여넣기, 모바일
  자동 완성·음성 입력으로 바뀐 검색어도 바로 검색합니다.
- 그 밖의 알 수 없는 매개변수나 필터 값은 경고 후 제외합니다. 초기화하면
  글 찾기의 선택과 검색어, 해당 query를 지우되 전체 검색의 `q`는 유지합니다.
- 문서와 카드의 태그 링크는 `explore/?tag=<slug>`로 연결합니다.

문서의 `tags`는 아래 통제 값에서 **1–4개** 선택합니다. 중복을 제거하고
목적 태그를 주제 태그보다 먼저 배치합니다. 기술 분류와 중복되는
`kubernetes`는 태그가 아니라 `technologies`로 지정합니다.

| 그룹 | 값 |
|---|---|
| 목적 | `design` 설계 · `build` 구현 · `deploy` 배포 · `diagnose` 진단 · `optimize` 최적화 · `operate` 운영 · `secure` 보안 · `evaluate` 비교·검증 · `migrate` 마이그레이션 |
| 주제 | `ai-agents` AI agents · `networking` 네트워킹 · `identity` ID·권한 · `storage` 스토리지 |

태그를 추가할 때는 `docs-taxonomy.yml`의 `tags`와 `tag_groups`를 함께
수정하고 실제 문서에 적용합니다. 각 태그는 그룹 하나에 정확히 한 번
등장해야 하며 미사용 태그는 허용하지 않습니다. `legacy_tag_redirects`는
이전 `/tags/<slug>/` 주소를 새 필터로 변환하는 taxonomy 소유 매핑입니다.
예를 들어 `authentication`은 `identity`와 `secure` 두 태그로,
`kubernetes`는 기술 필터로 이동합니다. 이 redirect는 검색·메뉴에서
제외하며 문서마다 legacy 태그를 저장하지 않습니다.

## 세 가지 작성 workflow

### 1. 독립 topic 추가

1. `docs/services/<service>/<topic>/index.md`를 만듭니다.
2. 공통 front matter와 선택한 `document_type`의 필수 필드를 채웁니다.
3. 렌더링 이미지가 있으면 같은 bundle의 `images/`에 두고 의미 있는 대체
   텍스트를 작성합니다.
4. 새 taxonomy 값이 있을 때만 `docs-taxonomy.yml`을 수정합니다.
5. 필수 검증을 모두 실행합니다.

### 2. 연결된 topic 추가 또는 확장

1. topic entry를 `docs/services/<service>/<topic>/index.md`에 두고
   [topic entry 구성 기준](#topic-entry-message)에 따라 핵심 메시지와 실제 결과를
   먼저 보여 줍니다.
2. 직접 자식마다 `<child>/index.md`를 만들고 연속 `topic_order`를
   지정합니다.
3. 이전 URL이 있으면 각 canonical 문서에 고유한 `redirect_from`을
   기록합니다.
4. topic 안의 링크는 canonical `.md` 상대 경로로 작성합니다.
5. entry 목차, 이전·다음 이동, 서비스 메뉴가 자동 생성되는지 strict build로
   확인합니다.

### 3. sample 추가

1. `docs/services/<service>/<topic>/samples/<sample>/`을 만듭니다.
2. `sample.yml`과 `README.md`를 먼저 작성하고 `used_by` 소유 문서를
   지정합니다.
3. 코드·매니페스트·결과물을 같은 sample 폴더에 둡니다.
4. 실제 식별자와 비밀을 가상 값으로 치환합니다.
5. public-safety 검사가 sample을 검사하고 strict build의 `site/`에는 sample
   원본 폴더가 없는지 확인합니다. `publish`를 사용하면 선언한 target만
   게시되며 원본과 바이트가 같은지도 확인합니다.

<!-- GitHub uses the named anchor; MkDocs uses the heading ID below. -->
<a name="content-first-headings"></a>

## 핵심 용어 제목 { #content-first-headings }

**제목은 문장이 아니라 핵심 용어로 구성한 명사구입니다.** 제목만 읽어도 무엇에
관한 글이며, 각 절이 어떤 대상의 어떤 측면(원인·조치·차이·결과)을 다루는지 알 수
있어야 합니다. 결론과 주장은 제목에 서술하지 않고 해당 절의 첫 문장에서 밝힙니다.
작성자의 생각 흐름이나 작업 순서를 그대로 제목으로 옮기지 않습니다.

- **문서 `title`과 H1**은 주제를 이루는 핵심 용어(제품·기술·대상·결과)를
  조합합니다. 용어 사이는 `·`, `—`, `:`, `→`, `와/과`로 잇습니다. 길이를 다르게
  줄이더라도 두 제목의 핵심 의미는 같아야 합니다.
- **H2·H3 등 절 제목**은 그 절이 다루는 대상과 측면을 핵심 용어로 나타냅니다.
  `대상: 측면` 형식(예: `수집: Instrumentation CR과 Pod annotation`)을 쓸 수
  있습니다. 상위 제목을 되풀이하지 않습니다.
- `~합니다`, `~입니다`, `~한다`, `~됩니다` 같은 서술 어미로 끝나는 완결 문장과
  질문형 문장을 제목으로 쓰지 않습니다. 먼저 절의 핵심을 한 문장으로 정리하고,
  그 문장에서 대상과 핵심 용어만 남겨 제목을 만듭니다. 정리한 문장은 본문 첫
  문장으로 씁니다.
- `개요`, `문제 정의`, `기존 코드`, `추가 설명`, `보강`, `중요한 점`,
  `다음 단계` 같은 일반적인 말만으로 정보 전달용 제목을 끝내지 않습니다.
  명사구라도 다른 글에 그대로 붙일 수 있다면 대상이나 요점이 빠진 것입니다.
- 결과·수치·인과관계는 본문에서 뒷받침되는 수준으로만 용어화합니다.
  추정은 `가능성`, `가설`처럼 용어로 구분하고 가설을 확정된 원인이나 검증된
  효과처럼 표현하지 않습니다. 핵심을 드러내기 위해 없는 결론을 만들지 않습니다.
- 이 기준은 기술 문서뿐 아니라 뉴스의 개별 항목 제목에도 적용합니다
  (예: `Azure Route Server — route maps GA`). 메뉴·색인·아카이브의 고정 이름과
  `참고 자료`, `관련 문서` 같은 보조 영역의 관례적 제목은 유지할 수 있습니다.

### 일반 항목명과 핵심 용어 제목 비교

아래는 해당 내용을 담은 본문이 있다는 가정의 편집 예시입니다.
예시의 결론이나 조치를 실제 문서에 근거 없이 추가하지 않습니다.

| 핵심이 드러나지 않는 제목 | 핵심 용어 제목 |
|---|---|
| 문제 정의 | 연결 종료 뒤 요청 미복구 현상 |
| 기존 코드 | 요청마다 연결을 새로 생성하는 코드 |
| 원인 분석 보강 | 노드 교체 후 기존 주소 재연결 가능성 |
| 두 방식 비교 | 직접 연결과 프록시 경유의 요청 경로 차이 |
| 마이그레이션 주의사항 | TTL·키 값 검증 후 새 저장소 트래픽 전환 |
| 다음 단계 | 오류율·복구 시간 기반 전환 결과 확인 |

### 서술형 문장 제목과 핵심 용어 제목 비교

| 서술형 문장 제목 | 핵심 용어 제목 |
|---|---|
| 앱 코드는 도메인 이벤트에서 meter를 올리는 것으로 끝납니다 | 앱 코드: 도메인 이벤트 기반 Micrometer meter |
| 관리형 3.7.7-aks에서는 지표가 0건이었고 3.7.10으로 바꾸자 도착했습니다 | agent 버전 게이트: 3.7.7-aks 지표 누락과 3.7.10 전환 |
| 비용은 meter × tag 조합 × Pod 수로 늘어납니다 | 수집 비용: meter × tag 조합 × Pod 수 |
| 정리하면 resource group 삭제로 모든 실습 자원이 사라집니다 | 정리: resource group 삭제 |

### 제출 전 제목 점검

제출 전에 문서 제목과 모든 절 제목을 순서대로 읽고 다음을 확인합니다.

1. 본문을 가려도 문서의 주제와 각 절이 다루는 대상·측면을 파악할 수 있는가?
2. 서술 어미로 끝나거나 완결 문장·질문 문장인 제목은 없는가?
3. 각 제목의 핵심 용어를 본문이 실제로 설명하거나 입증하며, 절의 결론은 본문
   첫 문장에 있는가?
4. 제목을 다른 글에 그대로 붙여도 어색하지 않다면 대상이나 요점이 빠진
   것은 아닌가? 형제 절의 제목이 겹치거나 작성 과정의 메모처럼 보이지 않는가?
5. 추정이나 제한 조건을 지운 단정적인 용어로 바뀌지는 않았는가?

제목을 구체적으로 만들기 어렵다면 그 절에 핵심이 없거나 서로 다른 내용이
섞여 있는지 먼저 점검하고, 본문을 정리한 뒤 제목을 다시 씁니다.
템플릿의 대괄호 항목은 작성할 내용의 역할을 표시한 자리표시자이며,
그대로 게시할 제목이 아닙니다.

## 공통 front matter

```yaml
---
title: AKS 네트워크 진단
description: AKS 네트워크 문제를 진단하는 현재 절차
document_type: guide
services: [azure-kubernetes-service]
technologies: [kubernetes]
tags: [diagnose, networking]
status: current
verification_status: verified
sources_checked_at: 2026-09-12
official_sources:
  - title: Azure Kubernetes Service documentation
    url: https://learn.microsoft.com/azure/aks/
last_verified: 2026-09-12
review_cycle_days: 180
applies_to: [AKS 1.34+]
---
```

`services`, `technologies`, `tags`와 유형별 `status`는
`docs-taxonomy.yml`의 값을 사용합니다. 유형별 전체 형식은
[사례 템플릿](case-template.md), [가이드 템플릿](guide-template.md),
[실습 템플릿](lab-template.md), [리서치 템플릿](research-template.md)을
사용합니다. 홈에 소개할 topic entry에는 `featured: true`를 지정할 수
있습니다.

## Azure Daily Update 보고서

일일 브리핑은 `docs/azure-daily-update/YYYY-MM-DD/index.md`에 작성합니다.
front matter는 `title`, `description`, `report_date`, `generated_at`을
사용하며, 날짜 디렉터리와 `report_date`는 일치해야 합니다.
`description`에는 그날의 핵심 기능 변화를 구체적으로 요약합니다.

본문은 짧은 핵심 요약, 주요 기능의 개요·구조와 동작, 필요한 대응,
기타 업데이트 순으로 구성합니다. 상단에 AI & Apps·Infra·Database별
수록 항목과 본문 링크를 표시하되 비어 있는 분류는 생략합니다.
건수·총계, 조사 방법, 빈 범주와 일률적인 전제조건 체크리스트는
넣지 않습니다. 각 주요 기능 앞에는 기능의 목적·배경과 이번 변화의
의미를 설명합니다. Control plane·Data plane 등 통용되는 기술 용어는
영어를 유지하고 동작은 한국어로 설명합니다. 업데이트 원문의 연결
문서와 Microsoft Learn 원문을 확인하고, 재배포가 허용된 공식
다이어그램을 출처와 함께 활용합니다. 해당 페이지에 사용하는 이미지는
같은 날짜 bundle의 `images/`에 둡니다.

리전 정보는 전체 지원 범위와 지역별 차이를 설명하고, 한국 리전의
미지원 여부도 의미가 있을 때 별도로 표시합니다. 주요 항목 수는
날짜별로 유동적이며, 의미 있는 신규 기능이나 대응 사항이 없는 날은
날짜 페이지를 만들지 않아도 됩니다. 이미 게시된 날짜 페이지는
삭제하지 않습니다.

기존의 분야별 건수·총계·핵심 한 줄 형식도 계속 지원합니다.
이 형식의 필드를 사용하면 전체 필드와 합계가 유효해야 합니다.
통계 요약이 없는 새 보고서는 최근 카드에 `description`을 표시하며
건수를 추정하지 않습니다. 날짜별 검색·달력은 두 형식 모두 지원합니다.

## 공식 출처 검증

Microsoft 또는 Azure의 동작, 지원 상태, 제한, 버전, 구성 단계나 CLI/API
사용법을 추가하거나 바꿀 때 repository skill `verify-with-microsoft-learn`을
사용합니다. Microsoft Learn 검색 결과만 인용하지 말고 선택한 원문 전체를
확인하여 주장, 적용 범위와 전제 조건을 비교합니다.

실제로 확인한 원문의 제목과 정규 URL을 `official_sources`에 기록하고
`sources_checked_at`을 확인일로 갱신합니다. 중요한 주장을 모두 확인했을
때만 `verification_status: verified`로 표시합니다. 검증을 완료하지 못하면
`verification_status: needs-review`로 남깁니다. Kubernetes·CNCF 세부
동작은 필요한 경우 upstream 공식 문서도 함께 확인합니다.

날짜만 기록하는 `sources_checked_at`과 `last_verified`는 **KST(UTC+09:00)**
기준으로 작성합니다. 로컬·PR CI·Pages의 검증기도 같은 기준으로 오늘 날짜를
판정하며, KST 기준의 미래 날짜는 허용하지 않습니다. 실행 환경의 시간대
차이를 피하려고 실제 확인일을 앞당기거나 검증 날짜를 삭제하지 않습니다.

## 본문과 공개 안전성

- 페이지마다 하나의 H1을 사용하고 H2/H3 순서를 건너뛰지 않습니다.
- 문서 링크는 canonical `.md` 상대 경로를 사용합니다.
- 렌더링 이미지는 같은 bundle의 `images/`에 두고 대체 텍스트를 씁니다.
- 고객·조직·사용자 실명, 구독·테넌트 ID, 키·토큰·인증서·연결 문자열,
  내부 URL·IP·호스트명, 개인정보가 포함된 로그와 승인되지 않은 화면을
  게시하지 않습니다.
- 실제 식별자는 문서와 sample 전체에서 일관된 가상 값으로 치환합니다.
- `.azure/`, `.claude/`, `.DS_Store`, `sim-env.json`, 실행 중 생성된
  `evidence/`는 커밋하지 않습니다.

## 필수 검증

저장소 루트에서 다음을 모두 실행합니다.

```powershell
python -m pytest tests/docs -q
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
```

PR CI도 같은 명령을 실행하므로 로컬에서 통과하면 PR에서도 같은 결과를
기대할 수 있습니다. 같은 PR에 새 commit을 push하면 진행 중인 이전 실행은
취소됩니다. `main`에 직접 push한 변경은 PR CI를 거치지 않으므로 Pages 배포가
검증 스크립트, 이전 URL 검사, strict build와 검색 인덱스 검증을 통과해야
배포됩니다.

이전에 공개한 URL은 `tests/docs/test_legacy_urls.py`의 목록으로 보존합니다.
목록의 각 경로는 현재 문서의 `redirect_from`에 계속 선언되어 있어야
합니다. 문서를 옮기거나 합칠 때는 기존 `redirect_from`을 새 canonical
문서로 함께 옮깁니다. URL을 의도적으로 폐기할 때만 목록에서 제거합니다.

생성된 `site/`과 검색 인덱스는 커밋하지 않습니다. 실패한 검증을 무시하지
않습니다.
