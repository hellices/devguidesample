# Azure Engineering Notes

Azure 기반 시스템의 설계·구현·운영 기록을 공유합니다. 실제 문제 해결 이력과 지속적으로 갱신하는 기술 가이드를 공개하는 문서 저장소입니다.

## 문서 사이트

**[Azure Engineering Notes에서 문서 보기](https://hellices.github.io/devguidesample/)**

사이트에서는 **서비스별 보기** 또는 **글 찾기**로 탐색합니다. 글 찾기는 모든 주제를 카드로 묶고 서비스, 목적·주제 태그, 기술, 제목·설명으로 좁힙니다. 태그 하나를 선택하면 그 태그가 붙은 문서만, 여러 태그를 선택하면 모든 태그가 붙은 문서만 주제 안에 표시하며 각 문서로 바로 연결합니다. 서비스·기술·검색어도 같은 문서에 AND로 적용됩니다. 결과에는 주제 수와 문서 수를 함께 표시합니다. 별도의 전체 텍스트 검색에서는 한국어·영어 제목과 본문, 제품명, 오류 메시지를 찾을 수 있습니다.

글 찾기의 제목·설명 검색어는 반복 가능한 `text`로 공유합니다
(예: `/explore/?tag=design&text=Agent&text=Memory`).
`q`는 사이트 전체 검색 전용이며 글 찾기의 필터 변경·초기화로 지우지 않습니다.
전체 검색 창을 닫아도 글 찾기의 `text` 조건은 유지됩니다.

| 모음 | 용도 |
|---|---|
| 문제 해결 사례 | 특정 시점의 증상, 조사, 근본 원인과 해결 결과를 보존합니다. |
| 일반 가이드 | 현재 재사용할 수 있는 절차를 제품 변화에 따라 계속 검증하고 갱신합니다. |
| 실습 | 배포, 실행, 검증과 정리를 재현할 수 있는 시나리오입니다. |
| 리서치 | 비교, 벤치마크와 아키텍처 조사를 기준 시점과 함께 기록합니다. |

모든 주제 목록은 파일로 중복 관리하지 않습니다. 올바른 폴더와 front matter를 사용하면 Pages 메뉴, 서비스 색인과 글 찾기에 자동으로 포함됩니다. 기존 `/tags/`, `/articles/` 및 이전 태그 주소는 검색·메뉴에서 제외된 글 찾기 redirect로 유지합니다.

공개 문서의 canonical 원본은
`docs/services/<service>/<topic>[/<child>]/index.md` topic package입니다.
실행 코드와 결과물은 해당 topic의 `samples/<sample>/`에 두며, 최상위
collection 폴더나 `samples/`에는 새 공개 콘텐츠를 추가하지 않습니다.

## 로컬 미리보기

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-docs.txt
.\.venv\Scripts\mkdocs serve
```

자세한 작성·검증 규칙은
[공개 문서 작성 계약](docs/contributing/index.md)을 확인하세요.
검색 인덱스 검증 다음에는 `python scripts/docs/audit_pre_pages.py`로
과거 공개 콘텐츠와 호환 URL 보존을 확인하며, 얕은 clone이면 `a4e6801`,
`9ace9667`가 포함되도록 전체 이력을 먼저 가져와야 합니다.

> 이 저장소와 Pages는 공개되어 있습니다. 고객·사용자 식별자, 구독·테넌트 ID, 비밀, 내부 URL 또는 승인되지 않은 화면 캡처를 커밋하지 마세요.
