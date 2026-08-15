# 02. S1 — HTTP 500 장애

주문 API가 500을 반환하도록 바꾸고, Azure Monitor Sev2 경고가 발생한 뒤 Agent가 원인을 짚어내는지 봅니다.

## 시작 조건

- [01-agent-setup.md](01-agent-setup.md)를 마쳤고 `evidence/state.json`에 `baseline_passed`와 `agent_setup_acknowledged`가 기록되어 있습니다.
- 현재 활성 구독이 azd 환경의 구독과 같습니다.

이 두 가지만 `evidence/state.json`을 통해 실제로 강제됩니다. 여기에 더해, 어떤 시나리오든 실행이 `running`이나 `failed`로 남아 있으면 세 시나리오 모두 새 실행이 거부됩니다. 세 시나리오는 같은 Container App 하나를 쓰고, 끝나지 않은 실행은 장애가 아직 살아 있을 수 있는 상태이기 때문입니다. 거부 메시지는 어떤 시나리오가 어떤 상태로 막고 있는지와 해결 명령을 함께 알려 줍니다. `failed`는 그 시나리오를 다시 실행하면 풀리고, `running`은 실행이 끝나기를 기다리거나 `python3 scripts/lab_state.py mark-failed s1`처럼 끝난 방식을 기록해야 풀립니다. 잠금까지 제공하지는 않으므로(1인 운영자 전제) 두 터미널에서 같은 명령을 정확히 동시에 띄우는 경우는 여전히 운영자가 피해야 합니다.

조건이 하나라도 없으면 실행이 시작 전에 거부되고 무엇을 먼저 하라는 안내가 출력됩니다.

## 실행 명령

```bash
cd monitor/sre-agent-event-lab
./scripts/lab.sh run s1
```

한 번의 실행이 장애 주입 → 부하 → 경고 대기 → 복구 → 타임라인 저장까지 진행합니다. 경고가 발생하지 않으면 12분 뒤 실패로 기록하고 종료합니다. 스크립트를 중간에 끊어도 종료 트랩이 복구를 시도합니다.

경고가 발생하고 복구까지 끝나면 조사 근거를 수집합니다.

```bash
./scripts/lab.sh capture s1
```

수집 대상 디렉터리는 방금 실행이 `evidence/state.json`에 기록한 값에서 정해지므로 경로를 직접 입력하지 않습니다.

같은 UTC 구간의 KQL 근거를 따로 내보내려면 실행이 남긴 `timeline.json`의 시각을 그대로 넣어 호출합니다.

```bash
./scripts/query-evidence.sh s1 evidence/s1-<타임스탬프> <시작 UTC> <끝 UTC>
```

## Azure에서 발생하는 변화

| 순서 | 변화 |
|---|---|
| 1 | Container App에 `FAILURE_MODE=http500` 환경 변수가 설정되어 새 revision이 만들어집니다 |
| 2 | `/api/orders`에 요청 120건(동시 4)이 들어가고 모두 HTTP 500을 받습니다 |
| 3 | Application Insights workspace 테이블 `AppRequests`에 `ResultCode == "500"` 레코드가 쌓입니다 |
| 4 | 5분 창의 500 응답이 10건을 넘으면 `alert-sre-lab-s1-http500`(Sev2)이 발생합니다 |
| 5 | 복구로 `FAILURE_MODE=none` revision이 다시 배포되고 경고가 자동 해제됩니다 |

## SRE Agent에서 확인할 항목

`https://sre.azure.com`에서 새 스레드를 열고 다음을 확인합니다.

- 경고 접수 시각과 스레드 생성 시각의 간격
- 조사 계획이 업로드한 운영 문서의 순서를 따르는지
- 영향 범위를 `/api/orders`로 좁혔는지, 앱 전체로 뭉뚱그리지 않았는지
- 직접 원인으로 최근 revision의 환경 변수 변경을 지목했는지
- 완화책을 제안만 하고 승인을 기다리는지(Review 모드)

`capture`가 만드는 `assets/captures/s1/`의 PNG·GIF·Markdown이 같은 내용을 담습니다.

## 성공·부분 성공·실패 판정

`capture`는 스레드의 마지막 상태를 그대로 기록합니다.

| 기록된 상태 | 의미 | 다음 시나리오 |
|---|---|---|
| `conclusion` | Agent가 구조화된 결론을 냈습니다 | 열립니다 |
| `investigation-missing` | 스레드는 열렸지만 조사 단계가 없습니다 | 막힙니다 |
| `conclusion-missing` | 조사는 했지만 결론에 도달하지 못했습니다 | 막힙니다 |
| `thread-not-created` | 경고가 Agent에 도달하지 못했습니다 | 막힙니다 |

성공은 `conclusion` 하나뿐입니다. 부분 성공은 결론이 나왔지만 내용이 얕은 경우이며, 이때도 상태는 `conclusion`이고 점수는 [05-results.md](05-results.md)의 채점에서 갈립니다. 빈 성공 화면을 만들지 않고 누락 상태와 마지막 확인 시각을 그대로 그림에 남깁니다.

`thread-not-created`가 나오면 [01-agent-setup.md](01-agent-setup.md)의 incident platform과 응답 계획부터 다시 확인합니다.

## 복구 확인

복구는 두 가지가 모두 확인된 뒤에만 기록됩니다.

1. Container App의 활성 revision이 다시 정상입니다.
2. 이 실행이 발생시킨 경고가 Azure Monitor에서 `Resolved`가 됩니다.

경고 해제는 최대 25분, 워크로드 정상화는 최대 10분까지 기다립니다. 1분 주기의 stateful log alert는 실패 요청이 5분 조회 창에서 빠진 뒤에도 조건이 10분간 불충족이어야 `Resolved`가 되므로 여유 시간을 포함합니다. 둘 중 하나라도 시간 안에 확인되지 않으면 실행은 실패로 기록되고 S2는 계속 막힙니다. 실패한 실행은 원인을 고친 뒤 `./scripts/lab.sh run s1`을 다시 실행하면 새 시도로 이어집니다. 다시 실행하는 순간 이전 시도의 `s1_recovered`와 `s1_captured` 기록은 장애를 주입하기 전에 지워지므로, 새 시도가 복구되고 `capture`까지 끝날 때까지 S2는 다시 막힙니다. 이미 성공한 시나리오를 한 번 더 돌릴 때도 같습니다.

되돌리기 자체가 실패하면(예: `az containerapp update` 거부, 새 revision이 준비되지 않음) 스크립트는 `CRITICAL:` 두 줄을 출력하고 0이 아닌 코드로 끝냅니다. 주입한 장애가 그대로 남아 있다는 뜻이므로, 다음 시나리오를 실행하기 전에 `FAILURE_MODE=none`을 수동으로 되돌리고 revision이 정상인지 확인하세요.

```bash
azd env get-value AZURE_CONTAINER_APP_FQDN
```

로 얻은 FQDN에 `/api/orders`를 호출해 200이 돌아오는지 직접 확인할 수도 있습니다.

## 다음 단계

지연 장애로 넘어갑니다: [03-scenario-s2.md](03-scenario-s2.md)
