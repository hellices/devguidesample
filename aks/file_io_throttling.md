# AKS Pod File I/O Throttling 분석

## 개요

AKS에서 Pod의 부하 상황을 분석하던 중 file write 지연으로 인한 병목 현상을 발견한 사례입니다.

## 문제 증상

### 1. 응답 속도 급격한 저하

특정 시점부터 응답속도가 현저히 느려지는 현상이 확인되었습니다.
- **정상 상태**: 5ms 이내
- **문제 발생 시**: 1분 이상

1분 지연은 CosmosDB client connection timeout 이후 retry 정책으로 재시도된 것으로 파악됩니다. 그러나 이 지연이 Cosmos query 응답속도는 아니기 때문에 추가적인 분석이 필요했습니다.

<img width="1336" height="390" alt="image" src="https://github.com/user-attachments/assets/55ec4215-4338-4b2d-8614-235510dbdc50" />

### 2. 메모리 증가 추세

부하량이 증가할수록 메모리가 지속적으로 증가하는 추세를 확인했습니다.

### 3. GC 발생 후 메모리 재증가

특정 시점 이후 GC가 발생하나 연이어서 메모리가 다시 full이 되는 현상이 관찰되었습니다.

<img width="1192" height="669" alt="스크린샷 2025-11-05 184653" src="https://github.com/user-attachments/assets/fe0d2b13-156c-48bf-8daa-af51450282bc" />

### 4. File System Async Activity 다수 발견

Trace 정보에서 profile을 확인했을 때 별다른 stack trace가 보이지 않고, 대신 수많은 file system async activity가 확인되었습니다.

<img width="1156" height="741" alt="image" src="https://github.com/user-attachments/assets/556786e8-afbb-4602-a657-298f2fb889a9" />

## 원인 분석

위 증상들을 종합하여 **AKS → NFS write 지연 이슈**로 의심되었습니다.

## 해결 방법

NFS capacity를 증설한 결과:
- ✅ 메모리 안정화
- ✅ 응답속도 정상화

## 결론

File I/O 병목이 애플리케이션 성능에 심각한 영향을 미칠 수 있으며, 특히 NFS 스토리지의 용량과 처리량이 충분한지 확인하는 것이 중요합니다.
