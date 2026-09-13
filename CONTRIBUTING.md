# 기여하기

새 공개 문서는
`docs/services/<service>/<topic>[/<child>]/index.md`에 추가합니다.
`document_type`은 `case`, `guide`, `lab`, `research` 중 문서의 수명주기에
맞게 선택하지만 물리 폴더에는 사용하지 않습니다.

`tags`에는 taxonomy의 목적·주제 통제 태그를 1–4개 지정하고 목적을 먼저
배치합니다. 중복 태그나 기술을 대신하는 태그는 추가하지 않습니다.
글 찾기는 모든 주제를 묶어 보여 주며 선택한 태그·서비스·기술·제목/설명
조건을 모두 충족하는 문서만 각 topic에 표시합니다. 주제 수와 문서 수를
함께 표시하고 일치 문서로 바로 연결합니다. 이전 태그 주소는 문서가 아닌
taxonomy의 `legacy_tag_redirects`에서 관리합니다.

실행 코드, 배포 매니페스트와 결과물은
`docs/services/<service>/<topic>/samples/<sample>/`에 `sample.yml`과
`README.md`를 포함해 둡니다. 최상위 collection 폴더와 `samples/`에는 새
공개 콘텐츠를 추가하지 않습니다.

문서 유형, topic/child 순서, redirect, sample manifest, 메타데이터, 이미지,
공개 안전성의 단일 기준은
[상세 기여 지침](docs/contributing/index.md)입니다.

Microsoft 또는 Azure 기술 내용을 새로 쓰거나 바꿀 때는 repository skill
`verify-with-microsoft-learn`을 사용해 Microsoft Learn 원문과 대조하고
출처 메타데이터를 갱신해야 합니다.

제출 전 다음을 실행하세요.

```powershell
python -m pytest tests/docs -q
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
```
