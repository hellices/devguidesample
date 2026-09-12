# 기여하기

새 공개 문서는 `docs/<collection>/<service>/<topic>/index.md`에 추가합니다. 올바른 폴더와 front matter를 사용하면 메뉴와 색인은 빌드 시 자동 생성됩니다.

문서 유형 선택, 메타데이터, 본문 구조, 태그, 이미지와 공개 안전성의 기준 문서는 [상세 기여 지침](docs/contributing/index.md)입니다.

Microsoft 또는 Azure 기술 내용을 새로 쓰거나 바꿀 때는 repository skill `verify-with-microsoft-learn`을 사용해 Microsoft Learn 원문과 대조하고 출처 메타데이터를 갱신해야 합니다.

제출 전 다음을 실행하세요.

```powershell
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
```
