# **Cosmos DB 연속 쿼리 시 DNS Lookup 병목 최적화 가이드**

## ✅ **문제 상황**

*   Node.js 애플리케이션에서 Cosmos DB(Gateway 모드) 연속 호출 시 **DNS lookup이 반복 발생**.
*   프로파일링에서 확인:
        DNS operation ran using an OS call on a worker thread from Node's internal pool.
        Too many such concurrent operations can exhaust the thread pool and block each other.
*   원인:
    *   Node.js는 기본적으로 DNS 캐싱 없음.
    *   libuv 스레드 풀(기본 4개)이 DNS lookup으로 점유 → 다른 I/O 작업 지연.

***

## ✅ **최적화 전략**

1.  **Node.js 애플리케이션 레벨 DNS 캐싱 적용**
2.  **UV\_THREADPOOL\_SIZE 조정 (증상 완화용)**
3.  **인프라 레벨 DNS 캐싱 (NodeLocal DNSCache, CoreDNS TTL)**

***

## **1. Node.js DNS 캐싱 구현**

### **방법 A: cacheable-lookup 라이브러리**

```bash
npm install cacheable-lookup
```

```javascript
const http = require('http');
const CacheableLookup = require('cacheable-lookup');

const cacheable = new CacheableLookup();
cacheable.install(http);

http.get('http://db-neu-prd-cosmos-northeurope.documents.azure.com', (res) => {
  console.log('Status:', res.statusCode);
});
```

*   TTL 기반 DNS 캐싱 지원.
*   HTTP 클라이언트(`got`, `axios`)와도 연동 가능.

***

### **방법 B: 직접 캐싱 구현**

```javascript
const dns = require('dns');
const cache = new Map();
const TTL = 300000; // 5분

async function cachedLookup(hostname) {
  const now = Date.now();
  if (cache.has(hostname)) {
    const { address, expires } = cache.get(hostname);
    if (expires > now) return address;
  }
  const address = await new Promise((resolve, reject) => {
    dns.lookup(hostname, (err, addr) => err ? reject(err) : resolve(addr));
  });
  cache.set(hostname, { address, expires: now + TTL });
  return address;
}
```

***

## **2. UV\_THREADPOOL\_SIZE 조정**

*   기본값: **4**
*   DNS lookup, 파일 I/O, crypto 작업 모두 공유.
*   조정 방법:
    ```yaml
    env:
      - name: UV_THREADPOOL_SIZE
        value: "64"
    ```
*   권장값:
    *   1코어: 4\~8
    *   4코어 이상: 16\~64
*   **주의**: 너무 크게 설정하면 메모리 사용량 증가 및 컨텍스트 스위칭 비용 발생.

***

## **3. 인프라 레벨 DNS 캐싱**

### **NodeLocal DNSCache (AKS)**

*   Pod에서 DNS 요청을 로컬 캐시로 처리.
*   CoreDNS와 연동.

### **CoreDNS TTL 조정**

```text
cache 30
```

### **Linux systemd-resolved**

*   대부분 최신 Linux에 기본 포함.
*   캐시 확인:
    ```bash
    resolvectl statistics
    ```
*   컨테이너 환경에서는 기본 없음 → NodeLocal DNSCache 권장.

***

## ✅ **비판적 결론**

*   UV\_THREADPOOL\_SIZE 증설은 **증상 완화용**.
*   **근본 해결책**은 DNS 캐싱:
    *   Node.js 레벨 캐싱
    *   NodeLocal DNSCache
*   Cosmos DB SDK 연결 재사용도 병목 완화에 중요.

***

### **추천 적용 순서**

1.  Node.js DNS 캐싱 (`cacheable-lookup` 또는 직접 구현)
2.  UV\_THREADPOOL\_SIZE 조정 (적절한 값)
3.  AKS NodeLocal DNSCache 활성화 + CoreDNS TTL 최적화
