# ✅ AKS Spot H100 GPU + KAITO LLM 서빙 가이드

**AKS에서 Azure Spot H100 GPU 노드와 KAITO(AI Toolchain Operator)로 `phi-4-mini-instruct`를 서빙한 End-to-End 검증 사례**

***

## 📌 핵심 요약

- AKS에 KAITO 애드온을 활성화하고, Spot H100 노드풀을 추가하여 LLM 추론을 저비용으로 실행.
- Spot + GPU 노드의 Taint 때문에 KAITO가 생성한 StatefulSet 및 NVIDIA device plugin DaemonSet에 **toleration 누락** 이슈 발생.
- Device plugin 캐시 stale 이슈로 `endpoint not found in cache for nvidia.com/gpu` 오류 발생 → device plugin 재생성으로 해결.
- Spot VM은 **Spot Core 쿼터가 없어도 배포 가능** (정규 H100 쿼터와 무관).

***

## 🔍 아키텍처

| 구성 | 값 |
|---|---|
| Resource Group | `rg-aks-kaito-demo` |
| Region | `koreacentral` |
| AKS Cluster | `aks-kaito`, Kubernetes 1.34, AI Toolchain Operator 애드온 |
| System 노드풀 | `nodepool1`, `Standard_D4s_v5` × 2 |
| GPU 노드풀 (Spot) | `gpuspot`, `Standard_NC40ads_H100_v5` × 1 (H100 94GB, Spot, max-price -1), autoscaler 0-1 |
| GPU 노드 Taint | `sku=gpu:NoSchedule` + AKS 자동 `kubernetes.azure.com/scalesetpriority=spot:NoSchedule` |
| 모델 | `phi-4-mini-instruct` (KAITO preset, vLLM runtime) |
| Service | `workspace-phi-4-mini` ClusterIP:80 (OpenAI 호환 API) |

***

## ✅ 배포 절차

### 1. Preview feature 등록 및 Resource Group 생성

```bash
RG=rg-aks-kaito-demo
LOC=koreacentral
CLUSTER=aks-kaito

az feature register --namespace Microsoft.ContainerService --name AIToolchainOperatorPreview
az provider register -n Microsoft.ContainerService
az extension add --name aks-preview --upgrade

az group create -n $RG -l $LOC
```

### 2. AKS 클러스터 + KAITO 애드온 생성

```bash
az aks create -g $RG -n $CLUSTER -l $LOC \
  --node-count 2 --node-vm-size Standard_D4s_v5 \
  --enable-oidc-issuer --enable-workload-identity \
  --enable-ai-toolchain-operator \
  --generate-ssh-keys --tier free --network-plugin azure

az aks get-credentials -g $RG -n $CLUSTER --overwrite-existing
```

### 3. Spot H100 GPU 노드풀 추가

```bash
az aks nodepool add -g $RG --cluster-name $CLUSTER -n gpuspot \
  --node-vm-size Standard_NC40ads_H100_v5 \
  --priority Spot --eviction-policy Delete --spot-max-price -1 \
  --enable-cluster-autoscaler --min-count 0 --max-count 1 --node-count 1 \
  --node-taints "sku=gpu:NoSchedule" \
  --labels apps.kaito.sh/managed=true \
  --node-osdisk-size 128
```

### 4. KAITO Workspace 배포

```yaml
# workspace-phi4-mini.yaml
apiVersion: kaito.sh/v1beta1
kind: Workspace
metadata:
  name: workspace-phi-4-mini
resource:
  instanceType: Standard_NC40ads_H100_v5
  labelSelector:
    matchLabels:
      apps.kaito.sh/managed: "true"
inference:
  preset:
    name: phi-4-mini-instruct
```

```bash
kubectl apply -f workspace-phi4-mini.yaml
```

***

## 🐞 배포 중 마주친 이슈 및 해결

| # | 증상 | 원인 | 해결 |
|---|---|---|---|
| 1 | `az aks nodepool add` 실패: `label 'accelerator' is not allowed` | AKS 예약 레이블 | `--labels`에서 `accelerator=nvidia` 제거 |
| 2 | Pod `FailedScheduling` / `untolerated taint sku=gpu, scalesetpriority=spot` | KAITO가 생성한 StatefulSet에 toleration 누락 | StatefulSet에 `sku=gpu`, `scalesetpriority=spot` toleration 추가 |
| 3 | `0/3 nodes available: 1 Insufficient nvidia.com/gpu` | `kaito-nvidia-device-plugin-daemonset`이 Spot/GPU 노드에 toleration 없음 | DaemonSet에 `sku=gpu`, `scalesetpriority=spot`, `nvidia.com/gpu` toleration 추가 |
| 4 | 메인 컨테이너 `CreateContainerConfigError: endpoint not found in cache for nvidia.com/gpu` | kubelet device plugin 캐시 stale | GPU 노드의 device-plugin pod 재생성 + workspace pod 재생성 |

