# ✅ AKS 생성 시 포털에서 Public IP 방지하는 방법

**Azure Portal에서 AKS 클러스터 생성 시 Public IP가 자동으로 붙는 것을 방지하는 가이드**

***

## 📌 문제 상황

Azure Portal을 통해 AKS(Azure Kubernetes Service) 클러스터를 생성할 때, 자동으로 Public IP 주소가 할당되어 클러스터가 인터넷에 노출되는 문제가 발생합니다. 보안상의 이유나 네트워크 정책으로 인해 Private 환경에서만 클러스터를 운영하고 싶은 경우, 이러한 Public IP 할당을 방지해야 합니다.

***

## 🔍 원인 분석

AKS 클러스터 생성 시 Public IP가 할당되는 주요 원인:

1. **API Server 접근 설정**: 기본적으로 Public endpoint가 활성화됨
2. **Load Balancer 타입**: 기본 Load Balancer가 Public IP를 자동 할당
3. **네트워크 설정**: 기본 네트워킹 옵션이 Public 접근을 허용

***

## ✅ 해결 방법 (Azure Portal)

### 1️⃣ Private Cluster 옵션 활성화

AKS 클러스터 생성 시 Private Cluster로 설정하여 API Server에 대한 Public IP 할당을 방지합니다.

#### 📍 포털 설정 단계:

1. **Azure Portal** → **Kubernetes services** → **Create**
2. **Basics** 탭에서 기본 정보 입력
3. **Networking** 탭으로 이동
4. **Network configuration** 섹션에서:
   - **Private cluster** 옵션을 **Enable**로 설정
   - 이 옵션을 활성화하면 API server가 Private IP만 사용

```
네트워킹 설정:
├─ Network configuration
│  ├─ Azure CNI 또는 kubenet 선택
│  └─ Private cluster: ✅ Enable
```

***

### 2️⃣ Load Balancer 구성 변경

Kubernetes Service의 Load Balancer가 Public IP를 생성하지 않도록 설정합니다.

#### 📍 포털 설정 단계:

1. **Networking** 탭에서
2. **Load balancer** 섹션:
   - **Load balancer SKU**: Standard 선택
   - **API server accessibility**: Private로 설정

***

### 3️⃣ Outbound Type 설정

클러스터의 아웃바운드 트래픽을 위한 Public IP 할당을 방지합니다.

#### 📍 포털 설정 단계:

1. **Networking** 탭에서
2. **Outbound type** 옵션:
   - **User-defined routing (UDR)** 선택
   - 또는 **NAT Gateway** 사용 (별도 설정 필요)

**옵션별 설명:**

| Outbound Type        | Public IP 할당 | 설명                                    |
| -------------------- | -------------- | --------------------------------------- |
| **Load balancer**    | ✅ Yes         | 기본 옵션, Public IP 자동 생성          |
| **User-defined routing** | ❌ No      | UDR 테이블을 통한 라우팅, Public IP 없음 |
| **NAT Gateway**      | ⚠️ Depends    | NAT Gateway에 Public IP 할당됨          |

***

### 4️⃣ 완전한 Private AKS 구성 (권장)

완전히 폐쇄된 Private 환경을 위한 종합 설정:

#### 📍 포털 전체 설정:

**Basics 탭:**
- Resource group, Cluster name, Region 설정
- Kubernetes version 선택

**Networking 탭:**
- **Network configuration**: Azure CNI 또는 kubenet
- **Private cluster**: ✅ Enable
- **Private DNS Zone**: **System** 선택 (권장 - 자동 생성 및 VNet 연결)
- **API server accessibility**: Private
- **Outbound type**: User-defined routing

**Integration 탭:**
- **Container monitoring**: 필요 시 활성화
- **Azure Policy**: 필요 시 활성화

***

## 🔧 Private Cluster 사용 시 고려사항

### ✅ 필수 사전 준비

1. **Virtual Network (VNet)**: 기존 VNet 필요
2. **Subnet**: AKS 노드용 Subnet 생성
3. **Private DNS Zone**: Private DNS 영역 (**System 모드 권장** - 자동 생성 및 VNet 연결)
4. **Bastion 또는 Jump Box**: Private cluster 접근용

