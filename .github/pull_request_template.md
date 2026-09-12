## 변경 내용

변경 목적과 독자가 얻는 결과를 간단히 적어 주세요.

## 공개 문서 체크리스트

- [ ] 사례·가이드·실습·리서치 중 올바른 문서 유형과 폴더를 선택했습니다.
- [ ] 필수 front matter와 `docs-taxonomy.yml`의 분류 값을 사용했습니다.
- [ ] Microsoft/Azure 기술 주장을 Microsoft Learn MCP와 `verify-with-microsoft-learn` skill로 원문까지 확인했습니다.
- [ ] 실제 구독·테넌트 ID, 비밀, 내부 URL·IP·호스트명 등 공개 안전성 문제를 제거했습니다.
- [ ] 필요한 경우 현재 가이드와 시점 고정 사례를 분리하고 서로 연결했습니다.
- [ ] 아래 로컬 검증을 통과했습니다.

```powershell
python -m pytest tests/docs -q
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
```
