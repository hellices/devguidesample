# Foundry Local (On-device SDK/CLI): 제약 사항과 에어갭(Air-gapped) 구성 가이드

> 본 문서는 **Microsoft Foundry Local — 온디바이스 SDK/CLI** (`foundry-local-sdk`) 를 기준으로 한다.
>
> **이름이 비슷하지만 다른 제품들과의 구분**
>
> - **Azure Local Disconnected Operations** ([공식 문서](https://learn.microsoft.com/azure/azure-local/manage/disconnected-operations-overview)): 온프렘 서버 클러스터를 Azure 퍼블릭 연결 없이 운영하는 sovereign 인프라 제품 (GA). 공식 [supported services](https://learn.microsoft.com/azure/azure-local/manage/disconnected-operations-overview#supported-services) 는 Azure portal · ARM · RBAC · Managed identity · Arc-enabled servers · Azure Local VMs · AKS-on-Arc(Preview) · ACR · Key Vault · Policy 까지이며, **Azure AI Foundry / Foundry Models / Azure OpenAI 는 현재(2026-04 기준) 공식 지원 목록에 없다.**
> - 따라서 *"Azure Local Disconnected 위에서 AI Foundry 가 통합 제공된다"* 는 통합 제품은 현재 **공식 문서화돼 있지 않다.** 에어갭 멀티유저 추론이 필요하면 (a) 본 문서의 Foundry Local SDK 단일 사용자 구성, (b) Azure Local Disconnected + AKS(Preview) 위에 vLLM/Triton/KAITO 컨테이너 자체 호스팅, 또는 (c) 일반 온프렘 K8s + 동일 OSS 스택을 직접 검토해야 한다.

## **문제 상황**

Foundry Local 은 온디바이스에서 **채팅(텍스트 생성)과 오디오 전사(Whisper)** 등을 로컬로 실행하기 위한 경량 런타임/SDK 이다.  
도입 전 두 가지 근본 특성을 이해해야 한다.

1. **단일 사용자 최적화 설계**. Microsoft 공식 FAQ 는 *"optimized for hardware-constrained devices where a single user accesses the model at a time"* 이라고 명시하며, 멀티 사용자 서빙이 필요하면 **vLLM / Triton** 사용을 권장한다.
2. **모델 카탈로그 · Execution Provider · 모델 파일 다운로드는 기본적으로 네트워크를 사용**한다. 네트워크가 차단된 환경에서 `download()` 를 호출하면 실패하므로, **사전 캐싱 → 오프라인 캐시 전달** 방식이 필요하다.

> 출처: https://learn.microsoft.com/azure/foundry-local/what-is-foundry-local

***

## **해결 방향**

- **멀티 사용자 서빙**이 필요하면 Foundry Local 대신 **vLLM / Triton / KAITO / Azure Foundry Managed Compute** 같은 서버용 런타임을 선택한다.
- **단일 사용자 오프라인 앱**이거나 **폐쇄망에서 테스트/데모가 필요한 경우**, 인터넷 접근이 가능한 Staging VM 에서 모델을 사전 다운로드해 공유 스토리지에 올려두고, 에어갭 VM 은 해당 스토리지에서만 모델을 로드하도록 구성한다.

***

## **Part 1. 제약 사항**

### 1. 동시 사용자 수용 한계

| 사용자 수 | 가능 여부 | 설명 |
|---|---|---|
| **1명** (개발자 본인 / 엔드유저 본인 기기) | ✅ 설계 목적 | 앱에 임베드된 SDK 가 in-process 호출 |
| **2~5명** (같은 팀 소수, 저부하) | ⚠️ 기술적으로는 가능하나 비권장 | Optional REST 서버로 열어 멀티스레드 동시 호출은 되지만, 공식 문서상 서버 추론 스택으로 설계되지 않아 동시 요청이 몰리면 throughput 이 빠르게 저하된다 |
| **수십~수백명** 동시 | ❌ 설계상 불가 | MS 문서가 **명시적으로 vLLM / Triton 사용 권장** |

***

### 2. 서버 런타임과의 설계 철학 차이

Foundry Local 은 **온디바이스 경량 런타임** 이고, vLLM · Triton 은 **멀티 테넌트 서버 스택** 이다. 공식 FAQ 는 *"Server-oriented runtimes like vLLM or Triton Inference Server are built for multi-user scenarios — they handle concurrent request queuing, continuous batching, and efficient GPU sharing across many simultaneous clients. Foundry Local doesn't provide these capabilities."* 라고 명시한다.

따라서 아래 기능이 **필요한 시나리오** 는 Foundry Local 이 아닌 서버 런타임을 선택한다.

1. **요청 큐잉 · 연속 배칭(continuous batching)** — GPU 에서 서로 다른 사용자 요청을 인터리빙해 throughput 을 최적화
2. **QoS · 우선순위 · 타임아웃 정책**
3. **효율적 GPU 공유** (NVIDIA MIG · MPS 등 다중 테넌시)
4. **다중 노드 · LB · 페일오버 · 오토스케일**
5. **PagedAttention 같은 메모리 최적화 기반 세션 공유**

> 위 기능들은 Foundry Local 공식 아키텍처 문서에 언급이 없다. "개별 기능을 금지한다" 는 단정이 아니라 **공식 스펙상 서버 런타임 기능이 제시되지 않는다** 는 의미로 이해한다.

***

### 3. 기능 비교 (요구사항 기반)

> 기준: Foundry Local v1.0.0 GA (2026-04-10), 공식 MS Learn 문서.

| 항목 | Foundry Local | 해당 기능이 필요하면 |
|---|---|---|
| **동시성** | 스레드 안전 in-process 세션 기반 호출. 요청 큐잉 · 연속 배칭 · QoS 는 공식 문서에 언급 없음 | vLLM / Triton (FAQ 에서 직접 권장) |
| **스케일링** | 단일 디바이스 설계 (*"single user accesses the model at a time"*) | Kubernetes + KAITO / Azure Foundry Managed Compute |
| **GPU 공유** | 공식 문서에 MIG / MPS / GPU 파티셔닝 관련 언급 없음 | Triton + NVIDIA MIG / MPS |
| **상태 관리** | 로컬 프로세스 메모리 + 자동 KV-cache 관리. 분산 세션 스토어 언급 없음 | Redis / vLLM PagedAttention |
| **로드밸런싱** | 로컬 엔드포인트 단일 접근 | Nginx · Envoy · Istio + 다중 노드 |
| **관측성** | 로그 · CLI · 상태 엔드포인트 · zip-logs 제공. Prometheus / OTel 메트릭 엔드포인트는 공식 문서에 명시 없음 | Triton metrics + Prometheus / Grafana |
| **모델 범위** | 큐레이션 카탈로그: Phi, Qwen, DeepSeek, Mistral, GPT OSS (open-weight), Whisper (오디오 전사) 중심 | 프로프라이어터리 모델(Claude, GPT-5.x 등)은 Azure OpenAI / Foundry Models API |
| **OCR / 문서 이해** | Foundry Local 카탈로그는 chat completions 와 audio transcription 범위. OCR / 문서 추출은 범위 외 | **온프렘**: Azure Vision Read Docker (Distroless) · **클라우드**: Document Intelligence API |
| **서빙 아키텍처 제어** | 단일 노드 in-process 실행 중심 | KServe / Triton / vLLM |

- 근거: https://learn.microsoft.com/azure/foundry-local/what-is-foundry-local
- 근거: https://learn.microsoft.com/azure/foundry-local/concepts/foundry-local-architecture

***

### 4. 플랫폼 지원

공식 문서 · 블로그 · SDK 패키지 설명에 따르면 Foundry Local 은 **Windows, macOS (Apple Silicon), Linux** 를 지원하며, 최신 GA 발표와 SDK 문구에는 **모바일 / 폰 폼팩터(예: Android)** 까지 포함하는 언급이 있다. 단, 실제 패키지 배포와 버전별 가용성은 플랫폼마다 다를 수 있으므로 본인 환경에 맞는 최신 공식 패키지 / 릴리스 노트를 확인한다.

- 출처: https://learn.microsoft.com/azure/foundry-local/what-is-foundry-local
- SDK 레퍼런스: https://learn.microsoft.com/azure/foundry-local/reference/reference-sdk-current

***

### 5. 적합 / 비적합 시나리오

| | Foundry Local 적합 | 비적합 (대안 런타임 필요) |
|---|---|---|
| 용도 | 개인 디바이스 오프라인 AI, 엔드유저 기기에 임베드된 앱 (1 user = 1 process = 1 device) | 사내 공용 챗봇, 프로덕션 API, SLA · 관측성 필요 시스템, GPU 공유 다중 팀 |
| 비 LLM AI 기능 | 오디오 전사 (Whisper) 포함 | OCR · Document Intelligence → Azure Vision / Document Intelligence |
| 모델 요구사항 | Phi · Qwen · Mistral · DeepSeek · GPT OSS 등 오픈 모델 | 프로프라이어터리 (GPT / Claude 등) → Azure OpenAI · Foundry Models API |
| 대안 | — | vLLM / Triton / KAITO / Azure Foundry Managed Compute |

***

## **Part 2. 에어갭 환경 구성**

> 아래는 **본 프로젝트 실측 기반** 구성이다. Linux GPU EP 동작, `FOUNDRY_CACHE_DIR` 처리, 특정 파일 글롭 등은 **환경 의존 이슈** 이며 공식 "일반 제약" 이 아니라 실측 관찰임을 전제로 한다.

### 1. 전체 구성

```
[Staging VM] ──(internet allowed)──▶ Foundry Local catalog / model CDN
     │
     │ pre-download
     ▼
[Azure Files NFS 4.1 share]  ◀── Private Endpoint (privatelink.file.core.windows.net)
     ▲
     │ mount (Private IP only)
     │
[Airgap VM]  (egress: DENY * except VNet & storage PE)
     └─ foundry-local-sdk → model.load()  (외부 통신 0)
```

핵심 원칙

- 모델 저장소는 Azure Files **Premium NFS 4.1 + Private Endpoint**. 퍼블릭 엔드포인트 차단.
- Staging VM 은 **인터넷 허용**, Airgap VM 은 **egress deny-all**.
- 두 VM 모두 같은 share 를 `/mnt/foundry-cache` 로 마운트. 모델은 NFS 상에서 단일 원본을 공유한다.
- Foundry SDK 는 `Configuration(model_cache_dir, app_data_dir)` 로 NFS 경로를 지정해야 한다 (실측상 `FOUNDRY_CACHE_DIR` 환경변수만으로는 재지정되지 않는 경우 관찰됨).

***

### 2. 검증된 리소스 (koreacentral, 2026-04)

| 리소스 | 값 |
|---|---|
| VNet | `10.0.0.0/16` (subnet-staging `/24`, subnet-airgap `/24`, subnet-pe `/24`) |
| Storage | Premium FileStorage, NFS 4.1, 100 GiB share |
| Private DNS | `privatelink.file.core.windows.net` → PE private IP |
| Staging VM | `Standard_D4as_v5` Spot, Ubuntu 24.04 |
| Airgap VM | `Standard_NC40ads_H100_v5` Spot (H100 NVL 94GB), private IP only |
| NVIDIA Driver | extension `NvidiaGpuDriverLinux` (driver 595.58.03 / CUDA 12.8) |
| Foundry SDK | `foundry-local-sdk==1.0.0` (Python) |

***

### 3. NSG (airgap)

```
inbound  : VNet only (22 from subnet-staging)
outbound : Allow → VirtualNetwork (10.0.0.0/16)   priority 100
           Allow → Storage tag / PE IP             priority 110
           Deny  → Internet                         priority 4096
```

> 실측 팁: `az network nsg rule create` 사용 시 포트 · 프로토콜을 **명시적으로** 전달하지 않으면 의도와 다른 기본값이 적용되는 케이스가 있었다. 전체 포트 허용 / 차단 규칙은 `--destination-port-ranges '*' --source-port-ranges '*'` 를 명시하는 것이 안전하다. (본인 CLI 버전과 공식 문서로 재확인 권장)

***

### 4. Staging VM (인터넷 허용): 모델 사전 다운로드

```python
from foundry_local_sdk import Configuration, FoundryLocalManager

cfg = Configuration(
    app_name="stage",
    model_cache_dir="/mnt/foundry-cache/models",
    app_data_dir="/mnt/foundry-cache/appdata",
)
FoundryLocalManager.initialize(cfg)
mgr = FoundryLocalManager.instance

for alias in ["qwen2.5-0.5b", "phi-3.5-mini", "phi-4-mini"]:
    mgr.catalog.get_model(alias).download()
```

***

### 5. Airgap VM (인터넷 차단): 추론

```python
cfg = Configuration(
    app_name="airgap",
    model_cache_dir="/mnt/foundry-cache/models",
    app_data_dir="/mnt/foundry-cache/appdata",
)
FoundryLocalManager.initialize(cfg)
mgr = FoundryLocalManager.instance

m = mgr.catalog.get_model("phi-4-mini")
m.load()
r = m.get_chat_client().complete_chat(
    [{"role": "user", "content": "Translate to Korean: 'Hello, world'"}]
)
print(r.choices[0].message.content)
m.unload()
```

***

### 6. 실측 결과 (에어갭 상태, egress 전면 차단)

| 모델 | 크기 | EP | Load | Infer | 검증 |
|---|---|---|---|---|---|
| qwen2.5-0.5b | 822 MB | CPU | 2.05 s | 0.09 s | "Paris" ✓ |
| phi-3.5-mini | 2590 MB | CPU | 96.13 s | 0.49 s | "Red, blue, yellow" ✓ |
| phi-4-mini | 4915 MB | CPU | 4.45 s | 0.40 s | "안녕하세요, 세계" ✓ |

- `phi-3.5-mini` 의 96 초 load 는 **NFS 콜드 read** 이며 두 번째 호출부터는 OS 캐시로 수초 이내.
- 외부 URL (`google.com`, `huggingface.co`, `pypi.org`, `download.pytorch.org`) 전부 timeout 확인.

***

## **환경 의존 실전 이슈 (Ubuntu 24.04 + H100, v1.0.0)**

> 공식 문서는 CPU · CUDA (GPU) · WebGPU · NPU 등 여러 EP 지원을 전제로 서술한다 (아키텍처 문서, SDK 패키지 설명). 아래는 특정 환경에서 관찰된 실측 이슈로, 공식 "일반 제약" 이 아니다.

1. **GPU EP 등록 누락 관찰**: `mgr.discover_eps()` 가 빈 리스트를 반환하고 카탈로그에 `*-generic-cpu` 변형만 노출되어 H100 이 있어도 CPU EP 로 실행됐다. 휠에는 `onnxruntime-gpu`, `onnxruntime-genai-cuda`, `libonnxruntime_providers_cuda.so` 가 포함돼 있었으나 자동 등록되지 않았다. 드라이버 · CUDA · SDK 조합 또는 GA 초기 Linux 패키지 이슈로 보이며, GPU 가속이 꼭 필요하면 **Windows 환경** 또는 **vLLM · Triton** 을 사용한다.
2. **`.so.dbg` 글롭 매칭 문제**: `foundry_local_sdk/detail/utils.py:92` 의 `glob(f"*{filename}*")` 가 debug symbols 파일 (`*.so.dbg`) 을 먼저 매칭. 설치 직후 제거로 우회했다.

   ```bash
   rm ~/venv/lib/python3.12/site-packages/foundry_local_core/bin/*.so.dbg
   ```
3. **캐시 경로 재지정**: `FOUNDRY_CACHE_DIR` 만으로는 NFS 경로가 적용되지 않는 현상이 관찰되어, `Configuration(model_cache_dir=..., app_data_dir=...)` 를 명시적으로 전달했다.

- 근거: https://learn.microsoft.com/azure/foundry-local/concepts/foundry-local-architecture
- 근거: https://learn.microsoft.com/azure/foundry-local/reference/reference-sdk-current

***

## **구성 요약**

| 구성 요소 | 위치 | 역할 |
|---|---|---|
| Staging VM | Azure VNet (subnet-staging) | 인터넷 경유 Foundry 카탈로그에서 모델 다운로드 |
| Azure Files NFS share | subnet-pe (Private Endpoint) | 모델 원본 저장소 (Private IP 만 접근) |
| Private DNS Zone | VNet link | `privatelink.file.core.windows.net` 을 PE IP 로 해석 |
| Airgap VM | Azure VNet (subnet-airgap, 공인 IP 없음) | NFS 에서 모델 로드, 외부 egress 전면 차단 상태에서 추론 |
| Foundry Local SDK | 양 VM 동일 | `Configuration(model_cache_dir=...)` 로 NFS 경로 지정 |
