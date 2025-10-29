# Node.js 서버 CPU 오버헤드 분석 및 개선 방안

## **문제 상황**

Node.js 서버를 Kubernetes Pod로 배포한 후 **CPU 사용량 급증** 현상이 발생.  
분석 결과, **신규 코드에서 파일 읽기 및 JSON 처리 과정**이 병목 요인으로 확인됨.

***

## **신규 코드 (문제 발생 부분)**

```javascript
const jsonTxt = fs.readFileSync(transFilePath, 'utf-8');
const transFile = JSON.parse(jsonTxt);
```

*   **특징**
    *   매 요청마다 `fs.readFileSync()`로 파일을 동기적으로 읽음
    *   이후 `JSON.parse()`로 매번 파싱 수행
*   **문제점**
    *   **동기 I/O** → 이벤트 루프 블로킹
    *   **JSON 파싱 반복** → CPU 부하 증가
    *   Pod 내 다중 요청 시 병목 심화

***

## **이전 코드 (캐싱 처리)**

```javascript
const transFile = require(ASSET_PATH + '/' + fileName);
```

*   **특징**
    *   `require()`는 Node.js 모듈 캐싱 메커니즘 활용
    *   최초 로드 후 메모리에서 재사용 → **I/O 및 파싱 비용 없음**
*   **장점**
    *   요청당 파일 읽기 없음
    *   CPU 사용량 안정적

***

## **부하 발생 요인**

1.  **파일 I/O**
    *   `fs.readFileSync()`는 블로킹 방식 → 요청 처리 지연
2.  **JSON 파싱**
    *   매 요청마다 `JSON.parse()` 실행 → CPU 사용량 증가
3.  **다중 요청 환경**
    *   Pod 내 동시 요청 시 병목 심각

***

## **개선 방안**

### ✅ **1. 캐싱 전략 적용**

*   **방법**
    *   애플리케이션 시작 시 모든 언어 파일을 메모리에 로드
    *   요청 시 캐싱된 객체에서 조회
*   **예시**
    ```javascript
    const fs = require('fs');
    const path = require('path');
    
    const ASSET_PATH = path.join(__dirname, 'assets');
    const cache = {};
    
    // ✅ 서버 시작 시 모든 파일 비동기 로딩 + JSON 파싱
    async function preloadFiles() {
        const files = await fs.promises.readdir(ASSET_PATH);
        for (const file of files) {
            if (file.endsWith('.json')) {
                const data = await fs.promises.readFile(path.join(ASSET_PATH, file), 'utf-8');
                cache[file] = JSON.parse(data);
            }
        }
        console.log('Files preloaded:', Object.keys(cache));
    }
    
    // ✅ 요청 처리 함수
    function getJsonFromString(code, key) {
        const fileName = Object.keys(cache).find(file => file.includes(code)) || '.json';
        const transJson = cache[fileName] || cache['.json'];
        return transJson[key] || key;
    }
    
    // ✅ 서버 시작 시 preloadFiles() 호출
    preloadFiles().catch(err => console.error('Preload error:', err));
    ```
***

### 참고

*   <https://nodejs.org/api/modules.html#modules_caching>

***
