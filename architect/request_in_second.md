# 응답속도 최적화를 위한 azure architect 고려사항

> 모든 azure의 제품을 고려할 때 네트워크의 홉이 증가한다는 사실을 고려해야 함

## apim

> apim의 rps(reeuest per second)/tps(transaction per second)는 명확히 알려진 바 없으나   
> standard v2 10 unit 기준 요청량이 증가하면서 apim에서 wait time이 증가(100ms 이상)

**1s 이하의 응답속도 최소화 요구사항 + 7500rps 이상이 있는 경우 apim은 제외하는 아키텍처를 검토**
- 단일 apim(standard v2)에서는 커버가 어려움
- 2025.11.05. 기준 premium v2는 preview로 제안 불가


