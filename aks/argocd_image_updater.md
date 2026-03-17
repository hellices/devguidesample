# ✅ ArgoCD Image Updater + ACR on AKS 설정 가이드

**AKS에서 ArgoCD Image Updater v2를 사용하여 Azure Container Registry(ACR)의 이미지 태그를 자동으로 감지하고 업데이트하는 전체 과정을 정리한 문서.**

***

## 📌 전제 조건

| 항목 | 요구사항 |
|---|---|
| AKS 클러스터 | OIDC Issuer + Workload Identity **활성화** 필수 |
| ACR | 접근 가능한 Azure Container Registry |
| ArgoCD Application | 소스 타입이 **Kustomize** 또는 **Helm** (Directory는 지원하지 않음) |

AKS 클러스터에 OIDC/Workload Identity가 활성화되어 있는지 확인:

```bash
az aks show \
  --name <AKS_NAME> \
  --resource-group <RG_NAME> \
  --query "{oidcIssuer:oidcIssuerProfile.enabled, workloadIdentity:securityProfile.workloadIdentity.enabled}" \
  -o json
```

둘 다 `true`여야 한다. 아니라면:

```bash
az aks update \
  --name <AKS_NAME> \
  --resource-group <RG_NAME> \
  --enable-oidc-issuer \
  --enable-workload-identity
```

***

## 📌 전체 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│  AKS Cluster                                            │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  argocd namespace                                │   │
│  │                                                  │   │
│  │  ┌─────────────────────────────────────────┐     │   │
│  │  │ Image Updater Pod                       │     │   │
│  │  │                                         │     │   │
│  │  │  1. Federated Token (자동 주입)          │     │   │
│  │  │  2. auth.sh 실행                        │     │   │
│  │  │     → AAD Token 교환                    │     │   │
│  │  │     → ACR Refresh Token 교환            │     │   │
│  │  │  3. ACR에서 태그 목록 조회              │     │   │
│  │  │  4. ArgoCD Application 업데이트          │     │   │
│  │  └────────────┬────────────────────────────┘     │   │
│  │               │                                  │   │
│  └───────────────┼──────────────────────────────────┘   │
│                  │                                      │
└──────────────────┼──────────────────────────────────────┘
                   │
         ┌─────────▼──────────┐
         │  Azure AD          │
         │  (Token Exchange)  │
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  ACR               │
         │  /v2/.../tags/list │
         └────────────────────┘
```

인증 흐름: **Federated Token → AAD Access Token → ACR Refresh Token**

***

## ✅ Step 1: ArgoCD 설치

```bash
kubectl create namespace argocd

kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

Pod 상태 확인:

```bash
kubectl get pods -n argocd
```

> **참고**: Redis 이미지(`public.ecr.aws/...`)가 pull 실패할 경우, Docker Hub 이미지로 대체:
> ```bash
> kubectl set image deployment/argocd-redis redis=redis:8.2.3-alpine -n argocd
> ```

***

## ✅ Step 2: ArgoCD Image Updater 설치

```bash
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/master/config/install.yaml
```

> **주의**: `stable` 브랜치가 아니라 `master/config/install.yaml` 경로임.

설치 확인:

```bash
kubectl get pods -n argocd | grep image-updater
```

***

## ✅ Step 3: Managed Identity 생성 및 ACR 역할 부여

Image Updater 전용 Managed Identity를 생성하고 ACR에 `AcrPull` 역할을 부여한다.

```bash
# 1. Managed Identity 생성
az identity create \
  --name id-image-updater-acr \
  --resource-group <RG_NAME> \
  --location <LOCATION>

# 출력에서 clientId, principalId 기록
# clientId: 예) 4baa8b8b-e2db-4c10-9043-168edc8466a0
# principalId: 예) 8eb24516-2c4d-4217-9239-353ec59ae24a

# 2. ACR에 AcrPull 역할 부여
ACR_ID=$(az acr show --name <ACR_NAME> --query id -o tsv)

az role assignment create \
  --assignee "<PRINCIPAL_ID>" \
  --role "AcrPull" \
  --scope "$ACR_ID"
```

### 확인 방법

```bash
# Managed Identity 확인
az identity show \
  --name id-image-updater-acr \
  --resource-group <RG_NAME> \
  --query "{name:name, clientId:clientId, principalId:principalId}" \
  -o table

# 역할 할당 확인
az role assignment list \
  --assignee "<PRINCIPAL_ID>" \
  --scope "$ACR_ID" \
  --output table
```

