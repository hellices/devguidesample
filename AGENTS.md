# Repository instructions

## Public documentation contract

- 상세 기준은 `docs/contributing/index.md`를 단일 설명 문서로 사용한다.
- 공개 기술 문서는 `docs/<collection>/<service>/<topic>/index.md` page bundle로 작성한다.
- `<collection>`은 `cases`, `guides`, `labs`, `research` 중 하나이며 front matter의 `document_type`과 일치해야 한다.
- Azure 제품의 `<service>`는 `azure-`와 공식 전체 제품명을 kebab-case로 조합한다(예: `azure-kubernetes-service`).
- Microsoft 제품은 공식 명칭을 보존하여 이름이 `Microsoft`로 시작하면 `microsoft-` slug를 사용하고, 오픈소스와 그 밖의 제품은 공식 프로젝트·제품명을 kebab-case로 사용한다.
- 새 서비스, 기술 또는 태그가 필요할 때만 `docs-taxonomy.yml`을 함께 수정한다.
- 개별 문서를 추가하기 위해 `mkdocs.yml`, `docs/.nav.yml`, README 또는 수동 문서 목록을 수정하지 않는다. 빌드가 폴더와 메타데이터에서 메뉴·색인을 생성한다.

## Content lifecycle

- 발생 시점의 환경, 관측값, 조사와 해결 이력은 `cases`에 보존한다.
- 현재 권장 절차, 지원 상태와 버전별 차이는 `guides`에서 계속 갱신한다.
- 한 문서에 두 성격이 섞이면 사례와 가이드로 분리하고 `related_cases`·`related_guides`로 연결한다.
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

## Required validation

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
