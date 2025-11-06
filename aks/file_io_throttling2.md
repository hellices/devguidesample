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

