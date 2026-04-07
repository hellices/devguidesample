# Codex ↔ Azure AI Foundry 연동: 폐쇄망 환경 가이드

## **문제 상황**

폐쇄망 환경에서는 VS Code의 GitHub Copilot Chat을 직접 활용할 수 없다.  
GitHub Copilot은 GitHub Public과의 통신이 필수적이며, GHE(GitHub Enterprise Server)를 사용하더라도 동일한 제약이 존재하고 GitHub Copilot과의 연계 매뉴얼 자체가 없다.

![GitHub Copilot 문서 버전 선택 화면](https://github.com/user-attachments/assets/61ad2681-bd06-4888-a718-e0f4544db985)

***

## **해결 방향**

GitHub Codex는 GitHub Extension 또는 단독(standalone) 모드로 활용 가능한 서비스로,  
**Azure AI Foundry의 엔드포인트를 활용**하면 폐쇄망에서도 AI 코딩 어시스턴트를 사용할 수 있다.

Azure AI Foundry를 Private Endpoint로 구성한 경우, Azure 망과 업무망이 분리되어 Direct Access가 불가능할 수 있다.  
이 경우 **VS Code Server + SSH 터널링 + Squid Proxy** 구성을 통해 우회 연결이 가능하다.

***

## **전체 연결 흐름**

```
로컬 Codex (Extension 또는 CLI)
  → Nginx (localhost, 443 포트)
  → SSH 터널링 (50056 포트)
  → VM 내 Squid Proxy
  → Azure AI Foundry (Private Endpoint)
```

***

## **설정 방법**

### 1. 로컬 DNS 설정 (hosts 파일)

Private Endpoint 도메인을 `localhost`로 매핑한다.

> 예: Private Endpoint 도메인이 `aif-krc-openai.azure.com`인 경우

**Windows hosts 파일 경로**: `C:\Windows\System32\drivers\etc\hosts`

```
127.0.0.1  aif-krc-openai.azure.com
```

***

### 2. Codex 설정 파일

**설정 파일 경로**: `C:\Users\<username>\.codex\`

**`config.toml`**

```toml
model = "gpt-5.3-codex"
model_provider = "custom-provider"
personality = "pragmatic"
model_reasoning_effort = "medium"
preferred_auth_method = "apikey"

[model_providers.custom-provider]
name = "azure-openai"
base_url = "https://aif-krc-openai.azure.com/openai/v1/"
env_key = "OPENAI_API_KEY"
wire_api = "responses"

[notice.model_migrations]
gpt-5 = "gpt-5.3-codex"

[windows]
sandbox = "elevated"
```

**`auth.json`** (우선 시도)

```json
{
  "OPENAI_API_KEY": "your_api_key"
}
```

**`.env`** (`auth.json`으로 인증이 되지 않는 경우 대안)

```
OPENAI_API_KEY=your_api_key
```

***

### 3. 로컬 Nginx 설치 및 설정

로컬 PC에 Nginx를 설치하고, AI Foundry Private Endpoint로의 요청을 SSH 터널 포트로 전달하도록 구성한다.

**`nginx.conf`**

```nginx
worker_processes  1;

events {
    worker_connections  1024;
}

http {
    include       mime.types;
    default_type  application/octet-stream;
    sendfile        on;
    keepalive_timeout  65;

    server {
        listen       443;
        server_name  aif-krc-openai.azure.com;

        location / {
            proxy_pass http://127.0.0.1:50056;

            proxy_set_header Host aif-krc-openai.azure.com;
            proxy_set_header Proxy-Connection keep-alive;
        }

        error_page   500 502 503 504  /50x.html;
        location = /50x.html {
            root   html;
        }
    }
}
```

*   Nginx는 로컬 443 포트에서 수신 대기
*   수신된 요청을 `127.0.0.1:50056`(SSH 터널 포트)으로 전달
*   `Host` 헤더를 원래 AI Foundry 도메인으로 유지

***

### 4. SSH 터널링 설정

로컬 50056 포트를 VM의 Squid Proxy 포트로 포워딩한다.

```bash
ssh -L 50056:localhost:50056 <vm-user>@<vm-host>
```

*   로컬 50056 포트 → VM의 localhost:50056 으로 터널링
*   VM에는 Squid가 50056 포트에서 수신 대기 중이어야 함

***

### 5. VM 내 Squid Proxy 설정

VM에 Squid를 설치하고 아래와 같이 설정한다.

**`squid.conf`**

```
http_port 50056

acl CONNECT method CONNECT
acl SSL_ports port 443
acl localnet src 10.0.0.0/8
acl mylocal src 10.113.64.90/32

http_access allow localnet CONNECT SSL_ports mylocal
http_access allow all

access_log /tmp/squid/access.log
cache_log /tmp/squid/cache.log
pid_filename /tmp/squid/squid.pid
```

*   `acl mylocal`의 IP는 실제 VM의 내부 IP로 변경
*   Squid는 CONNECT 메서드를 허용하여 HTTPS 터널링을 지원

**Squid 설치 및 실행**

```bash
# Squid 설치
sudo apt-get install -y squid

# 로그 및 PID 디렉토리 생성
mkdir -p /tmp/squid

# 설정 파일을 지정하여 Squid 실행
squid -f /path/to/squid.conf

# 실행 확인
squid -f /path/to/squid.conf -k check
```

*   `/path/to/squid.conf`는 실제 설정 파일 경로로 변경
*   `-k check` 옵션으로 설정 파일 유효성을 사전에 검증 가능

***

## **구성 요약**

| 구성 요소 | 위치 | 역할 |
|---|---|---|
| Codex | 로컬 PC | AI 코딩 어시스턴트 |
| hosts 파일 | 로컬 PC | Private Endpoint 도메인을 localhost로 매핑 |
| Nginx | 로컬 PC (443) | HTTPS 요청 수신 후 SSH 터널로 전달 |
| SSH 터널 | 로컬 ↔ VM (50056) | 로컬과 VM 간 암호화 통신 채널 |
| Squid Proxy | VM (50056) | AI Foundry Private Endpoint로 요청 전달 |
| Azure AI Foundry | Azure Private Endpoint | LLM 추론 엔드포인트 |

***

## **참고 링크**

*   [Azure AI Foundry Private Endpoint 설정](https://learn.microsoft.com/ko-kr/azure/ai-foundry/how-to/configure-private-link)
*   [GitHub Copilot Coding Agent (Codex) 공식 문서](https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-coding-agent)
*   [Nginx 공식 문서](https://nginx.org/en/docs/)
*   [Squid Proxy 공식 문서](http://www.squid-cache.org/)

***
