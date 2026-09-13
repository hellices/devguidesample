# Repository instructions

## Public documentation contract

- 상세 기준은 `docs/contributing/index.md`를 단일 설명 문서로 사용한다.
- 공개 기술 문서는
  `docs/services/<service>/<topic>[/<child>]/index.md` topic package로
  작성한다.
- topic entry는 `<topic>/index.md`이며 `topic_order`를 쓰지 않는다. 연결된
  자식 문서는 `<topic>/<child>/index.md`에 두고 `topic_order`를 1부터
  중복 없이 연속으로 지정한다.
- `document_type`은 `case`, `guide`, `lab`, `research` 중 하나이며
  collection 호환 색인과 수명주기 규칙을 선택한다. 물리 경로에는
  collection 이름을 사용하지 않는다.
- Azure 제품의 `<service>`는 `azure-`와 공식 전체 제품명을 kebab-case로
  조합한다. 이름이 `Microsoft`로 시작하는 제품은 `microsoft-` slug를
  사용하고, 그 밖의 제품은 공식 프로젝트·제품명을 kebab-case로 사용한다.
- 새 서비스, 기술 또는 태그가 필요할 때만 `docs-taxonomy.yml`을 함께
  수정한다.
- 개별 문서를 추가하기 위해 `mkdocs.yml`, `docs/.nav.yml`, README 또는
  수동 문서 목록을 수정하지 않는다.

## Topic samples and redirects

- 실행 가능한 프로젝트, 배포 매니페스트와 대용량 결과물은
  `docs/services/<service>/<topic>/samples/<sample>/`에 둔다.
- 각 sample에는 `sample.yml`과 `README.md`가 필요하다. manifest의
  `kind`는 `runnable` 또는 `artifact`이며, `used_by`는 `index` 또는 직접
  자식 slug를 중복 없이 지정한다.
- 최상위 `samples/`에는 공개 콘텐츠를 추가하지 않는다.
- 페이지에서 렌더링할 이미지만 같은 bundle의 `images/`에 두며 의미 있는
  대체 텍스트를 작성한다.
- 이전 공개 URL은 canonical 문서의 `redirect_from`으로 보존한다. redirect
  경로에 원본 Markdown을 다시 만들지 않는다.

## Publishing automation

- 메뉴 트리, 서비스별·태그별·전체 글 목록, 검색 인덱스, collection 호환
  색인과 이전 URL redirect page는 빌드 시 자동 생성한다.
- 대메뉴는 `홈`, `서비스별 보기`, `태그별 보기`, `전체 글`, `기여하기`다.
  서비스 branch 아래에는 canonical topic entry와 순서가 있는 자식 문서만
  배치한다. redirect page와 collection 호환 색인은 이 branch에 넣지 않는다.
- 서비스 목록은 front matter의 `services` 전체를 반영한다. 사이드바에는
  경로의 대표 서비스 아래 원본 topic을 한 번만 배치한다.
- 태그 링크는 정확히 일치하는 태그별 목록으로 연결한다. 전체 글에는 각
  canonical 문서를 한 번만 표시한다.
- 홈 대표 글은 topic entry의 `featured: true`로 지정한다. 생성기에 특정
  문서·서비스·태그 경로나 제목 목록을 하드코딩하지 않는다.
- sample 파일은 public-safety 검사 대상이지만 MkDocs 사이트와 검색
  인덱스에는 포함하지 않는다.

## Content lifecycle

- 발생 시점의 환경, 관측값, 조사와 해결 이력은 `document_type: case`로
  보존한다.
- 현재 권장 절차, 지원 상태와 버전별 차이는 `document_type: guide`에서
  계속 갱신한다.
- 재현 가능한 실습은 `document_type: lab`, 비교·벤치마크·아키텍처 조사는
  `document_type: research`를 사용한다.
- 당시 증거를 보존하는 사례와 현재 절차를 갱신하는 가이드의 수명주기가
  다르면 문서를 분리하고 `related_cases`·`related_guides`로 연결한다.

## Official-source verification

- Microsoft 또는 Azure의 동작, 지원 여부, 제한, 버전, 구성 단계,
  CLI/API 사용법을 추가하거나 바꿀 때 repository skill
  `verify-with-microsoft-learn`을 반드시 사용한다.
- Microsoft Learn MCP 검색 뒤 선택한 원문 전체를 조회하고 주장과 적용
  범위를 비교한다.
- `official_sources`, `sources_checked_at`, `verification_status`는 실제
  검증 결과와 일치시킨다. URL만 추가한 것은 검증이 아니다.
- Microsoft Learn이 최종 권위가 아닌 Kubernetes·CNCF 세부 동작은
  upstream 공식 문서도 함께 확인한다.
- 의미 검증을 완료하지 못하면 `verification_status: needs-review`로
  남기고 완료했다고 표현하지 않는다.

## Public safety

- 고객·조직·사용자 실명, 구독·테넌트 ID, 비밀, 연결 문자열, 내부
  URL·IP·호스트명, 개인정보가 담긴 로그와 승인되지 않은 화면을 공개
  문서나 sample에 넣지 않는다.
- 실제 식별자는 문서와 sample 전체에서 일관된 가상 값으로 치환한다.
- `.azure/`, `.claude/`, `.DS_Store`, `sim-env.json`과 실행 중 생성된
  `evidence/`는 로컬 상태이며 커밋하지 않는다.
- 공유 개발 설정, 예제 입력과 비식별화한 공개 sample은 로컬 상태와
  구분해 유지한다.

## Required validation

문서 또는 사이트 구성을 변경한 뒤 저장소 루트에서 실행한다.

```powershell
python -m pytest tests/docs -q
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
```

테스트나 검증 실패를 무시하거나 생성된 `site/` 및 검색 인덱스를 커밋하지
않는다. sample 애플리케이션의 별도 테스트나 의존성은 해당 sample 변경
범위에서만 실행한다.
