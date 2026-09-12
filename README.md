# DevGuideSample

실제 Azure 문제 해결 이력과 지속적으로 갱신하는 기술 가이드를 외부에 공개하는 문서 저장소입니다.

## 문서 사이트

**[DevGuideSample GitHub Pages에서 검색하기](https://hellices.github.io/devguidesample/)**

사이트에서는 한국어·영어 전체 텍스트, 제품명, 오류 메시지와 태그로 모든 공개 문서를 검색할 수 있습니다.

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