***

## ✅ Step 4: Workload Identity Federation 설정

Kubernetes ServiceAccount를 Azure Managed Identity에 연결하는 Federated Credential을 생성한다.

```bash
# OIDC Issuer URL 조회
AKS_OIDC_ISSUER=$(az aks show \
  --name <AKS_NAME> \
  --resource-group <RG_NAME> \
  --query "oidcIssuerProfile.issuerUrl" -o tsv)

# Federated Credential 생성
az identity federated-credential create \
  --name fc-image-updater \
  --identity-name id-image-updater-acr \
  --resource-group <RG_NAME> \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject "system:serviceaccount:argocd:argocd-image-updater-controller" \
  --audiences "api://AzureADTokenExchange"
```

> **subject 값의 형식**: `system:serviceaccount:<namespace>:<service-account-name>`
> Image Updater의 SA 이름은 `argocd-image-updater-controller`

### 확인 방법

```bash
# Federated Credential 확인
az identity federated-credential show \
  --name fc-image-updater \
  --identity-name id-image-updater-acr \
  --resource-group <RG_NAME> \
  -o table

# 기대 출력:
# Issuer: https://<region>.oic.prod-aks.azure.com/...
# Subject: system:serviceaccount:argocd:argocd-image-updater-controller
```

***

## ✅ Step 5: ACR 인증 스크립트 ConfigMap 생성

공식 문서에 기반한 auth 스크립트. Workload Identity의 Federated Token을 이용해 ACR Refresh Token을 발급받는다.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-auth
  namespace: argocd
data:
  auth.sh: |
    #!/bin/sh
    set -eo pipefail

    AAD_ACCESS_TOKEN=$(cat $AZURE_FEDERATED_TOKEN_FILE)

    ACCESS_TOKEN=$(wget --output-document - --header "Content-Type: application/x-www-form-urlencoded" \
    --post-data="grant_type=client_credentials&client_id=${AZURE_CLIENT_ID}&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer&scope=https://management.azure.com/.default&client_assertion=${AAD_ACCESS_TOKEN}" \
    https://login.microsoftonline.com/${AZURE_TENANT_ID}/oauth2/v2.0/token \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

    ACR_REFRESH_TOKEN=$(wget --quiet --header="Content-Type: application/x-www-form-urlencoded" \
    --post-data="grant_type=access_token&service=${ACR_NAME}&access_token=${ACCESS_TOKEN}" \
    --output-document - \
    "https://${ACR_NAME}/oauth2/exchange" |
    python3 -c "import sys, json; print(json.load(sys.stdin)['refresh_token'])")

    echo "00000000-0000-0000-0000-000000000000:$ACR_REFRESH_TOKEN"
```

```bash
kubectl apply -f argocd-image-updater-auth.yaml
```

**스크립트 동작 원리:**

1. `AZURE_FEDERATED_TOKEN_FILE` → Workload Identity가 자동 주입한 JWT 토큰
2. AAD `/oauth2/v2.0/token` 호출 → Azure AD Access Token 획득
3. ACR `/oauth2/exchange` 호출 → ACR Refresh Token 획득
4. `username:password` 형식으로 출력 → Image Updater가 Docker auth로 사용

***

## ✅ Step 6: registries.conf 설정

```bash
kubectl patch configmap argocd-image-updater-config -n argocd --type merge -p '{
  "data": {
    "registries.conf": "registries:\n  - name: Azure Container Registry\n    api_url: https://<ACR_NAME>.azurecr.io\n    prefix: <ACR_NAME>.azurecr.io\n    default: true\n    credentials: ext:/app/auth/auth.sh\n    credsexpire: 1h\n"
  }
}'
```

핵심 설정값:
*   `credentials: ext:/app/auth/auth.sh` — 외부 스크립트를 통한 인증
*   `credsexpire: 1h` — 토큰 캐시 만료 시간 (ACR 토큰 유효기간에 맞춤)

***

## ✅ Step 7: ServiceAccount 패치

```bash
kubectl patch sa argocd-image-updater-controller -n argocd --type merge -p '{
  "metadata": {
    "labels": {
      "azure.workload.identity/use": "true"
    },
    "annotations": {
      "azure.workload.identity/client-id": "<MANAGED_IDENTITY_CLIENT_ID>",
      "azure.workload.identity/tenant-id": "<TENANT_ID>"
    }
  }
}'
```

### 확인 방법

```bash
kubectl get sa argocd-image-updater-controller -n argocd -o yaml | grep -A5 "annotations\|labels"
```

***

## ✅ Step 8: Deployment 패치

auth 스크립트 볼륨 마운트, ACR_NAME 환경변수, Workload Identity 라벨을 추가한다.

```bash
cat <<'EOF' | kubectl patch deployment argocd-image-updater-controller -n argocd --type strategic --patch-file /dev/stdin
spec:
  template:
    metadata:
      labels:
        azure.workload.identity/use: "true"
    spec:
      containers:
        - name: argocd-image-updater-controller
          env:
            - name: ACR_NAME
              value: <ACR_NAME>.azurecr.io
          volumeMounts:
            - mountPath: /app/auth
              name: auth
      volumes:
        - configMap:
            name: argocd-image-updater-auth
            defaultMode: 493
          name: auth
