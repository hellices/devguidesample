# 자동화 가이드

자동화 관련 문서는 이 카테고리 아래에 모은다. 하나의 목적을 다루는 원리·실험·결과·한계는 주제별 Markdown 파일 하나에 정리하고, 실행 스크립트와 증적은 하위 `*-lab/` 폴더에 보관한다.

| 문서 | 내용 |
|---|---|
| [GitHub Actions Self-hosted Runner - NAT 환경의 사설 IP 변경 검증](github-actions-self-hosted-runner.md) | 작업 수신 원리, IP 변경 실험, 실제 수신 대기 관측, 재현 절차·근거·미확인 사항 |
| [Azure Automation - 포탈/CLI 제한사항 및 우회 방법](portal-cli-limitations.md) | Runbook 게시·스케줄 연동 등 관리 작업의 제한과 우회 방법 |

## 문서 배치

- 파일명은 `portal-cli-limitations.md`처럼 영문 소문자와 하이픈으로 주제를 나타낸다.
- Runner 실험의 그림·스크립트·증적은 모두 `runner-nat-lab/` 아래에 둔다.
- 개별 가이드나 랩 때문에 새 최상위 폴더를 추가하지 않는다.
