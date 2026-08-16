# 실습 도구 모음

이 저장소의 실습이 공통으로 쓰는 도구와 설치 방법입니다. 랩마다 목록을 복제하지 않고 이 문서 하나를 갱신합니다.

## 컨테이너로 갖추기 (권장)

`.devcontainer/devcontainer.json`이 저장소 전체의 기본 설정입니다. 별도로 고를 것이 없습니다.

- **Codespaces**: 저장소에서 **Code > Codespaces > Create codespace**
- **로컬 VS Code**: **Dev Containers: Reopen in Container**

컨테이너는 도구만 갖춰 줍니다. 로그인과 각 랩의 준비 명령은 실습 문서를 따라 직접 실행합니다. 무엇이 실행되는지 가려지지 않도록 컨테이너가 랩 명령을 대신 실행하지 않습니다.

## 도구 목록

| 도구 | 쓰임 | 컨테이너에서 |
|---|---|---|
| `az` | Azure 리소스 조회·조작, 로그 쿼리 | `azure-cli` feature (`log-analytics`, `containerapp` 확장 포함) |
| `azd` | 랩 환경 프로비저닝(`azd up`)과 삭제(`azd down`) | `azure-dev/azd` feature |
| `gh` | GitHub 저장소·이슈 확인 | `github-cli` feature |
| `python3` | 랩의 Python 도구 실행 | `python` feature (3.12) |
| `uv` | Python 의존성 설치 | `python` feature의 `toolsToInstall` |
| `jq` | JSON 출력 파싱 | 베이스 이미지 |
| `curl` | 애플리케이션 엔드포인트 호출 | 베이스 이미지 |

## 로컬에 직접 설치하기

컨테이너를 쓰지 않는다면 아래를 설치합니다.

**macOS (Homebrew)**

```bash
brew install azure-cli azure-dev gh python@3.12 uv jq
```

**Ubuntu / Debian**

```bash
sudo apt-get update && sudo apt-get install -y jq curl python3
curl -sSL https://aka.ms/InstallAzureCLIDeb | sudo bash
curl -fsSL https://aka.ms/install-azd.sh | bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`gh`는 [GitHub CLI 설치 안내](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)를 따릅니다.

`az` 확장은 별도로 추가합니다. 랩에서 `az monitor log-analytics query`를 쓰려면 필요합니다.

```bash
az extension add --name log-analytics
az extension add --name containerapp
```

사내 프록시 환경이라면 `uv`가 프록시로 구성된 인덱스를 그대로 씁니다. 랩의 Python 환경 준비 스크립트는 공개 PyPI로 폴백하지 않으므로, `uv`가 없으면 설치 안내와 함께 실패합니다.

## 로그인

두 CLI는 자격 증명을 따로 관리하므로 각각 로그인합니다.

```bash
az login --use-device-code
azd auth login
```

## 참고

- [Dev Containers 사양](https://containers.dev/implementors/json_reference/)
- [Codespaces 문서](https://docs.github.com/ko/codespaces)
- [azd 설치](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- [uv 설치](https://docs.astral.sh/uv/getting-started/installation/)
