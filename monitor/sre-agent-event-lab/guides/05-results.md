# 05. 결과 읽기와 채점

수집한 근거만으로 세 시나리오를 채점하고, 사람이 판단해야 하는 부분을 남김없이 드러내는 단계입니다.

## 시작 조건

- 세 시나리오의 `run`과 `capture`가 끝났습니다.
- `evidence/state.json`에 `s3_captured`가 있습니다.
- 각 시나리오 디렉터리에 `normalized-timeline.json`이 있습니다.

## 실행 명령

```bash
cd monitor/sre-agent-event-lab
./scripts/lab.sh score
```

`evidence/scorecard.json`과 `SCENARIO<TAB>CRITERION<TAB>STATUS<TAB>POINTS<TAB>DETAIL` 표를 출력합니다. 종합 판정이 `FAIL`일 때만 종료 코드 1을 반환합니다.

## 채점 기준

시나리오마다 10점입니다.

| 항목 ID | 뜻 | 배점 |
|---|---|---:|
| `impact_scope` | 영향 범위를 특정했는가 | 2 |
| `direct_cause` | 직접 원인을 지목했는가 | 3 |
| `actual_evidence` | 실제 근거를 인용했는가 | 2 |
| `safe_minimum_mitigation` | 되돌리기 가능한 최소 완화책인가 | 2 |
| `uncertainty` | 불확실한 부분을 밝혔는가 | 1 |

- Pass: 8점 이상
- Partial: 5~7점
- Fail: 4점 이하

시나리오의 `run_status`가 `recovered`가 아니면 채점기는 capture 내용과 관계없이 모든 항목을 `FAIL`·0점으로 기록합니다.

한 번 `conclusion`으로 끝난 capture는 같은 실행에서 다시 수집할 수 없습니다. 두 번째 결과가 필요하면 해당 시나리오를 다시 실행해 새 attempt와 evidence 디렉터리를 만든 뒤 capture합니다.

`impact_scope`는 alert 규칙 자체의 scope를 그대로 옮겨 적는 것으로는 채워지지
않습니다. 이 랩의 모든 alert는 Log Analytics workspace scope입니다
(`infra/alerts.bicep`의 `scopes`/`targetResourceTypes:
Microsoft.OperationalInsights/workspaces`). 텔레메트리 행이 담은
`_ResourceId`도 workspace가 아니라 Application Insights 리소스를 가리킬 뿐,
둘 다 워크로드가 아닙니다. `AppRoleName`/`Name`에서 실제 영향받은 Container
App과 엔드포인트(`/api/orders`, `/api/documents`)를 짚었을 때만 이 항목을
충족한 것으로 봅니다.

## 사람이 채워야 하는 판정

점수를 주는 근거는 시나리오 디렉터리의 `conclusion-review.json`입니다. 항목마다 `{"met": true|false, "detail": "..."}`를 기록합니다.

```json
{
  "impact_scope": { "met": true, "detail": "2번 메시지가 /api/orders만 영향으로 특정" },
  "direct_cause": { "met": false, "detail": "배포 변경이라고만 하고 어떤 설정인지 지목하지 못함" }
}
```

기록이 없는 항목은 `MANUAL`로 표시되고 **점수를 주지 않습니다**. 읽지 않은 결론에 점수를 주는 것보다, 아직 읽지 않았다고 말하는 편이 정확하기 때문입니다.

## 결과 해석

| 출력 | 뜻 | 할 일 |
|---|---|---|
| 항목 `MANUAL` | 사람이 아직 판정하지 않음 | 스레드 결론을 읽고 `conclusion-review.json`에 기록한 뒤 다시 채점 |
| 시나리오 `FAIL` 0점 | 캡처가 결론에 이르지 못함 | 사유가 DETAIL에 남습니다. 해당 시나리오 문서의 실패 표를 참고 |
| 종합 `INCOMPLETE` | `MANUAL`이 남아 총점이 하한값 | 남은 판정을 채웁니다 |
| 종합 `PASS` | 모든 시나리오가 Partial 이상이고 두 개 이상 Pass | 결과를 정리하고 리소스를 지웁니다 |

캡처가 `thread-not-created`, `investigation-missing`, `conclusion-missing`으로 끝난 시나리오는 모든 항목이 `FAIL` 0점입니다. 이때 점수가 낮은 것은 제품 판단이 아니라 근거가 없다는 사실의 기록입니다.

## 남겨 둘 것

- `assets/captures/s1`, `s2`, `s3`의 PNG·GIF·Markdown은 커밋 대상입니다.
- `evidence/` 아래 원본 스냅샷과 `scorecard.json`은 Git에서 제외됩니다. 필요하면 별도로 보관하세요.
- 결론을 공유할 때는 구독 ID, 엔드포인트 FQDN, 토큰이 화면에 남지 않았는지 먼저 확인합니다.

티켓과 이메일 초안 같은 운영 산출물은 정규화된 타임라인에서 다시 만들 수 있습니다. `generate_notifications.py`는 표준 라이브러리만 사용하므로(Pillow가 필요한 `render_capture.py`와 달리) `app/.venv` 없이 시스템 `python3`로 바로 실행합니다.

```bash
python3 scripts/generate_notifications.py \
  --timeline evidence/s1-<타임스탬프>/normalized-timeline.json \
  --output-dir assets/notifications \
  --report-url validation-results.md
```

## 다음 단계

실습이 끝났으면 바로 정리합니다. 리소스를 남겨 두면 계속 과금됩니다.

```bash
azd down --purge
```

정리 훅이 무엇을 지우는지, 확인 프롬프트에서 취소하면 무엇이 남는지는 [README의 정리 절](../README.md)에 있습니다.
