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

### 2. Pod Resource Limits 조정

```yaml
resources:
  requests:
    cpu: "1000m"
    memory: "2Gi"
  limits:
    cpu: "2000m"
    memory: "4Gi"
```

### 3. NFS 클라이언트 진단

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
- [Azure NetApp Files 성능](https://learn.microsoft.com/azure/azure-netapp-files/azure-netapp-files-performance-considerations)
- [Kubernetes StorageClass](https://kubernetes.io/docs/concepts/storage/storage-classes/)

## 결론

**핵심 조치사항**:
1. NFS mount 옵션 최적화 (nconnect=4, rsize/wsize 1MB)
2. Pod CPU limits 증가 (throttling 완화)
3. Datadog에서 `system.io.w_await`, `kubernetes.cpu.throttled.seconds` 모니터링
