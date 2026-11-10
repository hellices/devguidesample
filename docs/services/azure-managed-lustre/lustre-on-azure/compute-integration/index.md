---
title: 'Azure Managed Lustre 컴퓨트 연결: VM·AKS·CycleCloud와 네트워크 요건'
description: Linux VM, AKS CSI driver, CycleCloud·Slurm이 Azure Managed Lustre를 mount하는 방식과 subnet·포트·가용성 영역 요건, 온프레미스·Azure Local 연결의 문서화 범위를 정리합니다.
document_type: research
services: [azure-managed-lustre, azure-kubernetes-service]
technologies: [lustre, kubernetes]
tags: [design, networking, storage]
status: current
verification_status: verified
sources_checked_at: 2026-11-10
published_at: 2026-11-10
topic_order: 3
official_sources:
  - title: Azure Managed Lustre file system prerequisites
    url: https://learn.microsoft.com/azure/azure-managed-lustre/amlfs-prerequisites
  - title: Configure a network security group for Azure Managed Lustre
    url: https://learn.microsoft.com/azure/azure-managed-lustre/configure-network-security-group
  - title: Connect clients to an Azure Managed Lustre file system
    url: https://learn.microsoft.com/azure/azure-managed-lustre/connect-clients
  - title: Plan your Lustre client installation
    url: https://learn.microsoft.com/azure/azure-managed-lustre/client-install-plan
  - title: Install Lustre client software
    url: https://learn.microsoft.com/azure/azure-managed-lustre/client-install
  - title: Upgrade Lustre client software to the current version
    url: https://learn.microsoft.com/azure/azure-managed-lustre/client-upgrade
  - title: Automatically mount clients to an Azure Managed Lustre file system by using fstab
    url: https://learn.microsoft.com/azure/azure-managed-lustre/automount-clients-fstab
  - title: Optimize Azure Managed Lustre performance
    url: https://learn.microsoft.com/azure/azure-managed-lustre/optimize-performance
  - title: Optimize file and directory layouts in Azure Managed Lustre
    url: https://learn.microsoft.com/azure/azure-managed-lustre/optimize-file-layouts
  - title: Troubleshoot Azure Managed Lustre performance issues
    url: https://learn.microsoft.com/azure/azure-managed-lustre/troubleshoot-performance
  - title: Enable and validate virtual network encryption with Azure Managed Lustre
    url: https://learn.microsoft.com/azure/azure-managed-lustre/vnet-encryption
  - title: Migrate data from an on-premises POSIX file system to Azure Managed Lustre
    url: https://learn.microsoft.com/azure/azure-managed-lustre/migrate-data-from-linux
  - title: Use the Azure Managed Lustre CSI driver with Azure Kubernetes Service
    url: https://learn.microsoft.com/azure/aks/azure-managed-lustre-overview
  - title: Install the Azure Managed Lustre CSI driver
    url: https://learn.microsoft.com/azure/aks/azure-managed-lustre-install
  - title: Install Azure Managed Lustre with AKS CLI options (preview)
    url: https://learn.microsoft.com/azure/aks/azure-managed-lustre-install-cli-preview
  - title: Plan network architecture for AKS with Azure Managed Lustre
    url: https://learn.microsoft.com/azure/aks/azure-managed-lustre-network-planning
  - title: Statically provision Azure Managed Lustre volumes for AKS
    url: https://learn.microsoft.com/azure/aks/azure-managed-lustre-static-provisioning
  - title: Dynamically provision Azure Managed Lustre volumes for AKS
    url: https://learn.microsoft.com/azure/aks/azure-managed-lustre-dynamic-provisioning
  - title: Dynamic provisioning reference for Azure Managed Lustre on AKS
    url: https://learn.microsoft.com/azure/aks/azure-managed-lustre-dynamic-provisioning-reference
  - title: Use Azure Firewall with Azure Managed Lustre
    url: https://learn.microsoft.com/azure/azure-managed-lustre/configure-firewall
  - title: Configure NFS mounts
    url: https://learn.microsoft.com/azure/cyclecloud/how-to/mount-fileserver?view=cyclecloud-8
  - title: Plan your CycleCloud Workspace for Slurm deployment
    url: https://learn.microsoft.com/azure/cyclecloud/how-to/ccws/plan-your-deployment?view=cyclecloud-8
  - title: Quickstart - Deploy Azure CycleCloud Workspace for Slurm using Azure Marketplace
    url: https://learn.microsoft.com/azure/cyclecloud/qs-deploy-ccws?view=cyclecloud-8
