# Foundry hosted agent에서 Toolbox 사용

이 문서는 [MCP 운영 아키텍처](../../../docs/guides/azure-architecture/mcp-configuration/index.md)의 hosted-agent 구성을 따라 하는 sample 안내입니다. Agent가 model과 Toolbox를 호출하는 것이며, MCP backend를 hosted agent에 옮기는 절차가 아닙니다.

## 1. 필요한 환경

- Foundry project와 게시한 Toolbox consumer endpoint.
- Agent 배포자의 **Foundry Project Manager** 권한과 runtime identity의 필요한 project/tool 권한.
- Azure CLI, azd 및 `microsoft.foundry` 확장.
- 선택한 공식 sample manifest의 `requiredVersions`를 충족하는 도구 버전.

모델·compute·스토리지 비용과 region 지원을 확인합니다. 사용자 OAuth tool을 쓰면 사용자 context·consent와 해당 backend 권한도 필요합니다.

## 2. 공식 sample에서 agent 초기화

기존 작업 디렉터리를 덮어쓰지 않도록 새 폴더에서 실행합니다.

```bash
mkdir toolbox-hosted-agent
cd toolbox-hosted-agent
azd extension install microsoft.foundry
azd auth login

azd ai agent init -m https://github.com/microsoft-foundry/foundry-samples/blob/main/samples/python/hosted-agents/agent-framework/responses/04-foundry-toolbox/azure.yaml
```

이 manifest는 실제 azd sample catalog에서 확인한 **Agent Framework + Toolbox + Responses** 예제입니다. 안내에 따라 Foundry project와 model을 선택합니다. 기존 project를 재사용하려면 실제 project를 선택하며 endpoint 문자열만으로 ARM resource ID를 추측하지 않습니다.

## 3. 사용할 Toolbox 연결

```bash
read -r -p "Toolbox consumer endpoint: " TOOLBOX_ENDPOINT
azd env set TOOLBOX_ENDPOINT "$TOOLBOX_ENDPOINT"
```

이 저장소의 `learn-tools` 또는 `learn-tools-search` endpoint를 사용할 수 있습니다. 공식 sample의 여러 SaaS connection을 전부 만들 필요는 없습니다. 사용하지 않는 기본 tool과 model deployment가 포함되어 있는지 생성된 `azure.yaml`과 README를 확인합니다.

공식 구현의 `FoundryToolbox`는 Foundry credential로 Toolbox에 인증하고 platform의 per-request call ID를 연결합니다. 사용자 identity header나 token cache를 임의로 만들어 사용자 OAuth를 대체하지 않습니다.

## 4. Preview와 배포

```bash
azd provision --preview
azd up
```

이 sample의 manifest에는 project/model 배포가 포함될 수 있습니다. Preview에서 기존 리소스 재사용 여부와 새 비용을 확인한 뒤 진행합니다. Agent version이 active 상태가 되고 필요한 identity 권한이 적용되었는지 확인합니다.

## 5. Agent 요청과 tool 호출 확인

```bash
azd ai agent invoke --new-session \
  "Microsoft Learn에서 MCP authentication 문서를 찾아 핵심 내용을 설명해줘."
```

답변만 보지 말고 agent의 tool 호출도 확인합니다.

- 일반 Toolbox: 검색 도구가 직접 선택되는지 확인합니다.
- Tool search Toolbox: 필요한 경우 `tool_search`로 도구를 찾고 `call_tool`로 실행하는지 확인합니다.
- APIM으로 governance하는 MCP: Toolbox connection의 대상이 APIM인지, 실제 APIM HTTP 로그에 요청이 기록되는지 확인합니다.

이 저장소의 기본 Learn Toolbox는 공개 Learn endpoint를 직접 호출합니다. APIM 경유를 확인하려면 별도의 MCP connection을 APIM URL과 그 API의 인증 방식으로 구성해야 합니다. Foundry의 preview 자동 gateway 연계는 모든 code-first tool이나 managed OAuth에 적용되는 기능이 아닙니다.

## 6. 권한과 비용 확인

Agent identity로 Toolbox에 접근하는 권한과 backend가 사용자·agent 중 누구의 권한으로 실행되는지를 구분합니다. Tool search는 도구를 찾는 기능이지 권한 검사나 API rate limit가 아닙니다.

토큰 비교는 같은 model·task·권한·버전 조건으로 업무 완료까지의 usage와 latency를 기록합니다. 이 문서는 실행 결과나 절감률을 제공하지 않습니다.

## 7. 정리

생성한 agent와 전용 리소스만 해당 azd environment의 안내에 따라 제거합니다. 기존 Foundry project나 공유 Toolbox를 재사용했다면 그것까지 삭제하지 않습니다. 이 저장소의 Toolbox를 제거하는 절차는 [README](README.md#versions-and-cleanup)에 있습니다.

## 공식 근거

- [What are hosted agents?](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents)
- [Deploy a hosted agent](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent)
- [공식 Agent Framework + Toolbox sample](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents/agent-framework/responses/04-foundry-toolbox)
- [Foundry Toolbox integration](https://learn.microsoft.com/agent-framework/integrations/by-component/tools/foundry-toolbox)
