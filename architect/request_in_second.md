# 응답속도 최적화를 위한 azure architect 고려사항

> 모든 azure의 제품을 고려할 때 네트워크의 홉이 증가한다는 사실을 고려해야 함

## apim

> apim의 rps(reeuest per second)/tps(transaction per second)는 명확히 알려진 바 없으나   
> standard v2 10 unit 기준 요청량이 증가하면서 apim에서 wait time이 증가(100ms 이상)

**1s 이하의 응답속도 최소화 요구사항 + 7500rps 이상이 있는 경우 apim은 제외하는 아키텍처를 검토**
- 단일 apim(standard v2)에서는 커버가 어려움
- 2025.11.05. 기준 premium v2는 preview로 제안 불가


# 사례
30000rps 이상, 100ms 이하의 latency를 요구
모바일 기기의 특정 앱 사용 이력을 수집하는 패턴을 위한 최적화 전략

## 변경 사항   
APIM latency로 인한 응답 지연 -> AFD의 429 error return.   
->   
App gateway를 max node * 3대를 두고, 앞단의 traffic manager에서 dns level로 load balancing.

<img width="952" height="607" alt="이미지 (5)" src="https://github.com/user-attachments/assets/0c156f38-9fd2-41b5-aa1f-c520ddff6e95" />

## 실패 사례

1. AFD - APIM에서 APIM을 제거하고 AGFC(application gateway for container)
: [AGFC autoscaling](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/scaling-zone-resiliency)

> AGFC는 manual capacity 설정 지원 없음.
> 또한 scale out 기간 동안 트래픽을 전혀 받지 못하는 이슈 확인(2025.11.13)

2. App gw + AKS LB
> Appgw 125 unit으로 최대한 올렸으나 트래픽 처리 안됨
