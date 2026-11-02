# 한국어 문체 밀도 검사기

에이전트가 쓴 한국어 Markdown에서 AI가 쓴 글처럼 읽히게 만드는 패턴의 개수와
밀도를 센다. AI 생성 여부를 판별하는 도구가 아니다. 고쳐 쓸 위치를 찾는 데만
쓴다. Python 3.9 이상 표준 라이브러리만 사용한다.

## 실행

아래 명령은 모두 이 sample 디렉터리에서 실행한다. 저장소 루트에서 시작한다면 먼저
이동한다.

```bash
cd docs/services/application-development/agents-md-korean-writing/samples/korean-style-check
python check_korean_style.py examples/
python check_korean_style.py --strict ../../../../../services/
python check_korean_style.py --json ../../index.md
```

저장소 루트에 머물러 있다면 스크립트를 전체 경로로 지정한다.

```bash
python docs/services/application-development/agents-md-korean-writing/samples/korean-style-check/check_korean_style.py --strict docs/services/
```

`--strict`를 주면 기준을 넘는 파일이 하나라도 있을 때 종료 코드 1을 반환한다.
에이전트의 작업 종료 전 점검이나 pre-commit 훅에 연결할 수 있다.

## 세는 항목

| 항목 | 기본 기준 | 근거 |
|---|---|---|
| `X: Y` 형식 제목 | 0개 (`research`·`lab` 문서는 세지 않음) | Wikipedia "Signs of AI writing", im-not-ai C-10 |
| `~합니다`·`~다`·`~요`로 끝나는 문장형 제목 | 0개 | 저장소 기여 가이드의 명사구 제목 예시 |
| 설명 문단의 굵은 글씨 밀도 | 본문 1,000자당 2개 | 카카오 문서 스타일 가이드, im-not-ai J-1 |
| `**꼬리표**:`로 시작하는 설명 문단 | 1개 | Wikipedia "Signs of AI writing" |
| 연결어미(-고·-며·-지만 등) 뒤 쉼표 | 100문장당 8개 | KatFishNet(ACL 2025) |
| 접속부사(그리고·따라서 등) 뒤 쉼표 | 0개 | KatFishNet 부록에서 인용한 한글 맞춤법 문장 부호 규정 |
| 번역투(~에 의해, 이중 피동, ~에 있어서 등) | 100문장당 6개 | Microsoft 한국어 스타일 가이드, 토스 테크니컬 라이팅 |
| 결산 접속어·의미 부풀리기·열거 도입 | 1개 | im-not-ai D-1·D-2·D-3 |
| "A가 아니라 B" 대조 | 2개 | im-not-ai C-8 |
| 설명 문단의 대시(—) | 100문장당 10개 | Wikipedia "Signs of AI writing", im-not-ai J-3 |
| `~다`와 `~니다` 종결 혼용 | 소수 쪽 15% | 카카오 문서 스타일 가이드 |
| 글머리표 줄 비율 | 35% | im-not-ai C-2 |

굵은 글씨, 꼬리표와 대시는 설명 문단에서만 센다. 표, 글머리표와 인용 블록은
결과·비교 절의 [스캔형 구성](../../../../../contributing/index.md#scan-format)이 비교 표의
우위 수치, 발견 목록의 꼬리표와 판정 기호를 두는 곳이라 세지 않는다. 목록이나 표를
여는 단독 꼬리표 줄(`**분석:**`)과 링크만 담은 출처 줄(`**출처:** [..] · [..]`)도
세지 않는다. 결론 꼬리표 문단(`**정리:** ...`)은 두 번 이상 반복될 때만 건다.

표 줄 비율, 문장 길이 평균과 변동계수(`sentence_chars_cv`)는 참고값으로만 출력한다.
표가 같은 기준의 비교인지는 개수로 판단할 수 없다. 문장 길이가 고른 글이 기계적으로
읽힌다는 관찰은 있지만 한국어 기술 문서의 기준값은 없다.

검사 결과는 다시 읽을 위치를 알려 줄 뿐이며 모든 수치를 0으로 맞출 필요는 없다. 모든 수치를 0으로 맞추려고
결과·비교 문서의 표와 목록을 문단으로 풀었을 때 문장이 79개에서 151개로 늘고
결론을 찾기 어려워졌다.

기준값은 저장소 문서를 읽으며 정한 출발점이다. `Thresholds` 클래스에서 조정한다.
코드 블록, 인라인 코드, 제목과 표는 문장 패턴 검사에서 뺀다. 코드 블록은 같은
문자로 여는 펜스와 길이가 같거나 더 긴 펜스로만 닫힌다. 각 줄에서 인용 블록(`>`),
목록 항목과 MkDocs의 admonition·접힘·탭 블록 접두사를 먼저 걷어 낸 뒤 남은 내용에서
펜스를 찾는다. 그래서 `> ```text`나 `- ```text`도 펜스로 보고, 최상위에서 네 칸
들여쓴 펜스는 펜스가 아니라 들여쓰기 코드 블록으로 본다. 소속 블록이 끝나면 열린
펜스도 닫힌다. 소속 블록 접두사를 걷어 낸 뒤 네 칸 이상 들여쓴 줄은 문단을 이어 가는
줄이 아니면 들여쓰기 코드 블록으로 보고 뺀다. `제목\n===`, `제목\n---` 형식의 Setext
제목도 `#` 제목과 같이 검사하며, 빈 줄 뒤의 `---`는 구분선으로 둔다.
표는 구분 행(`--- | ---`)으로 찾으며 바깥쪽 `|`를 생략한 표도 인식한다.
따옴표 안의 문구도 예시를 인용한 경우가 많아 패턴 검사와 문장 수
계산에서 뺀다. 영문자나 숫자에 붙은 작은따옴표(`don't`, `user's`)는 인용 부호로 보지
않는다. 제목은 링크 레이블과 강조 표시를 평문으로 바꾼 뒤 검사한다.
형태소 분석을 하지 않으므로 용언과 명사는 마지막 음절로 구분한다. 문장형 제목은
"다"나 "요" 앞 음절이 용언 어간처럼 끝날 때만 센다(한다·했다·없다·다르다·해요).
"개요", "필요", "바다", "람다"는 세지 않지만 "판다", "아젠다" 같은 외래어는 잘못 셀 수
있다. 연결어미 쉼표는 "사고", "재고", "참고", "로고"처럼 "고"로 끝나는 흔한 명사를
뺀다. "보고"는 "로그를 보고,"처럼 연결형으로도 자주 쓰여 그대로 센다. 예시 문구를
함께 출력하므로 사람이 확인한 뒤 고친다.

## 테스트

`test_check_korean_style.py`는 표준 라이브러리 `unittest`로 문장형·Setext 제목, 연결어미
쉼표, 코드 펜스와 들여쓰기 코드 블록, 인용, 표와 스캔형 구성 판정을 검증한다.

sample 디렉터리에서 실행한다. 저장소 루트에서는 `-s`로 시작 디렉터리를 지정한다.

```bash
python -m unittest -v
python -m unittest discover -v -s docs/services/application-development/agents-md-korean-writing/samples/korean-style-check
```

## 예시

`examples/before.md`는 AI 문체 패턴을 일부러 모은 글이고 `examples/after.md`는
같은 내용을 고쳐 쓴 글이다. sample 디렉터리에서 실행한다.

```bash
python check_korean_style.py --strict examples/after.md   # 종료 코드 0
python check_korean_style.py --strict examples/before.md  # 종료 코드 1
```

## 정리

설치하거나 생성하는 파일이 없다. 스크립트만 복사해 쓰고 필요 없으면 지운다.