### Device Plugin DaemonSet 패치

```bash
kubectl patch ds -n kube-system kaito-nvidia-device-plugin-daemonset --type=json -p='[
  {"op":"add","path":"/spec/template/spec/tolerations/-","value":{"key":"sku","operator":"Equal","value":"gpu","effect":"NoSchedule"}},
  {"op":"add","path":"/spec/template/spec/tolerations/-","value":{"key":"kubernetes.azure.com/scalesetpriority","operator":"Equal","value":"spot","effect":"NoSchedule"}},
  {"op":"add","path":"/spec/template/spec/tolerations/-","value":{"key":"nvidia.com/gpu","operator":"Exists","effect":"NoSchedule"}}
]'
```

### Workspace StatefulSet 패치

```bash
kubectl patch statefulset workspace-phi-4-mini --type=json -p='[
  {"op":"add","path":"/spec/template/spec/tolerations/-","value":{"key":"sku","operator":"Equal","value":"gpu","effect":"NoSchedule"}},
  {"op":"add","path":"/spec/template/spec/tolerations/-","value":{"key":"kubernetes.azure.com/scalesetpriority","operator":"Equal","value":"spot","effect":"NoSchedule"}}
]'
```

***

## 🧪 검증

### 상태 확인

```bash
kubectl get workspace workspace-phi-4-mini
# INSTANCE=Standard_NC40ads_H100_v5  RESOURCEREADY=True  INFERENCEREADY=True  STATE=Ready

kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.'nvidia\.com/gpu'
# aks-gpuspot-... 1
```

### 포트 포워딩으로 호출

```bash
kubectl port-forward svc/workspace-phi-4-mini 8080:80
```

```bash
curl http://localhost:8080/v1/models

curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "phi-4-mini-instruct",
    "messages": [{"role":"user","content":"hello"}],
    "max_tokens": 128
  }'
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8080/v1", api_key="not-needed")
resp = client.chat.completions.create(
    model="phi-4-mini-instruct",
    messages=[{"role": "user", "content": "Write one sentence about Azure Spot VMs."}],
    max_tokens=80,
)
print(resp.choices[0].message.content)
```

### 클러스터 내부 curl pod

```bash
kubectl run curltest --rm -i --restart=Never --image=curlimages/curl:8.10.1 -- \
  curl -s http://workspace-phi-4-mini/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"phi-4-mini-instruct","messages":[{"role":"user","content":"hi"}],"max_tokens":60}'
```

### 검증 결과

- `/v1/models`: `phi-4-mini-instruct` (max_model_len=131072) 노출 확인.
- `/v1/chat/completions`
  - 요청: `"Write one short sentence about Azure Spot VMs."`
  - 응답: *"Azure Spot VMs offer a cost-effective solution by allowing you to take advantage of unused Azure capacity at a significant discount, suitable for workloads that can tolerate interruptions."*
  - `usage`: prompt=21, completion=33, total=54, `finish_reason=stop`.

