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

3. **비동기 처리 한계**
   - Async pool의 작업 큐가 포화 상태에 도달
   - Node.js 이벤트 루프 블로킹 가능성

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

- [ ] **Node.js 애플리케이션 코드 리뷰**
  - Async pool 크기 및 queue 처리 방식 검증
  - File write 패턴 분석 (버퍼링, batch write 가능 여부)
  - `fs.writeFile` vs `fs.createWriteStream` 비교

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

### 🔧 즉시 적용 가능한 개선

#### 1. NFS Mount 옵션 최적화

**현재 설정 확인**:
```bash
kubectl exec -it <pod-name> -- mount | grep nfs
```

**권장 옵션**:
```yaml
mountOptions:
  - nfsvers=4.1
  - rsize=1048576
  - wsize=1048576
  - hard
  - timeo=600
  - retrans=2
  - noresvport
```

#### 2. NetApp Files CSI Driver 업데이트

최신 버전으로 업그레이드 및 성능 관련 기능 활성화:
```bash
helm upgrade netapp-trident netapp-trident/trident-operator \
  --namespace trident \
  --set enableACP=true
```

#### 3. Node.js 애플리케이션 개선

**버퍼링 전략 적용**:
```javascript
const { createWriteStream } = require('fs');
const { pipeline } = require('stream/promises');

// ✅ Stream 기반 버퍼링 쓰기
const writeStream = createWriteStream('/mnt/nfs/data.log', {
  flags: 'a',
  highWaterMark: 64 * 1024 // 64KB 버퍼
});

async function writeData(data) {
  return new Promise((resolve, reject) => {
    writeStream.write(data + '\n', (err) => {
      if (err) reject(err);
      else resolve();
    });
  });
}
```

**Batch Write 적용**:
```javascript
const writeQueue = [];
const BATCH_SIZE = 100;
const FLUSH_INTERVAL = 5000; // 5초

setInterval(() => {
  if (writeQueue.length > 0) {
    const batch = writeQueue.splice(0, BATCH_SIZE);
    fs.appendFile('/mnt/nfs/data.log', batch.join('\n') + '\n');
  }
}, FLUSH_INTERVAL);
```

### 🚀 중장기 개선 방안

#### 1. NetApp Files 성능 티어 업그레이드

- **Standard** → **Premium** 이동 고려
- 처리량 한계 증대 (최대 4.5GiB/s)
- 참고: [Azure NetApp Files 성능 벤치마크](https://learn.microsoft.com/azure/azure-netapp-files/performance-benchmarks-linux)

#### 2. Write Cache 레이어 추가

로컬 SSD를 캐시로 활용:
```yaml
volumes:
  - name: local-cache
    emptyDir:
      medium: Memory
      sizeLimit: 1Gi
```

#### 3. 아키텍처 개선

- **대안 1**: 메시지 큐 도입 (Azure Service Bus, RabbitMQ)
- **대안 2**: 시계열 DB 사용 (Azure Data Explorer, InfluxDB)
- **대안 3**: Blob Storage 직접 쓰기 (Azure Blob SDK)

***

## 참고 자료

- [Azure NetApp Files 성능 고려사항](https://learn.microsoft.com/azure/azure-netapp-files/performance-considerations-smb)
- [NFS CSI Driver for Kubernetes](https://github.com/kubernetes-csi/csi-driver-nfs)
- [Node.js Stream API](https://nodejs.org/api/stream.html)
- [Linux NFS Performance Tuning](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/managing_file_systems/mounting-nfs-shares_managing-file-systems#nfs-performance-tuning_mounting-nfs-shares)

***

## 결론

NetApp Files 용량 증설 후에도 CPU 급증과 I/O 대기 현상이 지속되는 것은 **NFS 클라이언트 설정**, **애플리케이션 I/O 패턴**, **NetApp Files 성능 티어** 등 복합적인 요인에 기인합니다. 단계별 분석과 최적화를 통해 근본 원인을 파악하고 개선해야 합니다.
