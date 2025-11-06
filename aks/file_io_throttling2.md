# AKS NetApp Files 환경에서의 CPU 급증 및 File I/O 대기 이슈

## 개요

AKS 환경에서 NetApp Files를 사용하는 Node.js 애플리케이션의 트래픽 증가 시 CPU 급증과 File I/O 대기 현상을 분석한 사례입니다. 이전 용량 증설로 NFS write 지연 문제를 해결했으나([file_io_throttling.md](./file_io_throttling.md) 참조), 추가적인 병목 현상이 발견되었습니다.

***

## 환경 구성

- **인프라**: Azure Kubernetes Service (AKS)
- **Pod 수**: 300개
- **컨테이너**: Node.js 애플리케이션
- **스토리지**: NetApp Files (NFS) Persistent Volume
- **애플리케이션 동작**:
  - HTTP 요청 수신
  - Async pool로 파일 쓰기 작업 위임
  - 즉시 `200 OK` 응답 반환 (비동기 처리)

***

## 문제 증상

### 1. 트래픽 증가 시 CPU 급증

트래픽이 증가하는 상황에서 Pod의 CPU 사용률이 급격히 상승하는 현상 발생.

<img width="568" height="251" alt="image" src="https://github.com/user-attachments/assets/7e916a87-7199-4082-be02-19158c255bf6" />

### 2. Network I/O 및 Disk Write 이상 패턴

- NFS 서비스 사용 중임에도 불구하고 **local disk write** 활동 확인
- Network I/O 패턴에서 특이점 관찰

<img width="1761" height="672" alt="image" src="https://github.com/user-attachments/assets/50805dd4-9b9b-440f-8fc2-e964ff8bfea1" />

### 3. Node의 I/O Wait 발생

해당 Node의 `system.io.w_await` 메트릭 확인 결과, 특정 시점에 write 대기 시간 급증 확인.

<img width="1728" height="615" alt="image" src="https://github.com/user-attachments/assets/52ccc592-f83f-454d-9041-6458fe4fc3bc" />

### 4. Pod 내 File System 대기 급증

프로파일링 결과, Pod 내부에서 **파일 시스템 대기**가 급격히 증가하는 것으로 확인됨.

<img width="1760" height="1284" alt="image" src="https://github.com/user-attachments/assets/31c9275d-0956-4c32-8f58-bece91714154" />

***

## 원인 분석

### 주요 의심 지점

1. **NFS Client Pool 부족**
   - NFS 클라이언트의 동시 연결 처리 한계로 인한 병목 가능성
   - NetApp Files CSI Driver 설정의 최적화 필요

2. **Local Disk Buffer/Cache 동작**
   - NFS 마운트 환경에서 커널의 페이지 캐시 동작으로 인한 local disk 활동
   - Write-back cache로 인한 지연 전파

3. **Pod Resource 제약**
   - CPU/Memory limits 설정으로 인한 throttling
   - NFS mount 옵션 미최적화

***

## 분석 작업 목록

### ✅ 우선 순위 높음

- [ ] **NFS CSI Driver 설정 검토**
  - 현재 설치된 CSI Driver 버전 확인
  - Mount 옵션 분석 (`nfsvers`, `rsize`, `wsize`, `hard/soft`, `timeo`, `retrans`)
  - Connection pool 관련 파라미터 확인

- [ ] **NetApp Files 서비스 티어 및 성능 검증**
  - 현재 할당된 처리량(throughput) 한계 확인
  - IOPS 및 latency 메트릭 분석
  - Premium vs Standard 티어 비교

- [ ] **PV/PVC 설정 검토**
  - 현재 StorageClass 확인
  - Mount 옵션 검증
  - Access Mode 및 Reclaim Policy 확인

### ⚠️ 우선 순위 중간

- [ ] **커널 레벨 NFS 통계 수집**
  - `nfsstat` 명령어로 NFS 클라이언트 통계 확인
  - `mountstats` 분석 (RPC 성능, 재전송 횟수)