EOF
```

> `defaultMode: 493` = `0755` (실행 권한 필수)

### 확인 방법

Pod가 재시작된 후, Workload Identity 환경변수가 정상 주입되었는지 확인:

```bash
kubectl exec -n argocd deployment/argocd-image-updater-controller -- env | grep AZURE
```

기대 출력:

```
AZURE_CLIENT_ID=<CLIENT_ID>
AZURE_TENANT_ID=<TENANT_ID>
AZURE_FEDERATED_TOKEN_FILE=/var/run/secrets/azure/tokens/azure-identity-token
AZURE_AUTHORITY_HOST=https://login.microsoftonline.com/
```

auth.sh 스크립트 마운트 확인:

```bash
kubectl exec -n argocd deployment/argocd-image-updater-controller -- ls -la /app/auth/
```

***

## ✅ Step 9: ImageUpdater CR 생성

Image Updater v2는 **CRD 기반**으로 동작한다. Application annotation 방식이 아닌 `ImageUpdater` CR을 생성해야 한다.

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: <CR_NAME>
  namespace: argocd
spec:
  applicationRefs:
    - namePattern: "<ARGOCD_APPLICATION_NAME>"
      images:
        - alias: myapp
          imageName: <ACR_NAME>.azurecr.io/<REPO_NAME>
          commonUpdateSettings:
            updateStrategy: semver
          manifestTargets:
            kustomize:
              name: <ACR_NAME>.azurecr.io/<REPO_NAME>
  writeBackConfig:
    method: argocd
```

> **주의**: `imageName`에 태그를 붙이지 않는다. `:1.0.0`을 붙이면 해당 버전이 semver constraint로 해석되어 정확히 그 버전만 eligible로 처리된다.

### writeBack 방식

| method | 설명 |
|---|---|
| `argocd` | ArgoCD Application의 spec을 직접 패치 (Git 변경 없음, 테스트에 적합) |
| `git` | Git repo에 커밋하여 변경 반영 (프로덕션 권장) |

***

## ✅ 검증 방법

### 1. ACR에 테스트 이미지 준비

```bash
# az acr import로 태그 여러 개 생성 (방화벽 우회)
az acr import --name <ACR_NAME> --source docker.io/library/nginx:1.25.0 --image test-app:1.0.0 --force
az acr import --name <ACR_NAME> --source docker.io/library/nginx:1.25.1 --image test-app:1.1.0 --force
az acr import --name <ACR_NAME> --source docker.io/library/nginx:1.25.2 --image test-app:1.2.0 --force

# 태그 확인
az acr repository show-tags --name <ACR_NAME> --repository test-app --orderby time_desc -o table
```

### 2. Image Updater 로그 확인

```bash
kubectl logs -n argocd deployment/argocd-image-updater-controller --tail=30
```

정상 동작 시 기대 로그:

```
msg="found 3 from 3 tags eligible for consideration"
msg="Setting new image to <ACR>.azurecr.io/test-app:1.2.0"
msg="Successfully updated image 'test-app:1.0.0' to 'test-app:1.2.0'"
msg="Successfully updated the live application spec"
msg="Processing results: applications=1 images_considered=1 images_skipped=0 images_updated=1 errors=0"
```

### 3. 실제 Deployment 이미지 확인

```bash
kubectl get deployment <DEPLOY_NAME> -n <NAMESPACE> \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

***

## 🔍 디버깅 가이드

### 디버그 로그 활성화

```bash
kubectl patch configmap argocd-image-updater-config -n argocd \
  --type merge -p '{"data":{"log.level":"debug"}}'

