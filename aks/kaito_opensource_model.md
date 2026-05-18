# AKS + KAITO로 오픈소스 LLM 서빙하기

KAITO(Kubernetes AI Toolchain Operator)를 사용해 AKS 위에 오픈소스 LLM을 배포하는 전체 과정을 정리한다.  
대표 모델 두 가지(**Phi-4-mini**, **Mistral-7B-Instruct**)를 예시로 한다.

---

## 📌 사전 요구사항

- Azure CLI **2.76.0** 이상 (`az --version`으로 확인)
- `kubectl` 설치
- Azure 구독에 **GPU VM 쿼터** 확보 (Standard_NC24ads_A100_v4 기준 vCPU 24 이상)
- `aks-preview` 확장 설치

---

## 1. 환경 변수 설정

```bash
export AZURE_SUBSCRIPTION_ID="<구독 ID>"
export AZURE_RESOURCE_GROUP="rg-kaito-demo"
export AZURE_LOCATION="koreacentral"      # GPU 쿼터가 있는 리전 사용
export CLUSTER_NAME="aks-kaito-demo"
```

---

## 2. az CLI 확장 & 프로바이더 등록

```bash
# aks-preview 확장 설치/업데이트
az extension add --name aks-preview --upgrade

# 구독 선택
az account set --subscription $AZURE_SUBSCRIPTION_ID

# 필요 프로바이더 등록 (최초 1회)
az provider register --namespace Microsoft.ContainerService
```

---

## 3. 리소스 그룹 생성

```bash
az group create \
  --name $AZURE_RESOURCE_GROUP \
  --location $AZURE_LOCATION
```

---

## 4. AKS 클러스터 생성 (AI Toolchain Operator 활성화)

```bash
az aks create \
  --location $AZURE_LOCATION \
  --resource-group $AZURE_RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --enable-ai-toolchain-operator \
  --enable-oidc-issuer \
  --generate-ssh-keys
```

> **`--enable-ai-toolchain-operator`** 플래그가 KAITO Add-on + GPU Provisioner를 함께 설치한다.  
> 기존 클러스터에 추가할 경우 `az aks update`에 같은 플래그를 사용한다.

---

## 5. 클러스터 연결 & 확인

```bash
az aks get-credentials \
  --resource-group $AZURE_RESOURCE_GROUP \
  --name $CLUSTER_NAME

kubectl get nodes
```

KAITO 관련 Pod가 정상 동작하는지 확인:

```bash
kubectl get pods -n kube-system | grep kaito
```

---

## 6. 모델 배포 — ① Phi-4-mini-instruct (Microsoft)

> **Phi-4-mini**: Microsoft의 SLM으로 가벼우면서 성능이 뛰어남. GPU 1장(NC24ads_A100_v4)으로 서빙 가능.

### Workspace YAML 작성

```yaml
# phi4-mini-workspace.yaml
apiVersion: kaito.sh/v1beta1
kind: Workspace
metadata:
  name: workspace-phi-4-mini
resource:
  instanceType: "Standard_NC24ads_A100_v4"
  labelSelector:
    matchLabels:
      apps: phi-4-mini
inference:
  preset:
    name: phi-4-mini-instruct
```

### 배포 & 상태 확인

```bash
kubectl apply -f phi4-mini-workspace.yaml

# 상태 추적 (STATE가 Ready가 될 때까지 대기, 약 10~20분)
kubectl get workspace workspace-phi-4-mini -w
```

출력 예시:
```
NAME                   INSTANCE                    RESOURCEREADY   INFERENCEREADY   WORKSPACESUCCEEDED   STATE   AGE
workspace-phi-4-mini   Standard_NC24ads_A100_v4    True            True             True                 Ready   18m
```

### 추론 테스트

```bash
# 서비스 IP 확인
export PHI4_IP=$(kubectl get svc workspace-phi-4-mini -o jsonpath='{.spec.clusterIPs[0]}')

# 모델 목록 확인
kubectl run -it --rm --restart=Never curl --image=curlimages/curl -- \
  curl -s http://$PHI4_IP/v1/models | jq

# Chat Completions 호출
kubectl run -it --rm --restart=Never curl --image=curlimages/curl -- \
  curl -X POST http://$PHI4_IP/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "phi-4-mini-instruct",
    "messages": [
      {"role": "user", "content": "Kubernetes가 뭔가요? 간단히 설명해주세요."}
    ],
    "max_tokens": 200,
    "temperature": 0.7
  }'
```

---

## 7. 모델 배포 — ② Mistral-7B-Instruct

> **Mistral-7B**: 유럽 Mistral AI의 대표 오픈소스 모델. 7B 파라미터로 빠르고 효율적. HuggingFace 인증 불필요.

### Workspace YAML 작성

```yaml
# mistral-7b-workspace.yaml
apiVersion: kaito.sh/v1beta1
kind: Workspace
metadata:
  name: workspace-mistral-7b-instruct
resource:
  instanceType: "Standard_NC24ads_A100_v4"
  labelSelector:
    matchLabels:
      apps: mistral-7b-instruct
inference:
  preset:
    name: "mistral-7b-instruct"
```