- [ ] **Pod Resource Limits 검증**
  - CPU/Memory limits 적절성 검토
  - Throttling 발생 여부 확인 (`kubectl top`, `metrics-server`)

- [ ] **Node 레벨 성능 분석**
  - `iostat`, `vmstat` 메트릭 수집
  - 다른 Pod들의 I/O 영향도 분석

### 📊 모니터링 강화

- [ ] **메트릭 대시보드 구성**
  - NFS 성능 메트릭 (latency, throughput, errors)
  - Pod 레벨 I/O wait 시간
  - Node 레벨 disk I/O 통계

***

## 조치 방안

> **참고**: 애플리케이션 코드 수정 권한이 없는 경우를 가정하여, 인프라 레벨에서 적용 가능한 방안을 중심으로 작성되었습니다.

### 🔧 즉시 적용 가능한 개선

#### 1. NFS Mount 옵션 최적화

**현재 설정 확인**:
```bash
# Pod 내에서 현재 마운트 옵션 확인
kubectl exec -it <pod-name> -- mount | grep nfs

# 또는 특정 마운트 상세 정보
kubectl exec -it <pod-name> -- cat /proc/mounts | grep nfs
```

**PV/PVC에서 Mount 옵션 추가**:

StorageClass 수정 ([Kubernetes StorageClass 공식 문서](https://kubernetes.io/docs/concepts/storage/storage-classes/)):
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
  - rsize=1048576      # 1MB read buffer
  - wsize=1048576      # 1MB write buffer
  - hard               # hard mount (재시도)
  - timeo=600          # 60초 timeout
  - retrans=2          # 재전송 2회
  - noresvport         # 비특권 포트 사용
  - actimeo=30         # attribute cache 30초
```

> **참고**: 
> - [Kubernetes StorageClass mountOptions](https://kubernetes.io/docs/concepts/storage/storage-classes/#mount-options)
> - [NetApp Trident Backend Configuration](https://docs.netapp.com/us-en/trident/trident-use/ontap-nas.html)
> - [Linux NFS Mount Options](https://man7.org/linux/man-pages/man5/nfs.5.html)

기존 PVC 재생성 (데이터 백업 필수) ([Kubernetes PVC 공식 문서](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)):
```bash
# 1. 현재 PVC 정보 백업
kubectl get pvc <pvc-name> -o yaml > pvc-backup.yaml

# 2. Pod 중지
kubectl scale deployment <deployment-name> --replicas=0

# 3. PVC 삭제 및 재생성 (새 StorageClass 사용)
kubectl delete pvc <pvc-name>
kubectl apply -f pvc-new.yaml

# 4. Pod 재시작
kubectl scale deployment <deployment-name> --replicas=<원래값>
```

#### 2. NFS 통계 및 성능 분석

**Pod 내에서 NFS 통계 확인** ([Kubernetes Debug 공식 문서](https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/)):
```bash
# NFS 클라이언트 통계
kubectl exec -it <pod-name> -- nfsstat -c

# NFS 마운트별 상세 통계
kubectl exec -it <pod-name> -- cat /proc/self/mountstats | grep -A 50 "device.*nfs"

# RPC 통계 확인 (재전송, timeout 등)
kubectl exec -it <pod-name> -- nfsstat -rc
```

**Node에서 I/O 대기 분석** ([Kubernetes Debug Node 공식 문서](https://kubernetes.io/docs/tasks/debug/debug-cluster/kubectl-node-debug/)):
```bash
# Node에 접속 (privileged)
kubectl debug node/<node-name> -it --image=ubuntu

# iostat 설치 및 실행
apt-get update && apt-get install -y sysstat
iostat -x 5

# NFS 관련 커널 메시지
dmesg | grep -i nfs
```

#### 3. Pod Resource Limits 조정

CPU throttling 완화 ([Kubernetes Resource Management 공식 문서](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)):
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-pod
spec:
  containers:
  - name: nodejs-app
    resources:
      requests:
        cpu: "1000m"
        memory: "2Gi"
      limits:
        cpu: "2000m"      # 더 높은 burst 허용
        memory: "4Gi"
```

> **참고**: [AKS의 컨테이너 리소스 관리](https://learn.microsoft.com/azure/aks/concepts-clusters-workloads#resource-reservations)

#### 4. NetApp Files CSI Driver 업데이트

최신 버전으로 업그레이드 ([NetApp Trident 설치 가이드](https://docs.netapp.com/us-en/trident/trident-get-started/kubernetes-deploy.html)):
```bash
# 현재 Trident 버전 확인
kubectl get tridentversions -n trident

# Helm으로 업그레이드
helm repo update
helm upgrade netapp-trident netapp-trident/trident-operator \
  --namespace trident \
  --set enableACP=true

# 또는 kubectl로 설치
kubectl apply -f https://github.com/NetApp/trident/releases/download/v24.02.0/bundle_pre_1_25.yaml
```

> **참고**: 
> - [NetApp Trident Operator 설치](https://docs.netapp.com/us-en/trident/trident-get-started/kubernetes-deploy-operator.html)
> - [AKS와 NetApp Trident 통합](https://learn.microsoft.com/azure/aks/azure-netapp-files)

### 🚀 중장기 개선 방안

#### 1. NetApp Files 성능 티어 업그레이드

Azure Portal에서 성능 티어 변경 ([Azure NetApp Files 서비스 수준](https://learn.microsoft.com/azure/azure-netapp-files/azure-netapp-files-service-levels)):
```bash
# Azure CLI로 확인
az netappfiles volume show \
  --resource-group <rg-name> \
  --account-name <account-name> \
  --pool-name <pool-name> \
  --name <volume-name> \
  --query "serviceLevel"

# Standard → Premium 업그레이드
az netappfiles volume update \
  --resource-group <rg-name> \
  --account-name <account-name> \
  --pool-name <pool-name> \
  --name <volume-name> \
  --service-level Premium
```

> **참고**: 
> - [Azure NetApp Files 성능 벤치마크](https://learn.microsoft.com/azure/azure-netapp-files/performance-benchmarks-linux)
> - [Azure NetApp Files 성능 고려 사항](https://learn.microsoft.com/azure/azure-netapp-files/azure-netapp-files-performance-considerations)
> - [Azure CLI netappfiles 명령](https://learn.microsoft.com/cli/azure/netappfiles/volume)

#### 2. Local Cache 레이어 추가

임시 로컬 볼륨을 write buffer로 활용 ([Kubernetes Volumes 공식 문서](https://kubernetes.io/docs/concepts/storage/volumes/#emptydir)):
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-pod
spec:
  containers:
  - name: nodejs-app
    volumeMounts:
    - name: nfs-volume
      mountPath: /mnt/nfs
    - name: local-cache
      mountPath: /mnt/cache     # 임시 버퍼
  volumes:
  - name: nfs-volume
    persistentVolumeClaim:
      claimName: netapp-pvc
  - name: local-cache
    emptyDir:
      medium: Memory            # 메모리 기반 (빠름)
      sizeLimit: 1Gi
```

> **참고**: 
> - [Kubernetes emptyDir 볼륨](https://kubernetes.io/docs/concepts/storage/volumes/#emptydir)
> - [AKS 임시 볼륨](https://learn.microsoft.com/azure/aks/concepts-storage#ephemeral-volumes)

**주의**: 애플리케이션이 `/mnt/cache`를 활용하도록 설정 필요 (개발팀 협업)

#### 3. 아키텍처 개선 (개발팀 협업 필요)

NFS 의존도를 낮추는 대안:
- **대안 1**: Azure Service Bus / RabbitMQ로 비동기 처리
  - [Azure Service Bus](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-messaging-overview)
- **대안 2**: Azure Blob Storage 직접 쓰기
  - [Azure Blob Storage](https://learn.microsoft.com/azure/storage/blobs/storage-blobs-introduction)
- **대안 3**: 시계열 DB (Azure Data Explorer, InfluxDB)
  - [Azure Data Explorer](https://learn.microsoft.com/azure/data-explorer/data-explorer-overview)

### 📋 진단 체크리스트

문제 해결 전 다음 사항을 확인 ([Kubernetes Troubleshooting](https://kubernetes.io/docs/tasks/debug/)):

```bash
# 1. 현재 mount 옵션 확인
kubectl exec -it <pod-name> -- mount | grep nfs

# 2. NFS 에러 확인
kubectl exec -it <pod-name> -- dmesg | grep -i nfs

# 3. Pod CPU throttling 확인
kubectl describe pod <pod-name> | grep -i throttl

# 4. NetApp Files 메트릭 확인 (Azure Portal)
# - Throughput (MB/s)
# - IOPS
# - Latency (ms)

# 5. StorageClass 확인
kubectl get storageclass -o yaml

# 6. PV 상태 확인
kubectl get pv -o wide
```

> **참고**: 
> - [AKS 문제 해결](https://learn.microsoft.com/azure/aks/troubleshooting)
> - [Kubernetes 디버깅 가이드](https://kubernetes.io/docs/tasks/debug/debug-application/)

***

## 참고 자료

### Azure 공식 문서
- [Azure NetApp Files 개요](https://learn.microsoft.com/azure/azure-netapp-files/azure-netapp-files-introduction)
- [Azure NetApp Files 성능 고려사항](https://learn.microsoft.com/azure/azure-netapp-files/azure-netapp-files-performance-considerations)
- [Azure NetApp Files 성능 벤치마크](https://learn.microsoft.com/azure/azure-netapp-files/performance-benchmarks-linux)
- [AKS에서 Azure NetApp Files 사용](https://learn.microsoft.com/azure/aks/azure-netapp-files)
- [AKS 스토리지 개념](https://learn.microsoft.com/azure/aks/concepts-storage)
- [AKS 문제 해결](https://learn.microsoft.com/azure/aks/troubleshooting)

### Kubernetes 공식 문서
- [Kubernetes Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- [Kubernetes StorageClass](https://kubernetes.io/docs/concepts/storage/storage-classes/)
- [Kubernetes Resource Management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
- [Kubernetes Debugging](https://kubernetes.io/docs/tasks/debug/)

### NetApp 공식 문서
- [NetApp Trident Documentation](https://docs.netapp.com/us-en/trident/index.html)
- [NetApp Trident Backend Configuration](https://docs.netapp.com/us-en/trident/trident-use/ontap-nas.html)
- [NetApp Trident 설치 가이드](https://docs.netapp.com/us-en/trident/trident-get-started/kubernetes-deploy.html)

### 기타 참고 자료
- [NFS CSI Driver for Kubernetes](https://github.com/kubernetes-csi/csi-driver-nfs)
- [Linux NFS Mount Options](https://man7.org/linux/man-pages/man5/nfs.5.html)
- [Linux NFS Performance Tuning (Red Hat)](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/managing_file_systems/mounting-nfs-shares_managing-file-systems#nfs-performance-tuning_mounting-nfs-shares)

***

## 결론

NetApp Files 용량 증설 후에도 CPU 급증과 I/O 대기 현상이 지속되는 것은 **NFS 클라이언트 설정**, **NFS mount 옵션**, **NetApp Files 성능 티어** 등 인프라 레벨의 복합적인 요인에 기인합니다. 

애플리케이션 코드 수정 없이 인프라 레벨에서 개선할 수 있는 방안:
1. **NFS mount 옵션 최적화** (rsize/wsize 증가, timeout 조정)
2. **NetApp Files 성능 티어 업그레이드** (Standard → Premium)
3. **Pod resource limits 조정** (CPU throttling 완화)
4. **CSI Driver 업데이트** (최신 성능 개선 적용)

추가적인 성능 개선이 필요한 경우 애플리케이션 팀과 협력하여 I/O 패턴 최적화를 검토할 수 있습니다.
