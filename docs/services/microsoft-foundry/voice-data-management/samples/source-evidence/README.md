# 음성 AI 데이터 보관 리서치 근거 원장

이 artifact는 2026-10-17에 발행한 음성 AI 데이터 보관 리서치의 구조화
근거를 보존합니다.

| 파일 | 내용 |
|---|---|
| `voice-data-policy-evidence-2026-10-17.json` | 실제 서비스 사례, 정책, 법·규제와 품질 관련 중요 주장 |
| `azure-voice-agent-storage-evidence-2026-10-17.json` | Microsoft·Azure 저장, 오디오 형식, 압축, 수명주기와 성능 관련 중요 주장 |

JSON 안의 `checked_on`은 각 원문을 실제로 대조한 날짜입니다. 파일명의
2026-10-17은 공개 리서치 발행일이며, 모든 원문을 같은 날 다시 검증했다는
뜻이 아닙니다.

## 사용

두 파일은 topic의 `downloads/` 경로로 게시됩니다. 사람이 읽을 때는
각 문서 본문과 함께 보고, 자동 검증에서는 claim의 `source_ids`가 실제
source ID를 가리키는지 확인합니다.

## 검증

저장소 루트에서 다음 검증을 실행합니다.

```bash
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
```
