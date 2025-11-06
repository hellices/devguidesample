# AKS NetApp Files 환경에서의 CPU 급증 및 File I/O 대기 이슈

## 개요

AKS 환경에서 NetApp Files를 사용하는 Node.js 애플리케이션의 트래픽 증가 시 CPU 급증과 File I/O 대기 현상을 분석한 사례입니다. 이전 용량 증설로 NFS write 지연 문제를 해결했으나([file_io_throttling.md](./file_io_throttling.md) 참조), 추가적인 병목 현상이 발견되었습니다.

## 환경 구성

- **인프라**: Azure Kubernetes Service (AKS)
- **Pod 수**: 300개
- **컨테이너**: Node.js 애플리케이션
- **스토리지**: NetApp Files (NFS) Persistent Volume

## 문제 증상

### 1. 트래픽 증가 시 CPU 급증

<img width="568" height="251" alt="image" src="https://github.com/user-attachments/assets/7e916a87-7199-4082-be02-19158c255bf6" />

### 2. Network I/O 및 Disk Write 이상 패턴

<img width="1761" height="672" alt="image" src="https://github.com/user-attachments/assets/50805dd4-9b9b-440f-8fc2-e964ff8bfea1" />

### 3. Node의 I/O Wait 발생

<img width="1728" height="615" alt="image" src="https://github.com/user-attachments/assets/52ccc592-f83f-454d-9041-6458fe4fc3bc" />

### 4. Pod 내 File System 대기 급증

<img width="1760" height="1284" alt="image" src="https://github.com/user-attachments/assets/31c9275d-0956-4c32-8f58-bece91714154" />

## 원인 분석

1. **NFS Client Pool 부족**: NFS 클라이언트의 동시 연결 처리 한계
2. **Local Disk Buffer/Cache 동작**: 커널 페이지 캐시로 인한 지연 전파
3. **Pod Resource 제약**: CPU/Memory limits 설정으로 인한 throttling

## 분석 작업

- [ ] NFS CSI Driver 설정 검토 (버전, mount 옵션, connection pool)
- [ ] PV/PVC 설정 검토 (StorageClass, mount 옵션, Access Mode)
- [ ] `nfsstat`, `mountstats`로 NFS 클라이언트 통계 확인
- [ ] Pod Resource Limits 검증 (CPU throttling 확인)

## Datadog 모니터링 메트릭

- `system.io.w_await`: Write I/O 대기 시간 (NFS 병목 감지)
- `kubernetes.cpu.throttled.seconds`: CPU throttling 발생 여부
- `system.cpu.iowait`: I/O 대기로 인한 CPU 대기 시간

## 조치 방안

### 1. NFS Mount 옵션 최적화

