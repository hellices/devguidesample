# Azure Engineering Notes

Azure 기반 시스템의 설계·구현·운영 기록을 공유합니다. 실제 문제 해결 이력과 지속적으로 갱신하는 기술 가이드를 공개하는 문서 저장소입니다.

## 문서 사이트

**[Azure Engineering Notes에서 문서 보기](https://hellices.github.io/devguidesample/)**

사이트에서는 서비스별·태그별 보기로 글을 탐색할 수 있으며, 태그별 목록에는 front matter의 `tags`에 해당 태그가 정확히 지정된 글만 포함됩니다. 이와 별도로 전체 텍스트 검색에서 한국어·영어 제목과 본문, 제품명, 오류 메시지를 찾을 수 있습니다.

| 모음 | 용도 |
|---|---|
| 문제 해결 사례 | 특정 시점의 증상, 조사, 근본 원인과 해결 결과를 보존합니다. |
| 일반 가이드 | 현재 재사용할 수 있는 절차를 제품 변화에 따라 계속 검증하고 갱신합니다. |
| 실습 | 배포, 실행, 검증과 정리를 재현할 수 있는 시나리오입니다. |
| 리서치 | 비교, 벤치마크와 아키텍처 조사를 기준 시점과 함께 기록합니다. |

전체 문서 목록은 파일로 중복 관리하지 않습니다. 올바른 폴더와 front matter를 사용하면 Pages 메뉴, 서비스 색인과 태그 색인에 자동으로 포함됩니다.

## 로컬 미리보기

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-docs.txt
.\.venv\Scripts\mkdocs serve
```

자세한 작성·검증 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md)를 확인하세요.

> 이 저장소와 Pages는 공개되어 있습니다. 고객·사용자 식별자, 구독·테넌트 ID, 비밀, 내부 URL 또는 승인되지 않은 화면 캡처를 커밋하지 마세요.
