# Application Gateway SSE 통신 시 Response Buffer 비활성화 가이드

## 문제 상황

AI Agent(예: Azure OpenAI, custom LLM 서비스)와 **SSE(Server-Sent Events)** 방식으로 스트리밍 통신할 때, Azure Application Gateway 뒤에 배치된 백엔드로부터 응답이 **실시간으로 전달되지 않고 지연**되는 현상이 발생합니다.

클라이언트 측에서는 스트리밍 응답이 끊기거나, 전체 응답이 한꺼번에 도착하는 것처럼 보이며, SSE의 실시간 토큰 스트리밍 UX가 정상적으로 동작하지 않습니다.

---

## 원인 분석

Azure Application Gateway Standard v2 SKU는 기본적으로 **Response Buffering이 활성화**되어 있습니다.

Response Buffer가 활성화된 경우, Application Gateway는 백엔드 서버로부터 **응답 패킷을 모두(또는 일부) 수집한 뒤** 클라이언트에 전달합니다. 이는 느린 클라이언트를 수용하고 백엔드 TCP 연결을 빠르게 해제하기 위한 설계이지만, **SSE와 같은 실시간 스트리밍 프로토콜에서는 응답 지연의 원인**이 됩니다.

```
[AI Backend] --SSE stream--> [App Gateway (Buffer ON)] --지연 전달--> [Client]
```

SSE는 `Content-Type: text/event-stream`으로 백엔드가 **연결을 유지한 채 이벤트 단위로 데이터를 지속 전송**하는 방식입니다. Response Buffer가 켜져 있으면 Gateway가 응답 완료를 기다리며 패킷을 쌓아두기 때문에, 클라이언트가 실시간으로 토큰을 수신할 수 없습니다.

---

## 해결 방법

Application Gateway의 `globalConfiguration`에서 **Response Buffering을 비활성화**해야 합니다.

> ⚠️ **주의**: 이 설정은 현재 **Azure Portal에서 변경할 수 없습니다**. Azure CLI, PowerShell, 또는 ARM Template을 통해서만 구성 가능합니다.

### 방법 1: Azure CLI

```bash
az network application-gateway update \
  --name <application-gateway-name> \
  --resource-group <resource-group-name> \
  --set globalConfiguration.enableResponseBuffering=false
```

### 방법 2: Azure PowerShell

```powershell
# 기존 Application Gateway에 적용
$appgw = Get-AzApplicationGateway -Name <application-gateway-name> -ResourceGroupName <resource-group-name>
$appgw.EnableResponseBuffering = $false
Set-AzApplicationGateway -ApplicationGateway $appgw
```

```powershell
# 신규 Application Gateway 생성 시
New-AzApplicationGateway `
  -Name "ApplicationGateway01" `
  -ResourceGroupName "ResourceGroup01" `
  -Location $location `
  -BackendAddressPools $pool `
  -BackendHttpSettingsCollection $poolSetting `
  -FrontendIpConfigurations $fipconfig `
  -GatewayIpConfigurations $gipconfig `
  -FrontendPorts $fp `
  -HttpListeners $listener `
  -RequestRoutingRules $rule `
  -Sku $sku `
  -EnableResponseBuffering:$false
```

### 방법 3: ARM Template

```json
{
  "type": "Microsoft.Network/applicationGateways",
  "apiVersion": "2023-09-01",
  "name": "[parameters('applicationGatewayName')]",
  "location": "[resourceGroup().location]",
  "properties": {
    "globalConfiguration": {
      "enableRequestBuffering": true,
      "enableResponseBuffering": false
    }
  }
}
```

---

## 적용 확인

설정 변경 후 현재 상태를 확인하려면:

```bash
az network application-gateway show \
  --name <application-gateway-name> \
  --resource-group <resource-group-name> \
  --query "globalConfiguration"
```

예상 출력:

```json
{
  "enableRequestBuffering": true,
  "enableResponseBuffering": false
}
```

---

## 제한 사항

| 항목 | 내용 |
|------|------|
| **Portal 미지원** | Azure Portal에서는 Buffer 설정을 변경할 수 없으며, CLI/PowerShell/ARM으로만 가능 |
| **API 버전** | `2020-01-01` 이상의 API 버전이 필요 |
| **리소스 레벨 설정** | Buffer 설정은 리소스 전체에 적용되며, 리스너별로 개별 관리 불가 |
| **WAF SKU 주의** | WAF SKU 사용 시 Request Buffering은 비활성화할 수 없음 (WAF가 요청 전체를 버퍼링). Response Buffering은 WAF와 무관하게 비활성화 가능 |

---

## 참고 링크

- [Configure Request and Response Proxy Buffers - Azure Application Gateway](https://learn.microsoft.com/en-us/azure/application-gateway/proxy-buffers)
- [Application Gateway SSE and WebSocket support](https://learn.microsoft.com/en-us/azure/application-gateway/application-gateway-websocket)
