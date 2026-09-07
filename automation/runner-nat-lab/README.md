# Runner 사설 IP 변경에 따른 NAT 경유 빌드 영향 테스트

## 1. 결론

**Runner VM의 사설 IP를 `10.77.2.10`에서 `10.77.2.20`으로 변경한 뒤에도, NAT·방화벽 규칙을 수정하거나 Runner를 재등록하지 않고 빌드가 성공했다.**

다음 조건에서 확인한 결과다.

- GitHub.com의 실제 self-hosted runner 사용. GHES와 Azure Secured Virtual Hub는 배포하지 않았다.
- Azure VM 두 대로 Runner와 Linux `nftables` NAT·방화벽을 분리했다.
- NAT 및 접근 허용 규칙은 이전 IP 한 개가 아니라 `10.77.2.0/24`를 대상으로 했다.
- Runner의 디스크, 등록 정보, 서비스, NAT IP, NSG, UDR를 유지했다.
- 동일한 workflow와 Oryx 이미지로 실제 저장소 애플리케이션을 빌드했다.
- 각 VM 중지 작업은 **빌드가 끝난 유휴 상태**에서 수행했다.

따라서 이 결과는 **“새 사설 IP가 기존 정책 범위에 포함된다면, IP 변경 자체가 NAT 경유 Runner의 새 빌드를 막지 않는다”**는 실측 근거다. 모든 NAT 정책이나 실제 Secure Hub 운영 환경에서 무조건 정상이라는 보장은 아니다.

## 2. 테스트 환경

| 항목 | 실제 구성 |
|---|---|
| 실행일 | 2026-09-07, 한국시간 |
| 리전 | Azure Korea Central |
| 전용 리소스 그룹 | `rg-runner-nat-ip-20260907` |
| 저장소 | `hellices/devguidesample` |
| 테스트 브랜치 | `test/runner-nat-ip-20260907` |
| NAT·방화벽 VM | `vm-nat`, Ubuntu 24.04, `Standard_B2s` |
| Runner VM | `vm-runner`, Ubuntu 24.04, `Standard_D2s_v5` |
| Runner | `nat-ip-lab-20260907`, Runner ID `21`, 버전 `2.337.0` |
| 빌드 대상 | [oryx-test](../../oryx-test)의 Flask 애플리케이션 |
| Python | 실제 빌드된 버전 `3.11.15` |
| 외부 노출 | Runner 공인 IP 없음. SSH 등 신규 인바운드 허용 없음 |
| 관리 방식 | Azure VM Run Command |
| 종료 상태 | 두 VM 모두 할당 해제. Runner 등록은 유지, 상태는 Offline |

연결은 **Runner가 GitHub.com으로 시작**한다. 빌드 코드는 GitHub 서버가 아니라 Runner VM에서 실행된다.

1. Runner: `10.77.2.10` 또는 `10.77.2.20`
2. Runner 서브넷의 UDR: `0.0.0.0/0 → VirtualAppliance 10.77.1.4`
3. Linux NAT: 원본 `10.77.2.0/24`를 `10.77.1.4`로 SNAT
4. Azure의 NAT VM 고정 Public IP 매핑을 통해 인터넷/GitHub.com 접근

Linux에서 관측한 패킷 증적은 **3번의 사설 주소 SNAT 전후**다. Azure 플랫폼의 공인 IP 변환을 외부 수신 서버에서 직접 캡처한 것은 아니다. 공인 IP 리소스가 변경되지 않았음은 Azure 조회 결과로 확인했다.

Azure DNS/플랫폼 에이전트 등 Azure 특수 통신과 애플리케이션의 인터넷 경유 경로는 구분한다. 본 테스트는 빌드 HTTPS 트래픽의 NAT 경유를 패킷으로 확인했다.

### 구성 파일

- [Bicep 인프라](../../infra/runner-nat-lab/main.bicep)
- [NAT·방화벽 cloud-init](../../infra/runner-nat-lab/nat-cloud-init.yml)
- [Runner 준비](prepare-runner.sh)
- [보호된 토큰을 사용하는 Runner 등록](register-runner.ps1)
- [Linux Runner 등록 및 서비스 설정](register-runner.sh)
- [NAT 증적 수집](capture-nat.sh)
- [테스트 workflow](../../.github/workflows/runner-nat-ip-test.yml)
- [실행 조건](case.json)

## 3. 검증 방법과 통제 조건

모든 정상 실험은 다음 단계를 실행했다.

