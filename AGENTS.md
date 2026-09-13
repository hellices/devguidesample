# Repository instructions

## Public documentation contract

- 상세 기준은 `docs/contributing/index.md`를 단일 설명 문서로 사용한다.
- 공개 기술 문서는 `docs/<collection>/<service>/<topic>/index.md` page bundle로 작성한다.
- `<collection>`은 `cases`, `guides`, `labs`, `research` 중 하나이며 front matter의 `document_type`과 일치해야 한다.
- Azure 제품의 `<service>`는 `azure-`와 공식 전체 제품명을 kebab-case로 조합한다(예: `azure-kubernetes-service`).
- Microsoft 제품은 공식 명칭을 보존하여 이름이 `Microsoft`로 시작하면 `microsoft-` slug를 사용하고, 오픈소스와 그 밖의 제품은 공식 프로젝트·제품명을 kebab-case로 사용한다.
- 새 서비스, 기술 또는 태그가 필요할 때만 `docs-taxonomy.yml`을 함께 수정한다.
- 개별 문서를 추가하기 위해 `mkdocs.yml`, `docs/.nav.yml`, README 또는 수동 문서 목록을 수정하지 않는다. 빌드가 폴더와 메타데이터에서 메뉴·색인을 생성한다.

## Publishing automation

- 문서의 원본은 Markdown page bundle과 front matter다. 기존 분류의 새 글은 `docs/guides/azure-kubernetes-service/<topic>/index.md` 같은 bundle만 추가하고, 메뉴에 문서 경로를 수동 등록하지 않는다.
- 메뉴 트리, 서비스별·태그별·전체 글 목록과 검색 인덱스, 기존 문서 유형별 색인은 빌드 시 자동 생성한다. 기존 원문·서비스·유형별 색인 URL은 보존한다. 브라우저에서 Markdown을 다시 읽거나 별도의 수동 문서 목록을 동기화하는 구조를 추가하지 않는다.
- 서비스별·태그별 중메뉴 페이지와 `전체 글` 페이지의 본문·카드·링크·문서 수 역시 생성 결과다. 개별 글을 추가·수정할 때 이 페이지나 메뉴의 콘텐츠를 수동으로 수정하지 않는다.
- `mkdocs.yml`과 `docs/.nav.yml`은 사이트 공통 설정과 대메뉴 구성에만 사용한다. 새 서비스·기술·태그를 처음 도입할 때의 공통 분류 등록은 `docs-taxonomy.yml`에서 처리한다.
- 홈의 대표 글은 문서의 `featured: true`로 지정한다. 문서·서비스·사용된 태그 수와 서비스·태그·전체 글 탐색 카드도 자동 생성한다. 생성기에 특정 문서·서비스·태그 경로나 제목 목록을 하드코딩하지 않는다.
- 게시 자동화를 바꿀 때는 기존 설정·taxonomy·홈·문서를 그대로 두고 기존 분류의 Markdown bundle 하나만 추가해 재빌드하는 통합 테스트로 검증한다. 메뉴·서비스별/태그별 중메뉴 페이지·전체 글·홈 통계·검색이 자동 갱신되는지 확인하며, 설정 파일의 문자열이 존재하는지만 검사하는 테스트로 대체하지 않는다.

## Reader interface

- 공개 사이트 이름은 `Azure Engineering Notes`, 부제는 `Azure 기반 시스템의 설계·구현·운영 기록`이다. 저장소 이름과 URL의 `hellices/devguidesample`은 유지한다.
- 독자는 개발자다. 제목과 설명은 구체적인 증상, 기술적 선택, 관측과 판단의 근거를 드러내고 일반적인 홍보 문구나 관료적인 표현을 피한다.
- 대메뉴는 `홈`, `서비스별 보기`, `태그별 보기`, `전체 글`, `기여하기`로 구성한다. 사이드바의 주요 글 경로는 서비스별 보기 → 서비스 → 문서다. 문서 이름은 front matter의 `title`, 서비스 이름은 taxonomy를 사용하고 bundle 폴더를 불필요한 추가 단계로 노출하지 않는다.
- 서비스 목록은 front matter의 `services` 전체를 반영한다. 사이드바에는 bundle 폴더의 대표 서비스 아래 원본 글을 한 번만 배치하며 모든 수명주기 유형을 함께 보여준다. `cases`·`guides`·`labs`·`research`는 내부 작성·수명주기 분류로 유지하되 유형별 대메뉴나 독자 목록·대표 글의 유형 배지·색상 구분에 사용하지 않는다.
- 태그별 보기 → 해당 태그의 글 목록 → 원문으로 연결한다. 문서 상단과 카드의 태그는 검색이 아니라 동일한 태그별 목록으로 연결하고, 해당 태그가 front matter에 정확히 지정된 글만 보여준다. 사용된 태그와 글 수는 자동 생성하며 전체 글 목록에는 각 원본 글을 한 번만 표시한다.
- 그룹은 접기·펼치기가 가능하고 현재 문서의 경로만 기본으로 열린다. `navigation.sections`나 `navigation.expand`로 모든 그룹을 강제로 펼치지 않는다.
- 큰 화면에서는 전체 문서 사이드바를, 작은 화면에서는 햄버거 메뉴를 제공한다. 들여쓰기·굵기·구분선으로 계층을 표시하고 현재 문서를 강조한다.
- 글자 크기는 GitHub Markdown 수준을 기준으로 한다: 본문 16px, H1 32px, H2 24px, H3 20px, 코드 약 13.6px. 홈 제목만 과도하게 키우지 않으며 밝은·어두운 테마와 모바일에서도 실제 크기·가독성을 확인한다.
- 검토 상태와 확인일은 사실대로 메타데이터에 유지하되, 마이그레이션·검토 미완료 같은 관리용 안내를 본문 배너나 목록 배지로 자동 노출하지 않는다. 출처 링크와 실제 기술적 제약·비용 경고는 보존한다.