### 배포 & 상태 확인

```bash
kubectl apply -f mistral-7b-workspace.yaml

kubectl get workspace workspace-mistral-7b-instruct -w
```

### 추론 테스트

```bash
export MISTRAL_IP=$(kubectl get svc workspace-mistral-7b-instruct -o jsonpath='{.spec.clusterIPs[0]}')

kubectl run -it --rm --restart=Never curl --image=curlimages/curl -- \
  curl -X POST http://$MISTRAL_IP/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral-7b-instruct",
    "messages": [
      {"role": "user", "content": "Azure AKS에서 GPU 노드풀을 구성하는 방법을 알려줘."}
    ],
    "max_tokens": 300,
    "temperature": 0.7
  }'
```

---

## 8. 외부 접근 (선택)

기본적으로 KAITO 서비스는 **ClusterIP** 타입이므로 클러스터 내부에서만 접근 가능하다.  
외부에서 테스트하려면 `port-forward`를 사용한다:

```bash
# Phi-4-mini를 로컬 8080 포트로 포워딩
kubectl port-forward svc/workspace-phi-4-mini 8080:80

# 로컬에서 호출
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "phi-4-mini-instruct",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 50
  }'
```

---

## 9. 정리 (리소스 삭제)

```bash
# 1) Workspace 삭제 (모델 Pod 제거)
kubectl delete workspace workspace-phi-4-mini
kubectl delete workspace workspace-mistral-7b-instruct

# 2) GPU 노드풀 확인 & 삭제 (KAITO가 자동 생성한 노드풀)
az aks nodepool list \
  --resource-group $AZURE_RESOURCE_GROUP \
  --cluster-name $CLUSTER_NAME \
  -o table

# 노드풀 이름을 확인 후 삭제
az aks nodepool delete \
  --resource-group $AZURE_RESOURCE_GROUP \
  --cluster-name $CLUSTER_NAME \
  --name <GPU_NODEPOOL_NAME>

# 3) 리소스 그룹 전체 삭제 (모든 리소스 포함)
az group delete --name $AZURE_RESOURCE_GROUP --yes --no-wait
```

---

## 📋 KAITO 지원 모델 요약 (주요 Preset)

| 모델 | Preset Name | 최소 Instance Type | 비고 |
|------|------------|-------------------|------|
| **Phi-4-mini** | `phi-4-mini-instruct` | Standard_NC24ads_A100_v4 | Microsoft SLM, 가볍고 빠름 |
| **Phi-4** | `phi-4` | Standard_NC24ads_A100_v4 | 14B 파라미터 |
| **Mistral-7B** | `mistral-7b-instruct` | Standard_NC24ads_A100_v4 | Mistral AI 오픈소스 |
| **Llama-3.1-8B** | `llama-3.1-8b-instruct` | Standard_NC96ads_A100_v4 | Meta, HF 토큰 필요 |
| **Llama-3.3-70B** | `llama-3.3-70b-instruct` | Standard_NC96ads_A100_v4 | 대형 모델, 멀티노드 지원 |
| **DeepSeek-R1** | `deepseek-r1` | Standard_NC96ads_A100_v4 | 멀티노드 분산추론 지원 |
| **Falcon-7B** | `falcon-7b-instruct` | Standard_NC24ads_A100_v4 | TII 오픈소스 |
| **Gemma-3-4B** | `gemma-3-4b-instruct` | Standard_NC24ads_A100_v4 | Google 오픈소스 |
| **Qwen-2.5-Coder-7B** | `qwen-2.5-coder-7b-instruct` | Standard_NC24ads_A100_v4 | 코딩 특화 |

> v0.9.0부터 **모든 vLLM 지원 HuggingFace 모델**을 `inference.preset.name`에 모델 카드 ID(예: `Qwen/Qwen3-0.6B`)로 지정해 실행할 수 있다.

---

## ⚠️ 주의사항

1. **GPU 쿼터 확인**: 배포 전 `az vm list-usage --location <region>` 으로 NC-series 쿼터를 확인한다.
2. **비용**: A100 GPU VM은 시간당 비용이 높다. 테스트 후 반드시 리소스를 삭제한다.
3. **리전 선택**: `koreacentral`에 GPU 쿼터가 없으면 `eastus`, `westus3`, `southcentralus` 등을 사용한다.
4. **Llama 계열**: Meta 라이선스 동의 후 HuggingFace 토큰을 Secret으로 등록해야 한다.
   ```bash
   kubectl create secret generic hf-token --from-literal=HF_TOKEN=<your-token>
   ```
5. **프로비저닝 시간**: GPU 노드 생성에 최대 10분, 모델 로딩에 추가 10~20분 소요될 수 있다.

---

## 참고

- [KAITO GitHub](https://github.com/kaito-project/kaito)
- [AKS AI Toolchain Operator 공식 문서](https://learn.microsoft.com/en-us/azure/aks/ai-toolchain-operator)
- [KAITO Preset 모델 목록](https://kaito-project.github.io/kaito/docs/presets)
- [KAITO 커스텀 모델 배포](https://learn.microsoft.com/en-us/azure/aks/kaito-custom-inference-model)