1. 해당 테스트 브랜치 checkout.
2. 실제 OS 출발지 IP가 기대 IP와 일치하는지 assertion.
3. Runner ID, 이름, boot ID, UTC 시각, commit 기록.
4. 동일한 digest의 Oryx 이미지로 Python 3.11 빌드.
5. 빌드된 가상환경에서 Flask `/` 응답 코드 `200` 및 본문 검증.
6. 빌드 로그·manifest·식별 정보 artifact 업로드.
7. 같은 artifact 다운로드 후 원본 식별 정보와 `cmp`.

사용한 이미지 digest:

```text
mcr.microsoft.com/oryx/build@sha256:0c99dd3b778ca5a7b137ce5342bd8f4ca149b3741483a651422047aefdf79b35
```

기준 성공 commit `7ea8017`부터 IP 변경 성공 commit `782b96a`까지의 코드 차이는 **case.json의 시나리오 이름과 기대 IP뿐**이다. 기존 Oryx workflow와 애플리케이션 소스는 수정하지 않았다.

아래 항목은 IP 변경 전후 동일함을 확인했다.

| 통제 항목 | 증거 |
|---|---|
| Runner ID | 세 실행 모두 `21` |
| Runner 이름 | 세 실행 모두 `nat-ip-lab-20260907` |
| VM 재기동 | 세 실행의 boot ID가 서로 다름 |
| NAT 설정 파일 | SHA-256 동일 |
| 실제 로드된 nftables filter/NAT 규칙 | 카운터를 제외한 정책 SHA-256 동일 |
| NAT/Runner NSG 및 UDR | Azure 조회 JSON의 SHA-256 동일 |
| NAT 공인 IP | Azure 리소스 조회로 변경 없음 확인 |
| 빌드 이미지 | 세 실행의 image digest 동일 |
| Runner 재등록 | 최초 한 번만 등록. 재기동 및 IP 변경 중 등록 명령 미실행 |

## 4. 실측 결과

시간은 한국시간(KST), 소요 시간은 GitHub job의 `startedAt`~`completedAt` 기준이다. 성능 벤치마크가 아니라 기능 검증이다.