### vLLM 주요 엔드포인트

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/completions`
- `POST /v1/embeddings`
- `GET /metrics` (Prometheus)
- `GET /ping` (헬스체크)

***

## 💡 운영 팁

- **Spot 축출**: 축출 시 KAITO가 pod를 재생성. `count: 1`은 SPOF이므로 프로덕션은 여러 Spot 노드 + `count > 1` 또는 Spot/Regular 혼합 권장.
- **이미지 크기**: `kaito-base` 이미지가 ~8GB이므로 최초 pull에 10분 이상 소요. ACR 캐시/이미지 warm-up 권장.
- **디스크**: OS 디스크 128GB 권장 (모델 가중치 + 컨테이너 이미지).
- **GPU 관찰**: `kubectl exec -it <pod> -- nvidia-smi`, vLLM `/metrics`.
- **모델 전환**: Workspace의 `inference.preset.name`만 변경해 재배포. Gated 모델(Llama, Gemma)은 `modelAccessSecret`으로 HF 토큰 제공 필요.
- **외부 노출**: `LoadBalancer`는 인증이 없으므로 데모 전용. 장기 사용 시 Ingress + OAuth2 Proxy/Entra ID 인증 필수.

***

## 🧹 리소스 정리

```bash
az group delete -n rg-aks-kaito-demo --yes --no-wait
```

***

## 📚 참고 링크

- [KAITO (AI Toolchain Operator) GitHub](https://github.com/kaito-project/kaito)
- [AKS AI Toolchain Operator 애드온](https://learn.microsoft.com/ko-kr/azure/aks/ai-toolchain-operator)
- [Azure Spot VM 개요](https://learn.microsoft.com/ko-kr/azure/virtual-machines/spot-vms)
- [NC H100 v5 시리즈](https://learn.microsoft.com/ko-kr/azure/virtual-machines/nc-h100-v5-series)
- [vLLM OpenAI 호환 서버](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)
# AKS Spot GPU + KAITO LLM Serving Demo

AKS에서 Azure Spot H100 GPU 노드를 사용하고, KAITO(AI Toolchain Operator)로 `phi-4-mini-instruct` LLM을 서빙한 End-to-End 검증 기록입니다.

## 아키텍처

| 구성 | 값 |
|---|---|
| Resource Group | `rg-aks-kaito-demo` |
| Region | `koreacentral` |
| AKS Cluster | `aks-kaito`, Kubernetes 1.34, AI Toolchain Operator 애드온 |
| System 노드풀 | `nodepool1`, `Standard_D4s_v5` × 2 |
| GPU 노드풀 (Spot) | `gpuspot`, `Standard_NC40ads_H100_v5` × 1 (H100 94GB, Spot, max-price -1), autoscaler 0-1 |
| GPU 노드 Taint | `sku=gpu:NoSchedule` + AKS 자동 `kubernetes.azure.com/scalesetpriority=spot:NoSchedule` |
| 모델 | `phi-4-mini-instruct` (KAITO preset, vLLM runtime) |
| Workspace CR | [workspace-phi4-mini.yaml](workspace-phi4-mini.yaml) |
| Service | `workspace-phi-4-mini` ClusterIP:80 (OpenAI 호환 API) |

> Spot VM은 Spot Core 쿼터가 설정되어 있지 않아도 배포 가능 (정규 H100 쿼터와 무관).

## 배포 요약 (재현 절차)

```bash
RG=rg-aks-kaito-demo
LOC=koreacentral
CLUSTER=aks-kaito

# 0) AITO preview feature 등록
az feature register --namespace Microsoft.ContainerService --name AIToolchainOperatorPreview
az provider register -n Microsoft.ContainerService
az extension add --name aks-preview --upgrade

# 1) Resource Group
az group create -n $RG -l $LOC

# 2) AKS + KAITO 애드온
az aks create -g $RG -n $CLUSTER -l $LOC \
  --node-count 2 --node-vm-size Standard_D4s_v5 \
  --enable-oidc-issuer --enable-workload-identity \
  --enable-ai-toolchain-operator \
  --generate-ssh-keys --tier free --network-plugin azure

az aks get-credentials -g $RG -n $CLUSTER --overwrite-existing

# 3) Spot H100 노드풀
az aks nodepool add -g $RG --cluster-name $CLUSTER -n gpuspot \
  --node-vm-size Standard_NC40ads_H100_v5 \
  --priority Spot --eviction-policy Delete --spot-max-price -1 \
  --enable-cluster-autoscaler --min-count 0 --max-count 1 --node-count 1 \
  --node-taints "sku=gpu:NoSchedule" \
  --labels apps.kaito.sh/managed=true \
  --node-osdisk-size 128

# 4) KAITO Workspace 배포
kubectl apply -f kaito/workspace-phi4-mini.yaml
```

## 배포 중 마주친 이슈 및 해결

| # | 증상 | 원인 | 해결 |
|---|---|---|---|
| 1 | `az aks nodepool add` 실패: `label 'accelerator' is not allowed` | AKS 예약 레이블 | `--labels`에서 `accelerator=nvidia` 제거 |
| 2 | Pod `FailedScheduling` / `untolerated taint sku=gpu, scalesetpriority=spot` | KAITO가 생성한 StatefulSet에 toleration 누락 | StatefulSet에 `sku=gpu`, `scalesetpriority=spot` toleration 추가 |
| 3 | `0/3 nodes available: 1 Insufficient nvidia.com/gpu` | `kaito-nvidia-device-plugin-daemonset`이 Spot/GPU 노드에 toleration 없음 | DS에 `sku=gpu`, `scalesetpriority=spot`, `nvidia.com/gpu` toleration 추가 |
| 4 | 메인 컨테이너 `CreateContainerConfigError: endpoint not found in cache for nvidia.com/gpu` | kubelet device plugin 캐시 stale | GPU 노드의 device-plugin pod 재생성 + workspace pod 재생성 |

### 적용한 DS 패치

```bash
kubectl patch ds -n kube-system kaito-nvidia-device-plugin-daemonset --type=json -p='[
  {"op":"add","path":"/spec/template/spec/tolerations/-","value":{"key":"sku","operator":"Equal","value":"gpu","effect":"NoSchedule"}},
  {"op":"add","path":"/spec/template/spec/tolerations/-","value":{"key":"kubernetes.azure.com/scalesetpriority","operator":"Equal","value":"spot","effect":"NoSchedule"}},
  {"op":"add","path":"/spec/template/spec/tolerations/-","value":{"key":"nvidia.com/gpu","operator":"Exists","effect":"NoSchedule"}}
]'
```

### 적용한 StatefulSet 패치

```bash
kubectl patch statefulset workspace-phi-4-mini --type=json -p='[
  {"op":"add","path":"/spec/template/spec/tolerations/-","value":{"key":"sku","operator":"Equal","value":"gpu","effect":"NoSchedule"}},
  {"op":"add","path":"/spec/template/spec/tolerations/-","value":{"key":"kubernetes.azure.com/scalesetpriority","operator":"Equal","value":"spot","effect":"NoSchedule"}}
]'
```

## 검증 (테스트 방법)

### 상태 확인

```bash
kubectl get workspace workspace-phi-4-mini
# INSTANCE=Standard_NC40ads_H100_v5  RESOURCEREADY=True  INFERENCEREADY=True  STATE=Ready

kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.'nvidia\.com/gpu'
# aks-gpuspot-... 1
```

### 방법 1: 포트 포워딩 (권장)

```bash
kubectl port-forward svc/workspace-phi-4-mini 8080:80
```

```bash
# 모델 목록
curl http://localhost:8080/v1/models

# Chat Completions (OpenAI 호환)
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "phi-4-mini-instruct",
    "messages": [{"role":"user","content":"hello"}],
    "max_tokens": 128
  }'
```

Python SDK 예:

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8080/v1", api_key="not-needed")
resp = client.chat.completions.create(
    model="phi-4-mini-instruct",
    messages=[{"role": "user", "content": "Write one sentence about Azure Spot VMs."}],
    max_tokens=80,
)
print(resp.choices[0].message.content)
```

### 방법 2: 클러스터 내부 curl pod

```bash
kubectl run curltest --rm -i --restart=Never --image=curlimages/curl:8.10.1 -- \
  curl -s http://workspace-phi-4-mini/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"phi-4-mini-instruct","messages":[{"role":"user","content":"hi"}],"max_tokens":60}'
```

### 방법 3: LoadBalancer로 외부 노출 (데모 전용)

```bash
kubectl patch svc workspace-phi-4-mini -p '{"spec":{"type":"LoadBalancer"}}'
kubectl get svc workspace-phi-4-mini -w   # EXTERNAL-IP 확인

# 원복
kubectl patch svc workspace-phi-4-mini -p '{"spec":{"type":"ClusterIP"}}'
```

> LoadBalancer는 인증이 없으므로 Ingress + 인증(OAuth2 Proxy, Entra ID 등) 구성 후 장기 사용 권장.

## 검증 결과

### `/v1/models`
```json
{
  "object": "list",
  "data": [{
    "id": "phi-4-mini-instruct",
    "object": "model",
    "owned_by": "vllm",
    "max_model_len": 131072,
    ...
  }]
}
```

### `/v1/chat/completions`
- 요청: `"Write one short sentence about Azure Spot VMs."`
- 응답:
  > "Azure Spot VMs offer a cost-effective solution by allowing you to take advantage of unused Azure capacity at a significant discount, suitable for workloads that can tolerate interruptions."
- `usage`: prompt=21, completion=33, total=54
- `finish_reason`: `stop`

### vLLM이 노출하는 주요 엔드포인트
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/completions`
- `POST /v1/embeddings`
- `GET /metrics` (Prometheus)
- `GET /ping` (헬스체크)

## 운영 팁

- **Spot 축출**: 노드 축출 시 KAITO Workspace가 pod를 재생성. `count: 1`은 SPOF이므로 프로덕션은 여러 Spot 노드 + `count > 1` 또는 Spot+Regular 혼합 권장.
- **이미지 크기**: `kaito-base:0.2.5`가 ~8GB라 최초 pull에 10분 이상. 이미지 미리 warm-up 하거나 ACR 캐시 활용.
- **디스크**: OS 디스크 128GB 권장(모델 가중치 + 컨테이너 이미지).
- **GPU 관찰**: `kubectl exec -it <pod> -- nvidia-smi`, `/metrics` (vLLM).
- **모델 전환**: Workspace의 `inference.preset.name`만 변경해서 재배포 가능. Gated 모델(Llama, Gemma)은 `modelAccessSecret`로 HF 토큰 제공 필요.

## 리소스 정리

```bash
az group delete -n rg-aks-kaito-demo --yes --no-wait
```
