---
title: HTTP/3 개요와 Azure L7 지원 현황
description: HTTP/3의 특징, Azure 주요 L7 서비스의 공개 지원 정보, 실제 AKS·AGFC 프로토콜 점검 결과를 구분해 정리합니다.
document_type: research
services:
  - azure-application-gateway-for-containers
  - azure-application-gateway
  - azure-front-door
  - azure-api-management
  - azure-kubernetes-service
technologies:
  - kubernetes
  - docker
  - go
tags:
  - evaluate
  - optimize
  - networking
status: current
verification_status: needs-review
sources_checked_at: 2026-09-15
official_sources:
  - title: "RFC 9114: HTTP/3"
    url: https://www.rfc-editor.org/rfc/rfc9114
  - title: HTTP/3 support in Azure Application Gateway - Preview
    url: https://learn.microsoft.com/azure/application-gateway/http3-quic-support
  - title: What is Application Gateway for Containers?
    url: https://learn.microsoft.com/azure/application-gateway/for-containers/overview
  - title: Application Gateway for Containers components
    url: https://learn.microsoft.com/azure/application-gateway/for-containers/application-gateway-for-containers-components
  - title: What is Application Gateway Ingress Controller?
    url: https://learn.microsoft.com/azure/application-gateway/ingress-controller-overview
  - title: Azure Front Door Frequently Asked Questions (FAQ)
    url: https://learn.microsoft.com/azure/frontdoor/front-door-faq
  - title: API Gateway Overview
    url: https://learn.microsoft.com/azure/api-management/api-management-gateways-overview
published_at: 2026-09-15
---

# HTTP/3 개요와 Azure L7 지원 현황

**기준일: 2026-09-15.** Azure 주요 L7 서비스의 공개 문서와 이날 수행한
점검 결과를 정리한다. **Application Gateway의 HTTP/3는 Preview로 문서화되어
있고, 실제 구성한 AGFC에서는 HTTP/2는 성공했지만 HTTP/3는 연결되지 않았다.** 두 제품의 지원
상태를 동일하게 취급하면 안 된다.

## HTTP/3란

HTTP/3는 HTTP의 요청·응답 의미를 유지하면서 전송 계층으로 **TCP 대신
UDP 기반 QUIC**를 사용하는 프로토콜이다. QUIC에 TLS 1.3이 통합되어 있으며,
UDP를 사용하더라도 스트림별 신뢰성 있는 순서 보장 전송을 제공한다.

| 특징 | 의미 |
|---|---|
| 연결 성립 지연 감소 | TCP 연결과 별도의 TLS 협상에 필요한 왕복을 줄여, RTT가 큰 환경의 초기 응답에 유리할 수 있음 |
| 독립적인 스트림 | HTTP/2의 TCP 연결에서 생기는 전송 계층 head-of-line blocking을 피함. 다만 연결 전체의 혼잡 제어는 공유하므로 손실의 모든 영향이 사라지는 것은 아님 |
| 연결 이동 기능 | QUIC 연결 ID를 이용해 IP·포트가 바뀌어도 연결을 유지할 수 있음. 실제 망 전환 동작은 클라이언트·서버의 지원과 설정에 달림 |

**HTTP/3가 항상 더 빠른 것은 아니다.** 구현, RTT, 손실, 연결 재사용과
워크로드에 따라 결과가 달라진다. 아래 로컬 실험에서도 개선과 악화를 모두
관측했다. 망 전환·배터리 절약 효과는 이번에 측정하지 않았다.

## Azure 주요 L7 서비스의 HTTP/3 지원

비교 기준은 **클라이언트 → L7 프런트엔드** 구간이다. 앞단에서 HTTP/3를
종단하더라도 백엔드까지 HTTP/3일 필요는 없다. 예를 들어 Application Gateway의
HTTP/3 Preview는 클라이언트 구간에만 적용되며 백엔드는 HTTP/1.1을 사용한다.