> ⚠️ **중요**: Private DNS Zone을 "System"으로 설정하면 Azure가 자동으로 DNS Zone을 생성하고 VNet에 연결합니다. Custom 또는 None 모드는 DNS 해석 실패(NXDOMAIN) 오류를 발생시킬 수 있습니다.

### ✅ 접근 방법

Private Cluster는 Public endpoint가 없으므로 다음 방법으로 접근:

1. **Azure Bastion**: VNet 내부에서 접근
2. **VPN Gateway**: 온프레미스에서 VPN 연결
3. **ExpressRoute**: 전용 회선 통한 연결
4. **Jumpbox VM**: VNet 내부에 관리용 VM 배치

```bash
# Jumpbox VM에서 kubectl 설정
az aks get-credentials --resource-group myRG --name myPrivateAKS
kubectl get nodes
```

***

## 🔐 추가 보안 설정

### 1️⃣ Authorized IP Ranges (Public Cluster인 경우)

Private Cluster를 사용할 수 없는 경우, API server 접근을 특정 IP로 제한:

1. **Networking** 탭
2. **API server accessibility**: Public
3. **Specify authorized IP ranges** 활성화
4. 허용할 IP 범위 입력 (예: `203.0.113.0/24`)

### 2️⃣ Network Policy 활성화

1. **Networking** 탭
2. **Network policy**: Azure 또는 Calico 선택
3. Pod 간 트래픽 제어 가능

***

## 📋 설정 검증

### ✅ AKS Cluster 생성 후 확인

```bash
# 클러스터 정보 확인
az aks show --resource-group myRG --name myAKS --query "apiServerAccessProfile"

# Private Cluster 여부 확인
az aks show --resource-group myRG --name myAKS --query "apiServerAccessProfile.enablePrivateCluster"

# Public IP 주소 확인 (없어야 함)
az network public-ip list --resource-group MC_myRG_myAKS_region --output table
```

### ✅ 예상 결과 (Private Cluster)

```json
{
  "enablePrivateCluster": true,
  "enablePrivateClusterPublicFQDN": false,
  "privateDNSZone": "/subscriptions/.../privateDnsZones/..."
}
```

***

## 🔧 트러블슈팅: Private DNS Zone 연결 문제

### ❌ 문제 증상

Private AKS 클러스터 생성 시 다음과 같은 오류가 발생할 수 있습니다:

```
VM has reported a failure when processing extension 'vmssCSE'
Error: NXDOMAIN - server can't find [cluster-name].privatelink.[region].azmk8s.io
API server connection check code: 52
```

**원인**: AKS 노드가 Private DNS Zone에 등록된 API 서버 FQDN을 해석하지 못함

### ✅ 해결 방법

#### 1️⃣ Private DNS Zone VNet Link 확인

Private DNS Zone이 AKS가 배포된 VNet에 연결되어 있는지 확인:

```bash
# Private DNS Zone 목록 확인
az network private-dns zone list --resource-group MC_myRG_myAKS_region --output table

# VNet Link 확인
az network private-dns link vnet list \
  --resource-group MC_myRG_myAKS_region \
  --zone-name [private-dns-zone-name] \
  --output table
```

#### 2️⃣ 포털에서 Private DNS Zone 설정 확인

**AKS 클러스터 생성 시:**

1. **Networking** 탭으로 이동
2. **Private cluster** 섹션에서:
   - ✅ **Enable private cluster** 체크
   - **Private DNS Zone** 옵션 선택:
     - **System** (권장): Azure가 자동으로 DNS Zone 생성 및 연결
     - **Custom**: 기존 Private DNS Zone 사용 (주의: 반드시 VNet Link 설정 필요)
     - **None**: DNS Zone 생성하지 않음 (비권장)

**권장 설정**:
```
Private Cluster:
├─ Enable private cluster: ✅ Yes
├─ Private DNS Zone: System (자동 관리)
└─ Enable private cluster public FQDN: ❌ No
```

#### 3️⃣ 기존 VNet에 Private DNS Zone 연결

만약 Custom DNS Zone을 사용하거나 이미 생성된 클러스터의 경우:

**포털 방법:**
1. **Azure Portal** → **Private DNS zones** 검색
2. AKS용 Private DNS Zone 선택 (예: `privatelink.koreacentral.azmk8s.io`)
3. 왼쪽 메뉴에서 **Virtual network links** 선택
4. **+ Add** 클릭
5. 설정:
   - **Link name**: 식별 가능한 이름 (예: `aks-vnet-link`)
   - **Virtual network**: AKS 노드가 배포된 VNet 선택
   - **Enable auto registration**: 필요한 경우 체크
6. **OK** 클릭

**CLI 방법:**
```bash
# VNet Link 생성
az network private-dns link vnet create \
  --resource-group MC_myRG_myAKS_region \
  --zone-name privatelink.koreacentral.azmk8s.io \
  --name aks-vnet-link \
  --virtual-network /subscriptions/{subscription-id}/resourceGroups/{vnet-rg}/providers/Microsoft.Network/virtualNetworks/{vnet-name} \
  --registration-enabled false
```

#### 4️⃣ DNS 해석 테스트

VNet 내부의 VM에서 DNS 해석 테스트:

```bash
# Private DNS 해석 확인
nslookup [cluster-name].[cluster-id].privatelink.koreacentral.azmk8s.io

# 또는
dig [cluster-name].[cluster-id].privatelink.koreacentral.azmk8s.io

# 예상 결과: Private IP 주소 반환 (예: 10.x.x.x)
```

#### 5️⃣ VNet DNS 설정 확인

VNet의 DNS 서버 설정이 올바른지 확인:

**포털 방법:**
1. **Virtual networks** → 해당 VNet 선택
2. **DNS servers** 선택
3. 설정 확인:
   - **Default (Azure-provided)**: Azure DNS 사용 (권장)
   - **Custom**: 사용자 지정 DNS 서버 (Private DNS Zone 포워딩 필요)

**Custom DNS 사용 시 추가 구성:**
- DNS 서버가 Azure Private DNS (`168.63.129.16`)로 포워딩하도록 설정 필요

### 🔄 재생성이 필요한 경우

다음 상황에서는 클러스터 재생성 고려:

1. Private DNS Zone을 "None"으로 설정하여 생성한 경우
2. 잘못된 Custom DNS Zone을 지정한 경우
3. VNet Link 문제를 해결할 수 없는 경우

**재생성 시 권장 설정:**
- Private DNS Zone: **System** 선택
- VNet 및 Subnet 사전 준비
- 올바른 네트워킹 구성 확인

***

## 🚨 주의사항

1. **Private Cluster는 생성 후 Public으로 변경 불가**
   - Private → Public 전환 불가능
   - 재생성 필요

2. **VNet Peering 고려**
   - 다른 VNet에서 접근 시 Peering 필요
   - Private DNS Zone 공유 설정 필요

3. **비용 고려**
   - Private Link 사용 시 추가 비용 발생
   - NAT Gateway 사용 시 비용 발생

4. **Container Registry 접근**
   - Private Cluster는 ACR Private Endpoint 설정 권장
   - 또는 Service Endpoint 사용

***

## 💡 Best Practices

1. ✅ **프로덕션 환경**: Private Cluster + UDR 사용
2. ✅ **개발/테스트**: Authorized IP Ranges 사용
3. ✅ **Hybrid 환경**: ExpressRoute + Private Cluster
4. ✅ **모니터링**: Azure Monitor for Containers 활성화
5. ✅ **백업**: Jumpbox를 통한 관리 접근 경로 확보

***

## 🎯 요약

| 목적                          | 포털 설정                                        |
| ----------------------------- | ------------------------------------------------ |
| **API Server Public IP 방지** | Networking → Private cluster: Enable            |
| **Outbound Public IP 방지**   | Networking → Outbound type: User-defined routing |
| **완전 Private 환경**         | Private cluster + UDR + Private DNS              |
| **부분 접근 제어**            | Authorized IP Ranges 설정                        |

***

## 📚 참고 링크

- [Azure Private AKS Cluster 공식 문서](https://learn.microsoft.com/ko-kr/azure/aks/private-clusters)
- [AKS Networking Concepts](https://learn.microsoft.com/ko-kr/azure/aks/concepts-network)
- [AKS Outbound Network Configuration](https://learn.microsoft.com/ko-kr/azure/aks/egress-outboundtype)
- [AKS Security Best Practices](https://learn.microsoft.com/ko-kr/azure/aks/operator-best-practices-network)

***