| 시나리오 | Runner IP | 실행 시각 | job 소요 | 결과 | 실행 링크 |
|---|---|---|---|---|---|
| 기준 빌드 | `10.77.2.10` | 11:19:45~11:20:24 | 39초 | 성공 | [34075920018](https://github.com/hellices/devguidesample/actions/runs/34075920018) |
| 같은 IP로 할당 해제/시작 | `10.77.2.10` | 11:23:00~11:23:40 | 40초 | 성공 | [34076095052](https://github.com/hellices/devguidesample/actions/runs/34076095052) |
| 사설 IP 변경 후 시작 | `10.77.2.20` | 11:26:05~11:26:48 | 43초 | 성공 | [34076271291](https://github.com/hellices/devguidesample/actions/runs/34076271291) |

IP 변경 실험의 관리 측 관측 시각:

- 11:24:12: Runner VM 할당 해제 요청.
- 11:24:46: 할당 해제 완료 관측.
- 11:24:51: NIC IP를 `10.77.2.20`으로 변경 완료.
- 11:25:36: 기존 Runner ID `21`의 Online 상태 관측.
- 11:26:48: 새 IP에서 실제 빌드 및 artifact 왕복 완료.

이 시각은 관리 명령/API 응답을 관측한 시점이다. 정확한 TCP 재연결 지연이나 무중단 시간을 측정한 값은 아니다.

### 성공 화면

#### 기준 빌드

![기준 빌드 성공](evidence/baseline/github-success.png)

#### 같은 IP 재기동

![같은 IP 재기동 후 성공](evidence/restart-control/github-success.png)

#### 사설 IP 변경

![사설 IP 변경 후 성공](evidence/private-ip-changed/github-success.png)

위 이미지는 실제 GitHub Actions 실행 페이지 캡처다. 화면의 전체 workflow 시간과 표의 job 시간은 집계 범위가 다를 수 있다. 상세 로그 열람에는 GitHub 로그인이 필요할 수 있으므로 주요 원본 증적을 이 브랜치에도 보관했다.

## 5. 네트워크 증거

### 변경 전: 10.77.2.10

11:23:19, 같은 IP 재기동 성공 실험 중 NAT NIC에서 관측:

```text
eth0 In  IP 10.77.2.10.58662 > 151.101.128.223.443: Flags [S], seq 30947337
eth0 Out IP 10.77.1.4.58662  > 151.101.128.223.443: Flags [S], seq 30947337
```

### 변경 후: 10.77.2.20

11:26:28, IP 변경 성공 실험 중 관측:

```text
eth0 In  IP 10.77.2.20.51166 > 151.101.128.223.443: Flags [S], seq 968024101
eth0 Out IP 10.77.1.4.51166  > 151.101.128.223.443: Flags [S], seq 968024101
```

동일 TCP sequence/목적지/포트의 패킷이 입력과 출력에서 각각 관측되며 출발지 IP만 바뀐다. **새 Runner IP가 기존 SNAT 규칙에 매칭되었음**을 확인할 수 있다.

연결 추적에도 새 IP의 세션이 생성됐다.

```text
ESTABLISHED src=10.77.2.20 dst=140.82.112.21 sport=51692 dport=443
            src=140.82.112.21 dst=10.77.1.4 sport=443 dport=51692 [ASSURED]
```

첫 튜플은 원래 방향, 두 번째 튜플은 NAT가 추적하는 응답 방향이다. 기존 `.10`의 세션을 `.20`으로 이전한 것이 아니라, **새 IP로 새 연결을 생성**한 것이다.

### 정책 동일성

IP 변경 전후 모두 다음 SHA-256이 일치했다.

```text
/etc/nftables.conf
472ff740b6d0877a08536f25162484d3cebd8c436fa57d74428b37b46bffa933

실제 filter 규칙 (nft --stateless list table inet lab_filter)
ff8fd503fdd803756fab3c5b66108f0747fb2c14d1b072950d3ccd93995eaa00

실제 SNAT 규칙 (nft --stateless list table ip lab_nat)
e009eff1f6064df82e015869bf0f750057b3ce3c1de85ae87bc2cd1689fc389c
```

원본:

- [변경 전 패킷·conntrack·정책 hash](evidence/before-ip-change-nat.txt)
- [변경 후 패킷·conntrack·정책 hash](evidence/after-ip-change-nat.txt)
- [NSG·UDR·공인 IP 비교](evidence/control-comparison.json)
- [IP 변경 관리 작업 시각](evidence/private-ip-change-lifecycle.json)
- [같은 IP 재기동 관리 작업 시각](evidence/restart-control-lifecycle.json)
- [변경 후 OS IP·Runner 서비스·버전](evidence/runner-final-online.txt)
- [기준 Runner 식별 정보](evidence/baseline/runner.json)
- [재기동 Runner 식별 정보](evidence/restart-control/runner.json)
- [IP 변경 Runner 식별 정보](evidence/private-ip-changed/runner.json)

각 시나리오 폴더에는 `github-run.json`, `oryx-build.log`, `oryx-manifest.toml`, `oryx-image.json`도 보관했다. GitHub artifact 보관 기간은 7일이며, 이 브랜치의 복사본은 artifact 만료와 별개다.

## 6. 재현 절차

현재 리소스는 보존하되 VM은 할당 해제한 상태다. 기존 환경을 다시 사용할 때는 NAT VM을 먼저 시작하고 방화벽 활성 상태를 확인한 후 Runner를 시작한다.

### 신규 환경 구성

아래는 PowerShell 예시다. `$subscription`에는 본인이 테스트할 구독 ID를 넣는다. 현재 테스트 리소스 그룹이나 다른 작업자의 리소스를 덮어쓰지 않도록 신규 실행은 별도 이름을 사용한다.

```powershell
$subscription = '<Azure subscription ID>'
$rg = 'rg-runner-nat-ip-20260907'
$pub = (Get-Content '<dedicated SSH public key file>' -Raw).Trim()

az group create --subscription $subscription --name $rg --location koreacentral
az deployment group validate --subscription $subscription -g $rg `
  --template-file .\infra\runner-nat-lab\main.bicep --parameters sshPublicKey="$pub"
az deployment group create --subscription $subscription -g $rg `
  --template-file .\infra\runner-nat-lab\main.bicep --parameters sshPublicKey="$pub"

az vm run-command invoke --subscription $subscription -g $rg -n vm-nat `
  --command-id RunShellScript `
  --scripts 'cloud-init status --wait; systemctl is-active nftables; sysctl net.ipv4.ip_forward'

az vm run-command invoke --subscription $subscription -g $rg -n vm-runner `
  --command-id RunShellScript --scripts '@automation\runner-nat-lab\prepare-runner.sh'

.\automation\runner-nat-lab\register-runner.ps1 `
  -SubscriptionId $subscription -ResourceGroup $rg
```

CLI가 성공해도 Run Command 내부 셸이 실패할 수 있다. `stdout`/`stderr`와 완료 마커를 확인하며, 등록 스크립트는 `instanceView.exitCode = 0`을 필수 조건으로 검사한다.

Runner 등록 토큰은 `gh`로 짧은 유효기간의 토큰을 발급받아 Azure Managed Run Command의 **protectedParameters**에 전달한다. 토큰은 소스, workflow, 증적, 일반 파라미터에 저장하지 않는다. 등록 후 managed Run Command 리소스를 삭제했다.

새 실험에서는 Runner 이름/label 및 workflow의 branch 조건을 충돌하지 않게 설정한다. 이 보고서의 기존 Runner를 그대로 재기동할 때에는 준비/등록 스크립트를 다시 실행하지 않는다.

### 기준 빌드와 같은 IP 재기동

1. 신규 배포의 초기 IP는 `.10`이다. `case.json`을 `baseline` / `10.77.2.10`으로 설정하고 전용 브랜치에 commit/push한다.
2. GitHub Actions의 모든 단계 성공과 artifact를 확인한다.
3. Runner가 유휴 상태인지 확인하고 다음을 실행한다.

```powershell
az vm deallocate --subscription $subscription -g $rg -n vm-runner
az vm start --subscription $subscription -g $rg -n vm-runner
```

4. 기존 Runner ID가 Online으로 복귀하는지 확인한다.
5. `case.json`의 case만 `restart-control`로 바꾸고 commit/push한다.

### 사설 IP 변경

직전 빌드 완료 후, **NAT·NSG·UDR는 변경하지 않고** 다음 작업만 수행한다.

```powershell
az vm deallocate --subscription $subscription -g $rg -n vm-runner
az network nic ip-config update --subscription $subscription -g $rg `
  --nic-name nic-runner --name ipconfig1 --private-ip-address 10.77.2.20
az vm start --subscription $subscription -g $rg -n vm-runner
```

`case.json`을 `private-ip-changed` / `10.77.2.20`으로 변경해 commit/push한다. 현재 브랜치는 이 마지막 상태다.

**실험 도중 Bicep 전체를 재배포하지 않는다.** 현재 템플릿의 초기 Runner IP는 `.10`이므로 재배포하면 실험용 수동 IP 변경을 되돌릴 수 있다.

빌드 실행 중 NAT 증적을 수집한다.

```powershell
az vm run-command invoke --subscription $subscription -g $rg -n vm-nat `
  --command-id RunShellScript --scripts '@automation\runner-nat-lab\capture-nat.sh'
```

등록 ID·boot ID·IP·이미지 digest·정책 hash와 GitHub 실행 결과를 함께 비교한다. 단순히 Runner가 Online인 것만으로 성공 판정하지 않는다.

## 7. 초기 구성 중 발견하고 수정한 사항

네트워크 본 실험 전에 테스트 도구의 문제를 수정했다. 이 실패들을 NAT/IP 변경 실패로 분류하지 않는다.

1. **Windows 줄바꿈:** Managed Run Command에 CRLF 스크립트를 전달해 `bash\r` 오류가 발생했다. Linux 스크립트 LF 속성을 지정하고 전송 시 LF로 정규화했다. 수정 후 등록 exit code는 `0`이었다.
2. **Oryx smoke-test 라이브러리 경로:** [첫 실행](https://github.com/hellices/devguidesample/actions/runs/34075637562)과 [두 번째 실행](https://github.com/hellices/devguidesample/actions/runs/34075798758)에서 Oryx 빌드와 패키지 다운로드는 성공했지만, 추가한 smoke test의 Python이 `libpython3.11.so.1.0`을 찾지 못했다. Oryx가 `venv --copies`로 구성한 사실을 VM에서 확인하고 `pyvenv.cfg`의 SDK home을 사용하도록 수정했다. 이후 동일 workflow로 세 본 실험이 모두 통과했다.
3. **도구 경고:** 설치된 Bicep CLI에 2026 API 스키마가 없어 BCP081 경고가 있었다. ARM validation과 실제 배포는 성공했다. GitHub는 기존 저장소와 같은 v4 Actions의 Node 20 폐기 경고를 표시했지만, 세 본 실험의 단계는 모두 성공했다.

## 8. 해석과 미검증 범위

### 이번에 확인한 것

- 새 Runner 사설 IP가 서브넷 단위 NAT·방화벽 정책에 포함되면, 정책 수정 없이 새 SNAT 세션을 생성한다.
- 기존 등록 정보가 보존되면 같은 Runner ID로 재접속한다.
- 신규 Runner 인바운드 허용 또는 Runner 대상 DNAT 없이 작업 수신과 실제 빌드가 가능했다.
- IP 변경 후 checkout, 외부 이미지/패키지 다운로드, 빌드, HTTP 응답 검사, artifact 왕복이 성공했다.

### 이번에 확인하지 않은 것

- 실제 GHES, GHES 전용 API/저장소/사설 CA, VPN/ExpressRoute 및 Secure Hub의 동작.
- Azure Firewall의 Application rule 프록시, TLS inspection, 제품별 idle timeout 및 SNAT 포트 용량.
- 이전 IP `/32`로 고정된 규칙의 실패·복구 실험.
- Runner를 목적지로 하는 별도 DNAT 또는 SSH/webhook 서비스.
- 빌드 도중 VM 종료/실시간 IP 변경, 중단된 빌드 재개, NAT 장비 장애.
- 대규모 동시 실행, 장시간 soak test, 성능·가용성 수치.
- GHES용 cache 및 artifact action 버전 호환성.

실제 Secure Hub에서는 다음을 확인해야 한다.

1. 원본 주소 허용/NAT 범위가 이전 IP 한 개인지, 새 IP도 포함하는지.
2. IP 변경 후 UDR·서브넷·NSG·반환 경로가 유지되는지.
3. 별도 Runner 대상 DNAT가 있다면 어떤 서비스가 사용하는지.
4. GHES 및 빌드가 사용하는 저장소·레지스트리·패키지 경로가 허용되는지.

**Runner IP를 목적지로 고정한 DNAT가 실제로 있는 경우 그 인바운드 서비스는 별도 영향 평가 대상이다. 이번 일반 Actions 작업 수신 경로에는 그런 DNAT가 필요하지 않았고 구성하지 않았다.**

## 9. 종료 상태, 보안 및 비용

- 테스트용 브랜치만 push했다. 기본 브랜치 및 기존 작업 디렉터리의 사용자 변경은 수정하지 않았다.
- Runner VM에는 Azure 역할/관리 ID나 Azure 자격 증명을 부여하지 않았다.
- 공개 저장소이므로 전용 branch/label 및 읽기 전용 `GITHUB_TOKEN`을 사용하고 PR 이벤트를 트리거하지 않았다.
- 이 VM은 신뢰한 workflow용이다. 이 구성만으로 같은 저장소의 모든 악성 workflow 할당을 차단하는 보안 경계가 되는 것은 아니다. 불특정 PR에 재사용하지 않는다.
- 캡처는 `tcpdump`의 주소·포트·TCP 헤더 텍스트만 저장했다. payload dump/PCAP, 인증 토큰, Runner 자격 증명은 게시하지 않았다.
- 최종적으로 `vm-runner`, `vm-nat` 모두 **VM deallocated**를 확인했다. Runner ID `21`은 재사용을 위해 등록을 유지하며 Offline이다.
- 종료 증적: [VM 상태](evidence/final-vm-states.json), [Runner 상태](evidence/final-runner-state.json).
- VM compute 비용은 할당 해제로 중지되지만 **OS 디스크 두 개와 고정 Public IP 등 보존 리소스의 비용은 계속 발생할 수 있다.** 리소스 그룹은 삭제하지 않았다.

완전히 폐기할 때만 다음 명령을 사용한다. 재실험하려면 삭제하지 않는다.

```powershell
gh api -X DELETE repos/hellices/devguidesample/actions/runners/21
az group delete --subscription $subscription --name $rg --yes
```

## 10. 참고 문서

- [GitHub self-hosted runner 통신 요구사항](https://docs.github.com/en/enterprise-server@3.18/actions/reference/runners/self-hosted-runners#communication)
- [Runner 서비스 자동 시작](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application)
- [Azure 사설 IP 할당 및 유지 조건](https://learn.microsoft.com/en-us/azure/virtual-network/ip-services/private-ip-addresses)
- [Azure Firewall 사설 주소 SNAT 기본 동작](https://learn.microsoft.com/en-us/azure/firewall/snat-private-range)
- [Azure Managed Run Command 보호 파라미터](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/run-command-managed)
