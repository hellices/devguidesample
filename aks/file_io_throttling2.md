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

### 📊 Datadog 모니터링 중점 메트릭

다음 Datadog 메트릭을 집중 모니터링:

- **NFS 클라이언트 성능**:
  - `system.io.w_await`: Write I/O 대기 시간 (급증 시 NFS 병목)
  - `system.io.r_await`: Read I/O 대기 시간
  - `system.io.util`: I/O 디바이스 사용률

- **Pod/Container 레벨**:
  - `kubernetes.cpu.usage.total`: CPU 사용률 (급증 패턴)
  - `kubernetes.cpu.throttled.seconds`: CPU throttling 발생 여부
  - `kubernetes.filesystem.usage`: 파일시스템 사용률

- **프로세스 상태**:
  - `system.cpu.iowait`: I/O 대기로 인한 CPU 대기 시간
  - Process state가 'D' (uninterruptible sleep) 상태인 프로세스 수

***

## 조치 방안

> **참고**: 애플리케이션 코드 수정 권한이 없는 경우를 가정하여, 인프라 레벨에서 적용 가능한 방안을 중심으로 작성되었습니다.

### 🔧 핵심 개선 방안

#### 1. NFS Mount 옵션 최적화

**StorageClass 수정** ([Kubernetes 공식 문서](https://kubernetes.io/docs/concepts/storage/storage-classes/)):
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
  - hard
  - timeo=600          # 600 deciseconds (60초) timeout
  - retrans=2
  - noresvport
```

> **참고**: [NetApp Trident Backend Configuration](https://docs.netapp.com/us-en/trident/trident-use/ontap-nas.html)

**PVC 재생성 절차**:
```bash
kubectl get pvc <pvc-name> -o yaml > pvc-backup.yaml
kubectl scale deployment <deployment-name> --replicas=0
kubectl delete pvc <pvc-name>
kubectl apply -f pvc-new.yaml  # 새 StorageClass 사용
kubectl scale deployment <deployment-name> --replicas=<original-replicas>
```

#### 2. Pod Resource Limits 조정

CPU throttling 완화 ([Kubernetes 공식 문서](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)):
```yaml
resources:
  requests:
    cpu: "1000m"
    memory: "2Gi"
  limits:
    cpu: "2000m"      # burst 허용
    memory: "4Gi"
```

#### 3. NFS 클라이언트 통계 확인

```bash
# NFS 클라이언트 통계
kubectl exec -it <pod-name> -- nfsstat -c

# RPC 재전송 확인
kubectl exec -it <pod-name> -- nfsstat -rc

# 마운트 통계
kubectl exec -it <pod-name> -- cat /proc/self/mountstats | grep -A 20 "device.*nfs"
```

### 📋 진단 체크리스트

```bash
# 1. 현재 mount 옵션 확인
kubectl exec -it <pod-name> -- mount | grep nfs

# 2. CPU throttling 확인
kubectl describe pod <pod-name> | grep -i throttl

# 3. StorageClass 확인
kubectl get storageclass <sc-name> -o yaml

# 4. NFS 에러 확인
kubectl exec -it <pod-name> -- dmesg | grep -i nfs
```

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

NetApp Files 용량 증설 이후에도 CPU 급증과 I/O 대기가 지속되는 경우, **NFS 클라이언트 설정**과 **Pod resource limits** 조정으로 개선 가능합니다.

**핵심 조치사항**:
1. NFS mount 옵션 최적화 (rsize/wsize 1MB, timeo 조정)
2. Pod CPU limits 증가 (throttling 완화)
3. Datadog에서 `system.io.w_await`, `kubernetes.cpu.throttled.seconds` 모니터링
