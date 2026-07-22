# AKS 원격 클러스터 + 로컬 개발 루프 (Telepresence / mirrord)

AKS에 배포된 서비스를 대상으로, **코드를 이미지로 빌드/배포하지 않고**
로컬 프로세스가 클러스터의 일부인 것처럼 개발·디버깅하는 방법.

두 도구를 같은 시나리오(AKS의 `echo-server` 트래픽을 로컬 Python 서버로 가로채기)로 실측 검증했다.

- **Telepresence** (OSS 2.30.1) — 머신 전체를 클러스터 네트워크에 연결
- **mirrord** (3.236.1) — 프로세스 단위 주입, VS Code 확장(UI) 제공

공식 자료 (AKS 관점):
- [Use Telepresence to develop and test microservices locally — MS Learn](https://learn.microsoft.com/en-us/azure/aks/use-telepresence-aks)
- [Local Development on AKS with mirrord — AKS Engineering Blog](https://blog.aks.azure.com/2024/12/04/mirrord-on-aks)

예제 파일: [`local_dev_loop/`](./local_dev_loop/)

```
local_dev_loop/
├── k8s/echo-service.yaml   # tp-demo 네임스페이스 + echo-server Deployment/Service
└── local/
    ├── local-server.py     # 트래픽을 가로챌 로컬 개발 서버 (:8080)
    └── mirrord.json        # mirrord 설정 (target, steal 모드, env/fs/dns)
```

---

## 📌 사전 요구사항

- Azure CLI, `kubectl`, AKS 클러스터 (예시: `aks-customvec-krc` @ `rg-aiplay-krc-01`)
- Telepresence: `brew install telepresenceio/telepresence/telepresence-oss`
- mirrord: `brew install metalbear-co/mirrord/mirrord`
- (UI 사용 시) VS Code + `code --install-extension MetalBear.mirrord`

---

## 1. 대상 서비스 배포

```bash
az aks get-credentials -g rg-aiplay-krc-01 -n aks-customvec-krc
kubectl apply -f local_dev_loop/k8s/echo-service.yaml
kubectl -n tp-demo rollout status deploy/echo-server
```

`echo-server`는 요청 헤더/환경변수를 JSON으로 되돌려주는 서비스라
응답이 **클러스터 Pod에서 왔는지 로컬에서 왔는지** 바로 구분된다.

---

## 2. Telepresence — 머신 전체 연결

> Telepresence는 CNCF Sandbox 프로젝트로, **Microsoft가 공식 지원하지 않는다.**
> 문제 발생 시 [Telepresence GitHub issues](https://github.com/telepresenceio/telepresence/issues)로.
> AKS 기준 튜토리얼: [MS Learn — Use Telepresence with AKS](https://learn.microsoft.com/en-us/azure/aks/use-telepresence-aks)

### 2-1. 아키텍처

```
[로컬 앱] → 클러스터 DNS/ClusterIP 그대로 호출
   ↓ (rootd가 만든 TUN 디바이스 + 라우팅 + DNS)
[userd] ⇄ gRPC 터널 ⇄ [Traffic Manager (클러스터)] → [Pod]
```

- **루트 데몬(rootd)**: TUN 생성, Pod/Service CIDR 라우팅, 클러스터 DNS 리졸버 → **root 권한 필요**
- **유저 데몬(userd)**: Traffic Manager와 gRPC 세션, intercept 관리 → 일반 권한
- 클러스터 측에는 **Traffic Manager**(helm)가 상주하고, intercept 시 대상 Pod에 사이드카가 주입됨

### 2-2. 사용 순서

```bash
# Traffic Manager 설치 (클러스터 측, 최초 1회)
telepresence helm install

# 연결 (macOS: 루트 데몬 때문에 sudo 비밀번호 프롬프트가 뜸)
telepresence connect

# outbound: 로컬에서 클러스터 내부 DNS로 바로 호출
curl http://echo-server.tp-demo            # 클러스터 Pod가 응답

# intercept 가능한 서비스 목록 확인
telepresence list

# inbound intercept: 클러스터 트래픽을 로컬로
python3 local_dev_loop/local/local-server.py &
telepresence intercept echo-server --namespace tp-demo --port 8080:80

# --env-file을 주면 원격 Pod의 환경변수를 파일로 받아 로컬 앱에서 재사용 가능
telepresence intercept echo-server --namespace tp-demo --port 8080:80 --env-file .env

# 검증: 클러스터 안에서 호출해도 로컬 서버가 응답
kubectl -n tp-demo run t --rm -i --restart=Never \
  --image=curlimages/curl:8.10.1 -- -s http://echo-server.tp-demo
```

### 2-3. 비대화형 환경에서 루트 데몬 직접 기동

sudo 프롬프트를 띄울 수 없는 환경(CI, 에이전트 셸 등)에서는 루트 데몬을 직접 실행한다.
2.30부터 서브커맨드가 `daemon-foreground` → `rootd`로 변경됐다.

```bash
PORT=<빈 포트>
printf '{"daemon_port":%d}' "$PORT" > ~/Library/Caches/telepresence/rootd/daemon.json
sudo telepresence rootd \
  --cache ~/Library/Caches/telepresence \
  --config "$HOME/Library/Application Support/telepresence/config.yml" \
  --logfile ~/Library/Logs/telepresence/daemon.log \
  --address ":$PORT" &
telepresence connect
```

> Docker가 있다면 `telepresence connect --docker`로 sudo 없이 사용 가능 (데몬이 컨테이너 안에서 동작).

---

## 3. mirrord — 프로세스 단위 주입

> AKS 공식 블로그 워크스루(Rust/Go 예제 포함):
> [Local Development on AKS with mirrord — AKS Engineering Blog](https://blog.aks.azure.com/2024/12/04/mirrord-on-aks)

### 3-1. 아키텍처

mirrord는 클러스터 상주 컴포넌트가 **없다**. 세션마다 임시 **agent pod**를 띄우고,
로컬 프로세스에 라이브러리(`DYLD_INSERT_LIBRARIES`/`LD_PRELOAD`)를 주입해
syscall 수준에서 네트워크/환경변수/파일을 원격 Pod의 것으로 바꿔치기한다.
**루트 데몬·sudo 불필요.**

### 3-2. 설정 파일

```jsonc
// local_dev_loop/local/mirrord.json
{
  "target": { "path": "deployment/echo-server", "namespace": "tp-demo" },
  "feature": {
    "network": {
      "incoming": { "mode": "steal", "port_mapping": [[8080, 80]] },
      "outgoing": true,
      "dns": true
    },
    "env": true,   // 원격 Pod의 환경변수를 로컬 프로세스에 주입
    "fs": "read"   // 원격 파일시스템 읽기를 syscall 후킹으로 제공
  }
}
```

**incoming 모드 선택**
- `"mirror"` (기본값): 트래픽 **복사본**만 로컬로 받음. 원격 Pod가 실제 응답하고
  로컬 응답은 폐기됨 → 클러스터에 영향 없는 관찰/로그 확인용
- `"steal"`: 트래픽을 로컬로 **가로채서** 로컬 응답이 클러스터로 나감 → 실제 개발용
- steal 시 [HTTP 필터](https://metalbear.com/mirrord/docs/using-mirrord/steal/)로
  특정 헤더/경로가 매칭되는 요청만 부분적으로 가로챌 수도 있다

### 3-3. CLI 사용

```bash
# 인바운드 steal + env/dns/fs 미러링
mirrord exec -f local_dev_loop/local/mirrord.json -- \
  python3 local_dev_loop/local/local-server.py

# 로컬 프로세스가 원격 Pod의 환경변수를 그대로 받음
mirrord exec -f local_dev_loop/local/mirrord.json -- \
  python3 -c "import os; print(os.environ['POD_NAME'])"

# 아웃바운드: 클러스터 내부 DNS도 프로세스 안에서 해석됨
mirrord exec -f local_dev_loop/local/mirrord.json -- \
  curl http://echo-server.tp-demo.svc.cluster.local
```

> ⚠️ OSS 버전은 같은 Pod에 **동시 세션 불가** — "dirty iptables" 에러가 나면
> 이전 세션이 비정상 종료된 것. `kubectl -n tp-demo delete pod --all`로 Pod를 재생성하면 해결.

### 3-4. VS Code 확장 (UI)

F5(Run/Debug)만으로 mirrord가 적용된다. **브레이크포인트를 찍으면 클러스터
트래픽으로 로컬 디버깅**이 가능 — UI 사용의 최대 장점.

상태바 토글이 저장되지 않는 경우가 있어, launch.json의 env로 강제하는 방식이 확실하다:

```jsonc
// .vscode/launch.json
{
  "name": "mirrord demo: local-server (echo-server steal)",
  "type": "debugpy",
  "request": "launch",
  "program": "${workspaceFolder}/aks/local_dev_loop/local/local-server.py",
  "console": "integratedTerminal",
  "env": {
    "MIRRORD_ACTIVE": "1",
    "MIRRORD_CONFIG_FILE": "${workspaceFolder}/.mirrord/mirrord.json"
  }
}
```

```jsonc
// .vscode/settings.json — GUI 앱은 셸 PATH를 모르므로 바이너리 경로 지정
{
  "mirrord.binaryPath": "/opt/homebrew/bin/mirrord",
  "mirrord.enabledByDefault": true
}
```

- 확장은 워크스페이스 루트의 `.mirrord/mirrord.json`을 자동 인식한다
- agent pod는 **디버그 세션이 살아있는 동안에만** 존재한다
  (`kubectl get pods -n default | grep mirrord-agent`)
- 코드 수정 후 재시작(`Cmd+Shift+F5`)만 하면 반영 — 이미지 빌드/배포 불필요

---

## 4. Telepresence vs mirrord 비교 (실측)

| 항목 | Telepresence OSS | mirrord OSS |
|---|---|---|
| 동작 범위 | 머신 전체 (TUN + 라우팅 + DNS) | `mirrord exec`로 띄운 프로세스만 |
| 루트 권한 | 필요 (루트 데몬) | 불필요 |
| 클러스터 상주물 | Traffic Manager(helm) + Pod 사이드카 | 없음 (세션마다 임시 agent pod) |
| 인바운드 | intercept (steal) | mirror(복사본, 기본) / steal / HTTP 필터 부분 steal |
| env 미러링 | intercept `--env-file`로 파일 제공 | 자동 (`"env": true`) |
| 파일 미러링 | sshfs 볼륨 마운트 (fuse-t 필요) | syscall 후킹 (`"fs": "read"`) |
| 동시 세션 | 가능 (사용자별 intercept) | 같은 타깃 steal은 유료(Operator)만, 서로 다른 타깃/mirror는 가능 |
| IDE UI | 없음 (CLI만) | **VS Code 확장 + IntelliJ 플러그인** |

**선택 기준**
- 팀에서 여러 명이 같은 서비스를 개발 → **Telepresence** (또는 mirrord for Teams)
- 개인이 sudo 없이 가볍게, IDE에서 클릭 한 번으로 → **mirrord**

---

## 5. 정리

```bash
# Telepresence
telepresence leave echo-server           # intercept 해제 (신버전: detach)
telepresence quit -s                     # 데몬 종료
telepresence helm uninstall              # Traffic Manager 제거

# mirrord — agent pod는 세션 종료 시 자동 삭제됨

# 샘플 서비스 제거
kubectl delete -f local_dev_loop/k8s/echo-service.yaml

# 비용 절약: 클러스터 중지
az aks stop -g rg-aiplay-krc-01 -n aks-customvec-krc
```

> ⚠️ 예시 클러스터는 시작 시 `gpuspot` 노드풀(NC16as_T4_v3 spot ×3)에
> `vllm-embedding` 워크로드가 함께 올라온다. 테스트 후 클러스터를 중지하거나
> `az aks nodepool scale ... -n gpuspot -c 0`으로 GPU 노드만 내릴 것.

---

## 참고 자료

- [Use Telepresence to develop and test microservices locally — MS Learn](https://learn.microsoft.com/en-us/azure/aks/use-telepresence-aks)
  — AKS 공식 튜토리얼. [aks-store-demo](https://github.com/Azure-Samples/aks-store-demo) 마이크로서비스로 intercept 실습
- [Local Development on AKS with mirrord — AKS Engineering Blog](https://blog.aks.azure.com/2024/12/04/mirrord-on-aks)
  — mirrord VS Code 확장으로 Rust/Go 서비스 개발. steal한 프로세스가 원격 env로
  RabbitMQ/MongoDB에 그대로 접속하는 예제 포함
- [Telepresence docs](https://telepresence.io/docs/) / [mirrord docs](https://metalbear.com/mirrord/docs/)