| 서비스 | 확인한 공개 지원 정보 | 이번 직접 점검 |
|---|---|---|
| **Azure Application Gateway** | **HTTP/3 Preview 지원.** Basic listener와 TLS 1.3을 지원하는 2022 사전 정의 TLS 정책 필요. WAF gateway·multi-site listener·IPv6 listener·상호 인증은 해당 Preview에서 지원하지 않음 | 미수행 — 문서 확인만 수행 |
| **Application Gateway for Containers(AGFC)** | 프런트엔드 HTTP/1.1·HTTP/2가 명시됨. 확인한 문서에는 HTTP/3 지원·활성화 방법이 없음 | **정상 HTTPS 구성에서 HTTP/2 성공, HTTP/3 연결 불성립** |
| **Azure Front Door** | FAQ에 HTTP·HTTPS·HTTP/2 지원이 명시됨. HTTP/3 지원은 명시되어 있지 않음 | 미수행 |
| **Azure API Management** | 게이트웨이 기능표에 종류·계층별 HTTP/2 지원이 명시됨. HTTP/3 지원은 명시되어 있지 않음 | 미수행 |

API Management는 API 게이트웨이로 함께 비교했다. **문서에 HTTP/3가 없다는
사실과 제품 전체의 미지원 확정은 구분한다.** 이 표는 모든 L7 제품의 목록이나
미공개 Preview의 판정표가 아니며, 실제 Azure 경로를 점검한 제품은 AGFC뿐이다.
Application Gateway의 HTTP/3 Preview는 SLA가 제공되지 않고 프로덕션 사용을 권장하지
않는다는 공식 주의사항도 있다.

### AGIC와 AGFC는 다르다

**AGIC**는 기존 Application Gateway를 설정하는 Kubernetes 컨트롤러다.
반면 **AGFC**는 별도 제어·데이터 플레인을 가진 제품이며 ALB Controller로
관리한다. 따라서 기존 Application Gateway에 추가된 HTTP/3 기능이 AGFC에도
자동 적용된다고 볼 수 없다. AGIC 자체가 HTTP/3 Preview 설정을 관리하는지도
이번에 검증하지 않았다.

## 실제 AKS + AGFC에서 확인한 사실

Korea Central에 임시 **AKS 1.35 + AGFC(ALB Controller 1.10.30)**를 구성했다.
경로는 `클라이언트 → AGFC HTTPS/443 → AKS 백엔드`이며 별도 Application
Gateway는 없었다. HTTPS 리스너·라우트와 백엔드는 정상이고, 인증서 검증을
켠 상태에서 같은 주소를 대상으로 비교했다.

| 접속 위치·클라이언트 | HTTP/2 강제 연결 | HTTP/3 강제 연결 |
|---|---|---|
| 로컬, curl/ngtcp2 | 3/3 성공, HTTP 200 | 0/3 성공, 모두 8초 타임아웃 |
| Azure AKS Pod, quic-go | 3/3 성공, HTTP 200 | 0/3 성공, 모두 8초 타임아웃 |
| 로컬, quic-go | 1/1 성공, HTTP 200 | 0/1 성공, 8초 타임아웃 |

- 추가 **15초 제한**의 HTTP/3 연결도 타임아웃이었다. 이후 HTTP/2 응답은
  여전히 정상이었다.
- 같은 로컬·Azure 환경의 외부 HTTP/3 대조군은 정상 연결됐다.
  AGFC 서브넷에는 사용자 NSG·라우팅 테이블이 없었다.
- **자동 fallback을 허용한 요청은 성공했지만 실제 프로토콜은 HTTP/2였다.**
  요청 성공만으로 HTTP/3 연결 성공이라고 판단할 수 없다.
- 임시 AKS·AGFC와 관련 리소스 그룹은 삭제 완료를 확인했다.