## Content lifecycle

- 발생 시점의 환경, 관측값, 조사와 해결 이력은 `cases`에 보존한다.
- 현재 권장 절차, 지원 상태와 버전별 차이는 `guides`에서 계속 갱신한다.
- 당시 증거를 보존하는 사례와 현재 절차를 갱신하는 가이드의 수명주기가 다르면 문서를 분리하고 `related_cases`·`related_guides`로 연결한다. `guides`·`research`의 연관된 비교·분석과 적용 절차는 한 문서에 함께 담을 수 있다.
- 실행 가능한 프로젝트, 배포 매니페스트와 대용량 결과물은 `samples/`에 두고 문서에서는 GitHub 소스 링크를 사용한다.
- 페이지에서 렌더링할 이미지만 같은 bundle의 `images/`에 두며 의미 있는 대체 텍스트를 작성한다.

## Official-source verification

- Microsoft 또는 Azure의 동작, 지원 여부, 제한, 버전, 구성 단계, CLI/API 사용법을 추가하거나 바꿀 때 `.github/skills/verify-with-microsoft-learn/SKILL.md`의 `verify-with-microsoft-learn` skill을 반드시 사용한다.
- Microsoft Learn MCP 검색 뒤 선택한 원문 전체를 조회하고, 주장과 적용 범위를 비교한다.
- `official_sources`, `sources_checked_at`, `verification_status`는 실제 검증 결과와 일치시킨다. URL만 추가한 것은 검증이 아니다.
- Microsoft Learn이 최종 권위가 아닌 Kubernetes·CNCF 세부 동작은 upstream 공식 문서도 함께 확인한다.
- 의미 검증을 완료하지 못하면 `verification_status: needs-review`로 남기고 완료했다고 표현하지 않는다.

## Public safety

- 고객·조직·사용자 실명, 구독·테넌트 ID, 비밀, 연결 문자열, 내부 URL·IP·호스트명, 개인정보가 담긴 로그와 승인되지 않은 화면을 공개 문서에 넣지 않는다.
- 실제 식별자는 문서 전체에서 일관된 가상 값으로 치환한다.
- `.azure/`, `.claude/`, `.DS_Store`, `sim-env.json`과 실습 실행으로 생성된 `evidence/`는 로컬 상태이며 커밋하지 않는다. 이미 추적 중인 파일은 ignore 규칙만 추가해도 제외되지 않으므로 로컬 파일을 보존하면서 Git 추적도 해제한다.
- 공유 개발 설정(`.vscode/mcp.json`, `.devcontainer/`)과 예제 입력(`.env.example`, 배포 매개변수), 공개용으로 정리한 샘플 자료는 로컬 상태와 구분해 유지한다.
- 완료된 일회성 구축 계획·설계 기록은 현재 작성 지침과 구분하고 세션 또는 로컬 보관소에 남긴다. 공개 문서나 샘플에서 참조하는 자료·다이어그램 원본은 생성 파일 또는 중복이라는 이유만으로 삭제하지 않는다.

## Required validation

문서 CI는 `tests/docs`와 공개 문서·사이트 검증을 대상으로 한다. SRE 실습 등 `samples/`의 애플리케이션 테스트나 의존성을 문서 CI에 묶지 않는다. 게시 스크립트나 사이트 동작을 변경하면 `python -m pytest tests/docs -q`도 실행한다.

문서 또는 사이트 구성을 변경한 뒤 저장소 루트에서 실행한다.

```powershell
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
```

테스트나 검증 실패를 무시하거나 생성된 `site/` 및 검색 인덱스를 커밋하지 않는다.