kubectl rollout restart deployment argocd-image-updater-controller -n argocd
```

### 오류 1: `unauthorized: authentication required`

```
level=error msg="Could not get tags from registry: Get \"https://<ACR>.azurecr.io/v2/.../tags/list\": unauthorized"
```

**원인**: Image Updater Pod이 ACR에 인증하지 못함.

**확인 순서:**

```bash
# 1. Workload Identity 환경변수 주입됐는지 확인
kubectl exec -n argocd deployment/argocd-image-updater-controller -- env | grep AZURE

# 2. Federated Token 파일 존재 확인
kubectl exec -n argocd deployment/argocd-image-updater-controller -- cat $AZURE_FEDERATED_TOKEN_FILE | head -1

# 3. auth.sh 스크립트 마운트 확인
kubectl exec -n argocd deployment/argocd-image-updater-controller -- ls -la /app/auth/auth.sh

# 4. registries.conf에 credentials: ext:/app/auth/auth.sh 설정 확인
kubectl get configmap argocd-image-updater-config -n argocd -o jsonpath='{.data.registries\.conf}'

# 5. Managed Identity에 AcrPull 역할 확인
az role assignment list --assignee "<PRINCIPAL_ID>" --scope "<ACR_ID>" --output table
```

**흔한 원인:**
*   `attach-acr`만 했을 경우 → kubelet identity만 권한 있음, Image Updater Pod은 별도 인증 필요
*   SA에 `azure.workload.identity/client-id` annotation 누락
*   Deployment에 `azure.workload.identity/use: "true"` label 누락
*   Federated Credential의 subject가 SA 이름과 불일치

### 오류 2: `skipping app of type 'Directory' because it's not of supported source type`

```
level=warning msg="skipping app 'argocd/test-app' of type 'Directory' because it's not of supported source type"
```

**원인**: ArgoCD Application의 소스가 plain directory.

**해결**: 소스 디렉토리에 `kustomization.yaml`을 추가하여 Kustomize 소스로 전환.

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
images:
  - name: <ACR_NAME>.azurecr.io/<REPO>
    newTag: "1.0.0"
```

Git push 후 ArgoCD Application을 refresh:

```bash
kubectl patch application <APP_NAME> -n argocd \
  --type merge -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"normal"}}}'

# 소스 타입 확인
kubectl get application <APP_NAME> -n argocd -o jsonpath='{.status.sourceType}'
# 기대: Kustomize
```

### 오류 3: `Invalid match option syntax`

```
level=warning msg="Invalid match option syntax '^[0-9]+\\.[0-9]+\\.[0-9]+$', ignoring"
```

**원인**: YAML에서 `\\`가 리터럴 `\`로 해석되어 regex에 `\\.`이 전달됨.

**해결**: semver 전략 사용 시, `allowTags`를 제거하면 semver 태그 자동 필터링됨. 필요하면 single backslash 사용:

```yaml
allowTags: "^[0-9]+\\.[0-9]+\\.[0-9]+$"   # ❌ 이중 이스케이프
allowTags: "^\\d+\\.\\d+\\.\\d+$"           # 필요시 YAML 문자열 확인
# semver 전략에서는 생략 가능                  # ✅ 권장
```

### 오류 4: `already on latest allowed version` (업데이트 안 됨)

```
level=debug msg="Using version constraint '1.0.0' when looking for a new tag"
level=debug msg="found 1 from 3 tags eligible for consideration"
level=debug msg="Image already on latest allowed version"
```

**원인**: `imageName`에 태그를 포함했을 때(`:1.0.0`), 해당 태그가 semver constraint로 사용되어 정확히 `1.0.0`만 eligible.

**해결**: `imageName`에서 태그 제거.

```yaml
imageName: acrrubiconkrc01.azurecr.io/test-app:1.0.0  # ❌
imageName: acrrubiconkrc01.azurecr.io/test-app         # ✅
```

### 오류 5: AZURE 환경변수 미주입

Pod에서 `env | grep AZURE` 시 아무것도 안 나오는 경우:

```bash
# SA label 확인
kubectl get sa argocd-image-updater-controller -n argocd \
  -o jsonpath='{.metadata.labels.azure\.workload\.identity/use}'
# 기대: true

# Pod label 확인
kubectl get pod -n argocd -l app.kubernetes.io/name=argocd-image-updater \
  -o jsonpath='{.items[0].metadata.labels.azure\.workload\.identity/use}'
# 기대: true