**판정: 점검한 AGFC HTTPS 구성에서는 HTTP/3를 사용할 수 없었다.**
다만 관측은 명시적인 프로토콜 거절 응답이 아닌 타임아웃이다. AGFC 측 경로의
UDP 처리 제한과 HTTP/3 리스너 부재를 이 결과만으로 구별하지는 못하며,
모든 지역·미공개 Preview·향후 버전으로 결론을 확대하지 않는다.

## 별도 모바일망 모의실험에서 관측한 성능

다음은 **AGFC가 아닌 로컬 HTTP/2·HTTP/3 서버**의 응답 완료 시간이다.
추가 RTT 80 ms, 방향별 10 Mbit/s, 방향별 손실 0%·1% 조건에서 각 조합을
30회 측정했다. 연결 재사용 항목의 응답 16개는 각각 16 KiB다.
p50·p95는 표본에서 계산한 50·95번째 백분위수다.

| 조건·작업 | HTTP/2 | HTTP/3 | 관측 결과 |
|---|---:|---:|---|
| 무손실, 새 연결·1 KiB 응답 p50 | 257.0 ms | 174.2 ms | 32.2% 단축 |
| 무손실, 연결 재사용·16개 응답 p50 | 481.3 ms | 364.0 ms | 24.4% 단축 |
| 손실 1%, 연결 재사용·16개 응답 p95 | 1611.9 ms | 884.8 ms | 45.1% 단축 |
| 손실 1%, 새 연결·1 KiB 응답 p95 | 367.5 ms | 421.8 ms | **14.8% 악화** |

추가 지연·손실이 없는 로컬 조건에서는 HTTP/3가 더 느렸다. 위 결과는
조건별 30개 표본의 탐색적 관측이며 **실제 스마트폰·통신사망·Azure L7의
성능 개선율이 아니다.** AGFC 경로의 HTTP/3 성능 개선율은 연결이 성립하지
않았으므로 **미측정**이다.

## 핵심 정리

- HTTP/3는 높은 RTT의 연결 성립과 손실 환경의 다중 스트림 전송에 이점이
  있을 수 있지만, 모든 응답 시간·꼬리 지연이 개선되는 것은 아니다.
- HTTP/3 적용 여부는 **클라이언트가 연결하는 L7 종단의 제품·기능·제약**으로
  판단한다. TLS 1.3 지원이나 Application Gateway라는 이름만으로 추정하지 않는다.
- **공식 문서의 지원 정보, 실제 프로토콜 연결 결과, 별도 환경의 성능 수치는
  서로 다른 근거**다.

상세 절차 대신 비식별화한 AGFC 연결 결과와 로컬 성능 원시 데이터를
각각 이 topic의 결과 아티팩트와 기존 sample에 보존한다.

## 공식 출처

- [RFC 9114: HTTP/3](https://www.rfc-editor.org/rfc/rfc9114): HTTP 의미, QUIC 전송과 독립 스트림.
- [Application Gateway HTTP/3 Preview](https://learn.microsoft.com/azure/application-gateway/http3-quic-support): 클라이언트 구간 지원과 Preview 제약.
- [AGFC overview](https://learn.microsoft.com/azure/application-gateway/for-containers/overview) · [components](https://learn.microsoft.com/azure/application-gateway/for-containers/application-gateway-for-containers-components): 별도 데이터 플레인과 지원 프로토콜.
- [AGIC overview](https://learn.microsoft.com/azure/application-gateway/ingress-controller-overview): 기존 Application Gateway를 관리하는 컨트롤러.
- [Azure Front Door FAQ](https://learn.microsoft.com/azure/frontdoor/front-door-faq): 지원 프로토콜.
- [API Management gateway overview](https://learn.microsoft.com/azure/api-management/api-management-gateways-overview): 게이트웨이 종류·계층별 기능.

공식 원문은 직접 대조했으나 Microsoft Learn MCP를 통한 재검증은 수행하지
못해 문서 검증 상태는 `needs-review`로 남겼다. 위 AGFC 실측은 별도로
확인한 관측 기록이다.