---

# Azure Managed Lustre 컴퓨트 연결: VM·AKS·CycleCloud와 네트워크 요건

Azure Managed Lustre(AMLFS)에 컴퓨트를 붙이는 공식 경로는 세 가지이며, 모두
**같은 Azure 네트워크 안의 Linux 노드가 Lustre client 커널 모듈로 TCP mount**
하는 같은 원리를 따릅니다. 차이는 client 설치와 mount를 누가 자동화하느냐입니다.
전체 흐름은 [주제 개요](../index.md), 서비스 측 구성은
[관리형 기능](../managed-features/index.md)에서 볼 수 있습니다.

| 연결 경로 | client 설치·mount 주체 | 주로 맞는 워크로드 |
|---|---|---|
| Linux VM·VMSS 직접 mount | 사용자가 `packages.microsoft.com` 패키지 설치 후 `mount -t lustre` | 직접 관리하는 HPC 노드, 데이터 준비 VM |
| AKS + Azure Lustre CSI driver | CSI driver가 노드에 client를 적재하고 PV를 mount | 컨테이너 기반 AI 학습·추론, 배치 |
| Azure CycleCloud·CycleCloud Workspace for Slurm | 클러스터 템플릿의 `type = lustre` mount 설정 | Slurm 기반 전통 HPC |