# Pod 재시작이 필요할 수 있음
kubectl rollout restart deployment argocd-image-updater-controller -n argocd
```

***

## 📌 attach-acr 방식이 동작하지 않는 이유

`az aks update --attach-acr`로 kubelet identity에 AcrPull을 부여하면 Image Updater도 자연스럽게 ACR에 접근할 수 있을 것 같지만, 실제로는 **동작하지 않는다**.

| 항목 | attach-acr (kubelet identity) | Workload Identity + ext 스크립트 |
|---|---|---|
| 원리 | kubelet identity에 AcrPull 부여 | Federated Token → AAD Token → ACR Token |
| 적용 대상 | 노드가 이미지 pull할 때 (containerd) | Image Updater Pod이 ACR API 직접 호출 |
| Image Updater 인증 | ❌ Pod은 kubelet identity 사용 불가 | ✅ Workload Identity로 토큰 교환 |
| 결과 | `unauthorized` 에러 | 정상 동작 |

`attach-acr`은 노드의 컨테이너 런타임(containerd)이 이미지를 pull할 때만 유효하다. Image Updater는 Pod 내에서 ACR의 REST API(`/v2/.../tags/list`)를 직접 호출하므로 kubelet identity의 권한을 상속받지 못한다. 따라서 **Workload Identity + 외부 스크립트** 방식으로 Pod 수준의 인증을 별도 구성해야 한다.

***

## 📌 네트워크 요구사항: Azure Firewall 환경에서의 아웃바운드 허용

auth.sh 스크립트는 토큰 교환 과정에서 다음 두 엔드포인트를 호출한다:

| 단계 | 엔드포인트 | 용도 |
|---|---|---|
| 1 | `login.microsoftonline.com` | Federated Token → AAD Access Token |
| 2 | `<ACR_NAME>.azurecr.io/oauth2/exchange` | AAD Access Token → ACR Refresh Token |

AKS를 **Azure Firewall + UDR(`0.0.0.0/0` → Firewall)** 구성으로 운영하는 경우, Pod의 모든 아웃바운드 트래픽이 Firewall을 경유한다. 이때 `login.microsoftonline.com`이 Firewall에서 허용되지 않으면 auth.sh가 실패하고 `unauthorized` 에러가 발생한다.

### AKS 필수 아웃바운드 FQDN

`login.microsoftonline.com`은 AKS가 Azure Firewall 뒤에서 동작하기 위해 **반드시 허용해야 하는 필수 FQDN**이다 (노드 부팅, kubelet 인증 등에 사용). 따라서 AKS 필수 아웃바운드 규칙을 올바르게 구성한 환경이라면, Image Updater의 auth.sh도 별도 설정 없이 동작한다.

> **참고**: `login.microsoftonline.com` (Azure AD / Entra ID)은 글로벌 멀티테넌트 서비스이므로 **Private Endpoint를 지원하지 않는다**. 반드시 Firewall Application Rule(FQDN) 또는 Network Rule(Service Tag `AzureActiveDirectory`)로 허용해야 한다.

### Firewall에서 허용되지 않은 경우 조치 방법

**Application Rule (FQDN 기반, 권장):**

```
Target FQDNs: login.microsoftonline.com
Protocol:     Https (443)
Source:       <AKS_SUBNET_CIDR>
```

**Network Rule (Service Tag 기반):**

```
Destination:  Service Tag "AzureActiveDirectory"
Port:         443
Protocol:     TCP
Source:       <AKS_SUBNET_CIDR>
```

| 엔드포인트 | Private Endpoint | Firewall Rule 필요 여부 |
|---|---|---|
| `login.microsoftonline.com` | **불가** | **필수** (AKS 필수 아웃바운드) |
| `<ACR>.azurecr.io` | 가능 | ACR Private Endpoint 미사용 시 필요 |

***

## 📚 참고 링크

*   [공식 문서: Configuring Azure Container Registry](https://argocd-image-updater.readthedocs.io/en/stable/configuration/registries/#configuring-azure-container-registry-with)
*   [Image Updater v2 GitHub](https://github.com/argoproj-labs/argocd-image-updater)
*   [Azure Workload Identity 문서](https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview)
*   [AKS 필수 아웃바운드 네트워크 규칙](https://learn.microsoft.com/en-us/azure/aks/outbound-rules-control-egress)
*   [Azure Firewall을 사용한 AKS 아웃바운드 트래픽 제어](https://learn.microsoft.com/en-us/azure/aks/limit-egress-traffic)

***