StorageClass 설정 ([참고: NetApp Trident](https://docs.netapp.com/us-en/trident/trident-use/ontap-nas.html)):
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: netapp-nfs-optimized
provisioner: csi.trident.netapp.io
parameters:
  backendType: "ontap-nas"
mountOptions:
  - nfsvers=4.1
  - nconnect=4         # 다중 TCP 연결 (300 pod 환경에 권장)
  - rsize=1048576      # 1MB read buffer
  - wsize=1048576      # 1MB write buffer
  - hard
  - timeo=600          # 60초 timeout
  - retrans=2
```

> **nconnect**: Linux kernel 5.3+ 지원. 다중 TCP 연결로 처리량 향상. 300개 pod의 동시 I/O 환경에 적합.

PVC 재생성:
```bash
kubectl get pvc <pvc-name> -o yaml > pvc-backup.yaml
kubectl scale deployment <deployment-name> --replicas=0
kubectl delete pvc <pvc-name>
kubectl apply -f pvc-new.yaml
kubectl scale deployment <deployment-name> --replicas=<original-replicas>
```

### 2. NFS 클라이언트 진단

```bash
# 통계 확인
kubectl exec -it <pod-name> -- nfsstat -c

# RPC 재전송 확인
kubectl exec -it <pod-name> -- nfsstat -rc

# 마운트 옵션 확인
kubectl exec -it <pod-name> -- mount | grep nfs
```

## 참고 자료

- [NetApp Trident 문서](https://docs.netapp.com/us-en/trident/trident-use/ontap-nas.html)
- [NetApp files nfs best practice](https://www.netapp.com/pdf.html?item=/media/10720-tr-4067.pdf)

---
netapp files nfs best practice 중 nconnect 내용 발췌
# Nconnect

A new NFS mount option called **nconnect** is in its nascent stages for use with NFS mounts. The `nconnect` option is only available on newer Linux clients. Be sure to verify with the OS vendor documentation to determine whether the option is supported in your kernel.

The purpose of `nconnect` is to provide multiple transport connections per TCP connection or mount point on a client. This helps increase parallelism and performance for NFS mounts. Details about `nconnect` and how it can increase performance for NFS in Cloud Volumes ONTAP can be found in the blog post **The Real Baseline Performance Story: NetApp Cloud Volumes Service for AWS**.

**ONTAP 9.8 and later** offers official support for the use of `nconnect` with NFS mounts, provided the NFS client also supports it. To use `nconnect`, verify whether your client version provides it and use ONTAP 9.8 or later. ONTAP 9.8 and later supports `nconnect` by default with no option needed.

> **Note**: `nconnect` is not recommended for use with NFSv4.0. NFSv3, NFSv4.1, and NFSv4.2 should work fine with `nconnect`.

***

## Table 15) Nconnect performance results

| Nconnect value | Threads per process | Throughput | Difference |
| -------------- | ------------------- | ---------- | ---------- |
| 1              | 128                 | 1.45GB/s   | -          |
| 2              | 128                 | 2.4GB/s    | +66%       |
| 4              | 128                 | 3.9GB/s    | +169%      |
| 8              | 256                 | 4.07GB/s   | +181%      |

> **Note**: The recommendation for using `nconnect` depends on client OS and application needs. Testing with this new option is highly recommended before deploying in production.

***

## How can I tell nconnect is working?

`nconnect` is designed to allocate more sessions across a single TCP connection. This helps to better distribute NFS workloads and add some parallelism to the connection, which helps the NFS server handle the workloads more efficiently.

In ONTAP, when an NFS mount is established, a **Connection ID (CID)** is created. That CID provides up to 128 concurrent in-flight operations. When that number is exceeded by the client, ONTAP enacts a form of flow control until it can free up some available resources as other operations complete. These pauses usually are only a few microseconds, but over the course of millions of operations, those can add up and create performance issues.

`nconnect` can take the 128 limit and multiply it by the number of `nconnect` sessions on the client, which provides more concurrent operations per CID and can potentially add performance benefits, as seen in Table 15.

Figure 16 illustrates how mounts without nconnect handle concurrent operations and how nconnect works 
to distribute operations to NFS mounts. 
<img width="727" height="474" alt="image" src="https://github.com/user-attachments/assets/15121acb-7456-4df4-b942-fe3d49fbfd76" />

***

### Verify nconnect usage

#### 1. Check active connections

```bash
cluster::> network connections active show -node [nodes] -service nfs* -remote-host [hostname]
```

**Example without nconnect:**

    cluster::> network connections active show -node * -service nfs* -remote-host centos83-perf.ntap.local
    Vserver    Interface              Remote
    Name       Name:Local Port        Host:Port                    Protocol/Service
    ---------- ---------------------- ---------------------------- ----------------
    Node: node1
    DEMO       data1:2049             centos83-perf.ntap.local:1013 TCP/nfs

**Example with nconnect=8:**

    DEMO data1:2049 centos83-perf.ntap.local:669 TCP/nfs
    DEMO data1:2049 centos83-perf.ntap.local:875 TCP/nfs
    DEMO data1:2049 centos83-perf.ntap.local:765 TCP/nfs
    DEMO data1:2049 centos83-perf.ntap.local:750 TCP/nfs
    DEMO data1:2049 centos83-perf.ntap.local:779 TCP/nfs
    DEMO data1:2049 centos83-perf.ntap.local:773 TCP/nfs
    DEMO data1:2049 centos83-perf.ntap.local:809 TCP/nfs
    DEMO data1:2049 centos83-perf.ntap.local:897 TCP/nfs

***

#### 2. Check statistics

```bash
cluster::> set diag
cluster::* > statistics start -object cid
cluster::* > statistics show -object cid -counter alloc_total
```

*   Without nconnect:

<!---->

    alloc_total = 11

*   With nconnect=4:

<!---->

    alloc_total = 16

*   With nconnect=8:

<!---->

    alloc_total = 24



---

다음은 netapp files best practice를 notebooklm을 사용해서 aks에 추천하는 mount 옵션 요청

## best practice in kubernetes

### NFSv4.1 마운트 시 추천 베스트 옵션 (Best Mount Options)

NFSv4.1은 NFSv3와 달리 단일 포트(2049)만 사용하며, 상태 기반(Stateful) 프로토콜입니다. AKS와 같이 높은 동시성 및 컨테이너 환경을 사용하는 경우, 성능과 효율성을 극대화하기 위해 다음과 같은 마운트 옵션들을 고려하는 것이 좋습니다.

#### 1. nconnect 옵션 (병렬 연결)
**`nconnect`**는 NFS 마운트 지점당 여러 개의 TCP 전송 연결을 제공하여 병렬 처리 능력을 높이고 성능을 향상시키는 새로운 NFS 마운트 옵션입니다.

*   **추천 이유:** NFSv4.x 클라이언트의 동시성(Concurrency)은 세션 슬롯(session slots)에 의해 제한되지만, ONTAP은 단일 연결 ID(CID)당 128개의 실행 컨텍스트(exec contexts)만 허용합니다. `nconnect`를 사용하면 여러 개의 CID를 생성하여 이 한계를 우회하고 더 많은 동시 작업을 처리할 수 있습니다. 컨테이너 환경에서는 단일 호스트 IP가 많은 연결을 생성하므로, `nconnect`를 사용하여 워크로드를 분산하는 것이 특히 중요합니다.
*   **설정 예:** `nconnect=8` 또는 `nconnect=16`와 같이 테스트된 값을 사용합니다.
    *   예: `mount -t nfs -o nfsvers=4.1,nconnect=8,hard ...`

#### 2. rsize/wsize (전송 크기)
`rsize`와 `wsize`는 NFS 클라이언트와 서버 간에 전송되는 데이터 블록의 크기를 결정합니다.

*   **추천 설정:** 최신 Linux 클라이언트는 NFS 서버의 최대 전송 크기 값(`-tcp-max-xfer-size`, ONTAP의 경우 최대 1MB)에 따라 자동으로 이 값을 협상합니다. 최상의 성능을 위해 **1MB (1048576)**로 설정하는 것을 고려하십시오.
*   **설정 예:** `rsize=1048576,wsize=1048576`

#### 3. pNFS (Parallel NFS) 활용
pNFS는 NFSv4.1 표준의 일부로, 메타데이터 서버(MDS)와 데이터 서버를 분리하여 데이터 접근 경로를 최적화함으로써 성능상의 이점을 제공합니다.

*   **설정:** 클라이언트가 pNFS를 지원하고 ONTAP에서 NFSv4.1이 활성화되어 있다면 pNFS는 기본적으로 활성화됩니다. 데이터 I/O 성능을 보장하기 위해 pNFS를 사용하는 것이 좋습니다. 마운트 시 특별한 옵션이 필요하지 않지만, 클라이언트에서 pNFS 커널 모듈이 로드되었는지 확인해야 합니다.

#### 4. 기타 권장 옵션

*   **복구 옵션:** **`hard`** 마운트 옵션을 사용하여 NFS 서버가 응답하지 않을 경우 프로세스가 중지하고 서버 복구를 기다리도록 설정하는 것이 비즈니스 크리티컬한 데이터에 권장됩니다.
*   **속성 캐싱 (선택 사항):** 읽기 위주의 워크로드(예: EDA 도구 라이브러리)에서 성능을 높이려면 **`nocto`** 옵션과 함께 **`actimeo=<큰 값>`** (예: 600초)을 사용하여 메타데이터 호출을 줄일 수 있습니다. 하지만 데이터 일관성이 느슨해지므로, 데이터 공유가 적은 환경에서만 사용해야 합니다.

---

### NetApp ONTAP (NFS 서버) 설정 방법

NetApp ONTAP(또는 NetApp Files 서비스) 측에서는 NFSv4.1 마운트가 원활하게 작동하고 성능을 최적화할 수 있도록 다음과 같은 설정을 확인하거나 변경해야 합니다.

#### 1. NFS 버전 및 ACL 활성화 확인

NFSv4.1과 관련된 기능이 SVM(Storage Virtual Machine)에 활성화되어 있는지 확인합니다.

*   NFSv4.1 활성화: NFSv4.1 버전을 사용하고자 하는 경우 해당 버전이 활성화되어 있는지 확인합니다.
*   NFSv4.x ACL 활성화: 세분화된 권한 관리를 위해 NFSv4.x ACL 지원을 활성화합니다 (예: `-v4.1-acl`).

#### 2. ID 도메인 매핑 설정 (가장 중요)

NFSv4.x의 주요 보안 기능은 사용자/그룹 식별자가 문자열(`user@DOMAIN.COM`) 형태로 전달된다는 것입니다. 클라이언트와 서버 간에 이 ID 도메인 문자열이 **정확히 일치**해야 합니다.

*   **ONTAP 서버:** SVM의 `-v4-id-domain` 옵션을 설정합니다.
    *   `cluster::> nfs server modify -vserver <vserver_name> -v4-id-domain <DOMAIN.COM>`
*   **클라이언트 (AKS/Linux):** `/etc/idmapd.conf` 파일에서 ID 도메인 문자열을 서버와 동일하게 설정해야 합니다.
*   **이름 서비스 일관성:** 클라이언트와 서버 모두 동일한 중앙 집중식 이름 서비스(LDAP 또는 NIS)를 사용하여 사용자 및 그룹 정보를 조회하도록 구성하는 것이 **최고의 방법**입니다. 이는 이름, UID, GID의 일관성을 보장합니다.
    *   *참고:* 만약 ID 매핑 인프라가 복잡하고 보안보다 NFSv3와 유사한 동작을 원한다면, ONTAP에서 `-v4-numeric-ids` 옵션을 활성화하고 클라이언트에서 ID 매핑을 비활성화하여 숫자 ID(Numeric ID)를 사용하도록 할 수 있습니다.

#### 3. 최대 전송 크기 설정

ONTAP 서버에서 TCP 전송 크기(wsize/rsize의 상한선)를 설정하여 클라이언트가 더 큰 블록 크기로 협상할 수 있도록 합니다.

*   **설정:** `-tcp-max-xfer-size` 옵션을 확인합니다. 기본값은 64K이지만, 성능을 위해 최대값인 **1MB**로 설정하는 것이 좋습니다.
    *   `cluster::> nfs server modify -vserver <vserver_name> -tcp-max-xfer-size 1048576`

#### 4. 내보내기 정책 (Export Policy) 설정

NFSv4.1을 사용하려면 볼륨에 적용된 내보내기 정책 규칙이 `nfs4` 프로토콜을 허용하도록 설정되어 있어야 합니다.

*   **프로토콜 설정:** 내보내기 정책 규칙에서 `Access Protocol`을 `nfs4` 또는 `nfs`(NFSv3 및 NFSv4.x 모두 포함)로 설정합니다.

### 요약된 NFSv4.1 마운트 명령 (Linux 클라이언트 기준)

NetApp 서버 IP가 `<NFS_SERVER_IP>`이고 내보낸 경로가 `/volumepath`라고 가정할 때, AKS 환경의 리눅스 클라이언트에서 일반적으로 권장되는 마운트 옵션은 다음과 같습니다.

```bash
# nconnect를 사용하여 병렬 처리, 최대 rsize/wsize, 하드 마운트 사용
sudo mount -t nfs -o nfsvers=4.1,nconnect=8,rsize=1048576,wsize=1048576,hard,proto=tcp <NFS_SERVER_IP>:/volumepath /mnt/netapp
```

**주의 사항:**

*   **pNFS:** 위 마운트 명령에 pNFS 관련 옵션은 포함되어 있지 않습니다. NFSv4.1이 활성화되어 있고 클라이언트가 pNFS를 지원하는 경우 자동으로 pNFS 기능이 활용됩니다.
*   **`nconnect` 유의:** `nconnect` 사용 시 단일 마운트가 더 많은 리소스를 사용하므로, 클러스터 노드당 연결 ID 제한을 초과하지 않도록 연결을 여러 데이터 LIF에 분산하도록 설계해야 합니다.


---


### AKS CSI 드라이버 설정의 논리적 위치 (소스 외 정보)

Kubernetes 환경에서 영구 볼륨(Persistent Volume)을 마운트할 때 클라이언트 측 옵션은 일반적으로 두 가지 주요 위치 중 하나에 지정됩니다.

1.  **StorageClass (저장소 클래스):** 대부분의 클러스터에서 영구 볼륨 청구(Persistent Volume Claim, PVC)를 생성할 때 동적으로 볼륨을 프로비저닝하기 위해 사용됩니다. CSI 드라이버는 StorageClass에 정의된 `mountOptions`를 사용하여 실제 마운트 명령에 반영합니다.
2.  **PersistentVolume (PV):** PV를 수동으로 생성하는 경우, PV 개체의 `mountOptions` 필드에 직접 지정됩니다.

이러한 설정은 일반적으로 YAML 형식의 `mountOptions` 필드 내에서 문자열 배열로 추가됩니다.

### NetApp NFSv4.1 마운트 옵션 및 적용 (소스 기반)

이러한 `mountOptions` 필드에 포함되어야 하는, 제공된 소스에서 권장하는 주요 NFSv4.1 옵션은 다음과 같습니다.

#### 1. nconnect (병렬 연결)

*   **설정 이유:** NFS 마운트 지점당 여러 개의 TCP 연결을 생성하여 동시성(concurrency)을 높이고 성능을 향상시킵니다. 컨테이너 환경처럼 단일 호스트 IP에서 많은 연결을 생성하는 경우 워크로드 분산에 중요합니다.
*   **권장 값:** `nconnect=8` 또는 `nconnect=16`와 같이 테스트된 값을 사용합니다.
    *   **주의 사항:** `nconnect`를 사용하면 단일 마운트가 더 많은 Connection ID (CID)를 사용하므로, 노드당 연결 ID 제한을 초과하지 않도록 주의해야 합니다. 이 옵션은 **NFSv4.1** 및 NFSv3에서 사용이 권장되지만, NFSv4.0에서는 권장되지 않습니다.

#### 2. rsize 및 wsize (전송 블록 크기)

*   **설정 이유:** 클라이언트와 서버 간의 데이터 전송 크기를 최적화합니다. ONTAP은 최대 1MB (1,048,576 바이트)의 전송 크기를 지원합니다.
*   **권장 값:** 최상의 성능을 위해 **1048576**로 설정하는 것을 고려하십시오.
    *   예: `rsize=1048576`, `wsize=1048576`.
    *   *참고:* 이 값을 변경하면 새 마운트에만 영향을 미치므로, 변경 시 기존 마운트는 언마운트 후 재마운트해야 합니다.

#### 3. 복구 및 프로토콜 옵션

*   **하드 마운트 (`hard`):** 비즈니스 크리티컬한 워크로드의 경우, NFS 서버가 응답하지 않을 때 프로세스가 중지되고 서버 복구를 기다리도록 `hard` 마운트 옵션을 사용하는 것이 권장됩니다.
*   **TCP 프로토콜 (`proto=tcp` 또는 `tcp`):** NFSv4.x는 기본적으로 TCP만 사용하지만, 명시적으로 `tcp`를 지정하면 NFSv3에서 MOUNT/Portmap 프로토콜의 UDP 호출로 인해 발생하는 추가적인 연결 ID(Connection ID) 생성을 줄이는 데 도움이 되므로, 일반적으로 컨테이너 환경에서 권장되는 모범 사례입니다.

#### 4. NFSv4.1 ID 도메인 설정 (매우 중요)

AKS CSI 드라이버 환경에서도 NFSv4.1의 핵심인 **ID 도메인 매핑**의 일관성이 보장되어야 합니다.

*   NFSv4.x는 사용자 식별자(예: `user@DOMAIN.COM`)를 문자열 형태로 전달합니다.
*   클라이언트(AKS 노드)와 서버(NetApp Files SVM)의 ID 도메인 문자열이 **정확히 일치**해야 합니다. 일치하지 않으면 사용자가 일반적으로 'nobody'로 매핑되어 액세스 문제가 발생합니다.
*   AKS 노드에 대한 이름 서비스 구성(ID 매핑)은 AKS 환경 외부에서 설정되어야 하지만, 이것이 ONTAP 측의 `-v4-id-domain` 값과 일치하는지 확인하는 것이 필수적입니다.

### 예시 마운트 옵션 목록 (StorageClass 또는 PV에 포함될 내용)

위에 나열된 권장 사항을 바탕으로, CSI 드라이버의 `mountOptions`에 적용될 수 있는 옵션 목록은 다음과 같습니다.

```yaml
mountOptions:
  - hard
  - nfsvers=4.1
  - proto=tcp
  - rsize=1048576
  - wsize=1048576
  - nconnect=8  # 또는 nconnect=16 (테스트 기반)
```

이 옵션들을 YAML 배열 형태로 구성하여 CSI 드라이버 설정에 전달해야 합니다. CSI 드라이버는 이 옵션들을 가져와서 AKS 노드에 있는 볼륨을 마운트할 때 사용하게 됩니다.