!!! note "HCI 해석 범위"
    요청의 "HCI"는 이 문서에서 **HPC 컴퓨트 클러스터의 연결**로 해석했습니다.
    Azure Local(구 Azure Stack HCI)이나 온프레미스 노드의 mount 여부는
    [온프레미스·Azure Local 연결](#on-prem-azure-local) 절에 따로 정리했습니다.

## 네트워크 요건: 전용 subnet·Lustre 포트·VNet peering { #network }

AMLFS는 사용자가 지정한 VNet subnet에 서버 노드 IP를 할당하므로, client 연결의
전제는 **client subnet과 AMLFS subnet 사이의 직접 IP 경로**입니다. 생성 후에는
다른 VNet이나 subnet으로 옮길 수 없고 IPv4만 지원합니다.

| 항목 | 요건 |
|---|---|
| subnet 크기 | 용량에 비례합니다. 예: 4–16 TiB는 `/27` 이상, 200–400 TiB는 `/23` 이상(최소 기준). 정확한 값은 `az amlfs get-subnets-size --sku <SKU> --storage-capacity <TiB>`로 계산합니다. |
| subnet 공유 | Azure NetApp Files와 subnet을 공유할 수 없으며, 과거에 NetApp Files 리소스를 포함했던 subnet에서도 배포가 실패합니다. |
| Lustre 포트 | client subnet ↔ AMLFS subnet 사이 **TCP 988, 1019–1023** 인바운드·아웃바운드 허용. 기본 `AllowVnetInBound`·`AllowVnetOutBound` 규칙으로 충족됩니다. client에서 다른 서비스가 이 포트들을 예약·사용하면 안 되며, 특히 `ypbind`가 988을 점유하지 않게 합니다. |
| subnet 내부 | AMLFS subnet 내부 호스트 간 통신 허용(배포에 TCP 22 필요). |
| 아웃바운드 | `AzureCloud` 서비스 태그로 모든 포트·프로토콜을 허용하거나, NSG 문서의 개별 규칙(AzureMonitor·AzureKeyVault·AzureActiveDirectory·Storage·AzureResourceManager·EventHub 등 443과 NTP UDP 123)을 리전에 맞게 구성합니다. 2026-03-31 이후 만든 VNet은 기본이 private subnet이므로 아웃바운드 경로를 명시적으로 열어야 합니다. |
| 다른 VNet의 client | VNet peering으로 연결합니다. AKS 네트워크 문서는 구독·리전 간 peering도 가능하다고 설명하며 주소 공간 중복을 피하라고 안내합니다. |
| 데이터 경로 | NVA나 Azure Firewall을 client ↔ AMLFS 경로에 두지 않고 subnet 간 직접 라우팅을 권장합니다. 방화벽은 subnet에 들어오거나 나가는 트래픽만 필터링하고 subnet 내부 트래픽은 거치지 않게 합니다. |
| 전송 중 암호화 | 지원 VM 계열에서 VNet encryption으로 client ↔ AMLFS 트래픽을 암호화할 수 있습니다. peering된 VNet도 encryption을 켜야 합니다. |

## Linux VM client: kmod·DKMS 패키지와 mount 명령 { #vm-client }

VM client는 Microsoft가 `packages.microsoft.com`의 `amlfs-<codename>` 저장소로
배포하는 Lustre client 패키지를 설치합니다. 지원 배포판은 Ubuntu 20.04·22.04·24.04,
Azure Linux 3, RHEL·AlmaLinux 8·9·10, AlmaLinux HPC 8.6이며 OS에 따라 Lustre
2.15 또는 2.17 client를 사용합니다. Ubuntu 18.04와 RHEL 7은 2.15.4에 고정되어 있고,
arm64 패키지는 Ubuntu 24.04만 제공합니다.

| 설치 방식 | 특성 | 선택 기준 |
|---|---|---|
| prebuilt kmod | 패키지 이름이 실행 중인 커널 버전에 묶임. Secure Boot용으로 사전 서명되어 Trusted Launch VM에서 추가 설정 없이 동작 | 커널을 고정 운영하고 Secure Boot를 쓰는 노드 |
| DKMS | 커널 업그레이드 시 모듈을 자동 재빌드. 서명되지 않아 Secure Boot 비활성 또는 MOK 등록 필요 | 커널이 자주 바뀌는 개발·테스트 노드 |

```bash
# Ubuntu 24.04 kmod 예시: 실행 중인 커널과 같은 버전의 패키지를 고정 설치
sudo apt install amlfs-lustre-client-2.17.0-28-gc7c975e=$(uname -r)

# mount: <MGS_IP>는 포털의 client connection 정보, lustrefs는 고정 이름
sudo mount -t lustre -o noatime,flock <MGS_IP>@tcp:/lustrefs /mnt/lustre
```

운영할 때 확인할 점은 다음과 같습니다.

- 이미 지원하는 커널 계열에 새 유지 관리 커널이 나오면 Microsoft는 일반적으로
  영업일 기준 1일 이내에 대응 메타패키지를 게시합니다(보장 값 아님).
- kmod 방식에서 커널만 올릴 때도 `amlfs-lustre-client` 메타패키지를 함께 올려야
  재부팅 후 client가 동작합니다. Azure Linux 3는 기존 Lustre 패키지 제거 → 커널
  업그레이드·재부팅 → 새 커널용 client 설치 순서를 따릅니다.
- Ubuntu 22.04·24.04는 HWE 대신 LTS 커널, RHEL 9는 EUS minor(기준일 권장값 9.6 EUS)
  고정을 권장합니다.
- Lustre 버전 업그레이드는 Ubuntu·RHEL 기준 unmount → 기존 패키지 제거 → 새 패키지
  설치 → `lustre_rmmod` → 확인 순서입니다. Azure Linux 3는 unmount → `lustre_rmmod` →
  제거 → 설치 → `modprobe lustre` 확인 순서입니다. DKMS도 Lustre 버전 업그레이드에는
  같은 절차를 따르며, 커널 업그레이드 시 재빌드만 자동으로 처리됩니다.
- 종료·재배포 전에는 `umount`를 `-f`·`-l` 없이 실행합니다. 정리되지 않은 client는
  eviction을 일으켜 다른 client가 최대 15분까지 멈출 수 있습니다.
- 재부팅 후 자동 mount는 `_netdev,x-systemd.automount` 옵션을 포함한 `fstab` 항목으로
  구성합니다.

## AKS: Azure Lustre CSI driver의 정적·동적 프로비저닝 { #aks }

AKS는 오픈 소스
[Azure Lustre CSI driver](https://github.com/kubernetes-sigs/azurelustre-csi-driver)로
AMLFS를 `ReadWriteMany` 볼륨으로 사용합니다. driver는 AKS와 AMLFS 조합만 지원하며,
다른 Kubernetes 배포나 다른 Lustre 설치는 지원 대상이 아닙니다.

| 항목 | 내용 |
|---|---|
| 지원 범위(v0.6.0) | Kubernetes 1.29 이상, `Ubuntu2204`·`Ubuntu2404`·`AzureLinux3` 노드 풀. Windows 노드 풀 미지원 |
| 설치 | MCR의 Helm OCI chart(권장) 또는 버전 고정 스크립트. `az aks ... --enable-azure-managed-lustre` 관리형 확장 설치는 **preview** |
| 정적 프로비저닝 | 기존 AMLFS의 MGS IP를 StorageClass `mgs-ip-address`에 지정, provisioner `azurelustre.csi.azure.com` |
| 동적 프로비저닝(v0.3.0+) | PVC마다 새 AMLFS를 생성. `sku-name`, `zone`, `vnet-name`, `subnet-name`, 유지 관리 시간 등을 StorageClass 파라미터로 지정 |
| 권한 | 동적 프로비저닝은 CSI controller가 쓰는 identity에 subnet 읽기·join, subnet 요건 검증, AMLFS 읽기·생성·수정·삭제 권한 필요 |
| 네트워크 | AKS 전용 VNet + peering 또는 AMLFS VNet 안의 별도 subnet. Azure CNI Overlay 권장. 노드는 MCR·`packages.microsoft.com`에 접근해야 함 |

```yaml
# 정적 프로비저닝 StorageClass 발췌
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: azurelustre-static
provisioner: azurelustre.csi.azure.com
parameters:
  mgs-ip-address: <MGS_IP_ADDRESS>
reclaimPolicy: Retain
volumeBindingMode: Immediate
mountOptions:
  - noatime
  - flock
```

동적 프로비저닝 StorageClass가 `reclaimPolicy: Delete`이면 PVC를 지울 때 PV와
AMLFS 파일 시스템, 그 데이터도 함께 삭제되고, `Retain`이면 파일 시스템이 남아 수동
정리 대상이 됩니다. `Delete` 구성은 여러 작업이 공유하는 장기 데이터셋보다 작업 단위
scratch 공간에 맞는 방식이라고 해석할 수 있습니다(설계 해석).

## CycleCloud·Slurm: 클러스터 템플릿의 Lustre mount { #cyclecloud }

Azure CycleCloud는 AMLFS mount를 기본 지원하며, 클러스터 템플릿의 mount 설정에
`type = lustre`와 MGS 주소를 지정합니다. `export_path`를 생략하면
`tcp:/lustrefs/`가 사용되고 기본 mount 옵션은 `noatime, flock`입니다. 노드 축소나
노드 회수 때 깨끗하게 unmount하도록 **Termination Notifications** 활성화를 강하게
권장합니다.

```ini
[[[configuration cyclecloud.mounts.lustre_data]]]
type = lustre
address = <MGS_IP>
mountpoint = /lustre_data
export_path = tcp:/lustrefs/data/
options = noatime, flock
```

CycleCloud Workspace for Slurm(CCWS)은 Marketplace 배포 과정에서 새 AMLFS를
만들거나 기존 AMLFS를 추가 mount로 지정할 수 있습니다. 새로 만들면
`ccw-lustre-subnet`이라는 전용 subnet을 사용하고, 기존 VNet을 쓰는 경우에도 용량에
맞는 전용 Lustre subnet을 준비합니다. 컴퓨트 노드와 파일 시스템을 같은 가용성 영역에
두는 옵션도 제공합니다.

Azure Batch는 AMLFS 성능 문서에서 "가속 네트워킹을 켜야 하는 오케스트레이터"로만
언급되며, Batch 전용 mount 절차는 Learn에서 확인하지 못했습니다.

## 성능 배치 조건: 가용성 영역·가속 네트워킹·striping { #performance }

광고된 처리량을 얻으려면 client를 **AMLFS와 같은 가용성 영역**에 두고 모든 client
VM에서 **가속 네트워킹**을 켜야 합니다. Azure HPC·AI VM 크기는 모두 가속 네트워킹을
지원합니다. AMLFS가 만든 `amlfs-*-snic` NIC의 설정, 특히 가속 네트워킹은 변경하지
않습니다.

- 파일 레이아웃은 기본 Progressive File Layout(1 GiB까지 stripe 1개, 이후 5·10·전체
  OST로 확장)을 유지하고, 매우 큰 단일 파일만 `lfs setstripe -c -1`로 전체 OST에
  분산합니다. 작은 파일에 넓은 stripe는 권장하지 않습니다.
- MDT가 여러 개인 파일 시스템에는 배포 시 기본 디렉터리 round robin
  (`lfs setdirstripe -D -i -1 -c 1 --max-inherit=-1 --max-inherit-rr=-1`)이 자동
  적용되어 메타데이터 부하를 나누므로 사용자가 따로 설정하지 않아도 됩니다.
- 여러 client에서 동시에 mount 전체를 훑는 보안 스캐너·백신 실행을 피합니다.

## 온프레미스·Azure Local 연결: 직접 mount 미문서화와 Blob 경유 데이터 이동 { #on-prem-azure-local }

2026-11-10 기준 Microsoft Learn에서는 **온프레미스 서버나 Azure Local(구 Azure Stack
HCI) VM이 VPN·ExpressRoute를 거쳐 AMLFS를 직접 mount하는 절차나 지원 여부를 확인할 수
없습니다.** 지원하지 않는다는 명시도 없으며, client 연결 문서는 AMLFS subnet과의 직접
연결 또는 VNet peering만 설명합니다. CSI driver는 AKS 외 Kubernetes를 지원하지 않는다고
명시합니다. CycleCloud Workspace for Slurm 문서는 VPN·ExpressRoute를 기업 네트워크와
사용자 접속 경로로만 설명하며, 이를 Lustre 데이터 경로로 쓰는 방법은 다루지 않습니다.

온프레미스와 관련해 문서화된 경로는 **데이터 이동**입니다.

1. 온프레미스 POSIX 파일 시스템의 데이터를 AzCopy로 Azure Blob Storage에 올립니다.
   이 초기 업로드에는 VPN·ExpressRoute가 필요하지 않습니다.
2. 생성 시 Blob 컨테이너와 통합한 AMLFS에서 import job으로 namespace를 가져옵니다.

같은 문서는 NFS·SMB 같은 POSIX 프로토콜이 장거리 지연에서 처리량이 크게 떨어진다는
점을 Blob 중계 방식의 근거로 듭니다. 이를 바탕으로 하면 Azure Local 클러스터와 AMLFS를
함께 쓸 때 **Blob을 경계로 데이터셋을 주고받고, 고성능 I/O가 필요한 계산은 AMLFS와 같은
영역의 Azure 컴퓨트에서 실행**하는 구성이 현실적인 선택지입니다. Azure Local과 AMLFS의
조합을 직접 다룬 Learn 문서는 없으므로 이 구성은 설계 해석입니다.

## 해석 제한과 미확인 사항 { #limitations }

- **InfiniBand·RDMA(`o2ib`)**: AMLFS 문서는 client 트래픽을 `@tcp` mount와 가속
  네트워킹(SR-IOV) Ethernet으로만 설명합니다. HPC VM의 InfiniBand를 Lustre 트래픽에
  쓰는 방법은 문서화되어 있지 않습니다.
- **AKS와 AMLFS의 같은 subnet 배치**: prerequisites 문서는 허용한다고 쓰지만 AKS
  문서군은 일관되게 별도 subnet을 요구합니다. 이 문서는 최신 AKS 문서의 별도 subnet
  기준을 따릅니다.
- **CSI driver 기본 설치 경로의 상태**: AKS CLI 확장 설치는 preview로 명시되어 있으나,
  AKS 개요 문서의 "Both options are in preview" 문구가 Helm·스크립트 설치까지 포함하는지
  분명하지 않습니다.
- **RHEL·AlmaLinux 9.8**: 지원 매트릭스에는 있으나 설치 문서는 Lustre 2.15.9 출시 전까지
  지원하지 않는다고 설명합니다. 배포 전 `packages.microsoft.com` 저장소를 확인합니다.
- 패키지 이름, CSI driver 버전과 커널 계열은 자주 바뀌므로 위 값은 기준일의 예시입니다.

## 공식 출처

이 문서의 주장은 front matter `official_sources`에 기록한 Microsoft Learn 원문과
대조했습니다. 2026-11-10에 각 문서를 전체 조회했습니다.
