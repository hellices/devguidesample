# 한국어 문체 밀도 검사기

에이전트가 쓴 한국어 Markdown에서 AI가 쓴 글처럼 읽히게 만드는 패턴의 개수와
밀도를 센다. AI 생성 여부를 판별하는 도구가 아니다. 고쳐 쓸 위치를 찾는 데만
쓴다. Python 3.9 이상 표준 라이브러리만 사용한다.

## 실행

```bash
python check_korean_style.py examples/
python check_korean_style.py --strict docs/
python check_korean_style.py --json path/to/doc.md
```

`--strict`를 주면 기준을 넘는 파일이 하나라도 있을 때 종료 코드 1을 반환한다.
에이전트의 작업 종료 전 점검이나 pre-commit 훅에 연결할 수 있다.

## 세는 항목

| 항목 | 기본 기준 | 근거 |
|---|---|---|
| `X: Y` 형식 제목 | 0개 | Wikipedia "Signs of AI writing", im-not-ai C-10 |
| `~합니다`·`~다`로 끝나는 문장형 제목 | 0개 | 저장소 기여 가이드의 명사구 제목 예시 |
| 굵은 글씨 밀도 | 본문 1,000자당 2개 | 카카오 문서 스타일 가이드, im-not-ai J-1 |
| `**꼬리표**:`로 시작하는 줄 | 0개 | Wikipedia "Signs of AI writing" |
| 연결어미(-고·-며·-지만 등) 뒤 쉼표 | 100문장당 8개 | KatFishNet(ACL 2025) |
| 접속부사(그리고·따라서 등) 뒤 쉼표 | 0개 | KatFishNet 부록에서 인용한 한글 맞춤법 문장 부호 규정 |
| 번역투(~에 의해, 이중 피동, ~에 있어서 등) | 100문장당 6개 | Microsoft 한국어 스타일 가이드, 토스 테크니컬 라이팅 |
| 결산 접속어·의미 부풀리기·열거 도입 | 1개 | im-not-ai D-1·D-2·D-3 |
| "A가 아니라 B" 대조 | 2개 | im-not-ai C-8 |
| 대시(—) | 0개 | Wikipedia "Signs of AI writing" |
| `~다`와 `~니다` 종결 혼용 | 소수 쪽 15% | 카카오 문서 스타일 가이드 |
| 글머리표·표 줄 비율 | 35%·30% | im-not-ai C-2 |

문장 길이 평균과 변동계수(`sentence_chars_cv`)도 함께 출력한다. 연구에서 문장
길이가 고른 글이 기계적으로 읽힌다는 관찰은 있지만 한국어 기술 문서의 기준값은
없으므로 이 값으로는 판정하지 않는다.

기준값은 저장소 문서를 읽으며 정한 출발점이다. `Thresholds` 클래스에서 조정한다.
코드 블록, 인라인 코드, 제목과 표는 문장 패턴 검사에서 뺀다. 코드 블록은 같은
문자로 여는 펜스와 길이가 같거나 더 긴 펜스로만 닫히며, 목록 안에서 들여쓴 펜스도
코드로 본다. 따옴표 안의 문구도 예시를 인용한 경우가 많아 패턴 검사와 문장 수
계산에서 뺀다.
정규식은 형태소 분석을 하지 않으므로 "참고," 같은 명사 뒤 쉼표를 연결어미로
잘못 셀 수 있다. 예시 문구를 함께 출력하므로 사람이 확인한 뒤 고친다.

## 예시

`examples/before.md`는 AI 문체 패턴을 일부러 모은 글이고 `examples/after.md`는
같은 내용을 고쳐 쓴 글이다.

```bash
python check_korean_style.py --strict examples/after.md   # 종료 코드 0
python check_korean_style.py --strict examples/before.md  # 종료 코드 1
```

## 정리

설치하거나 생성하는 파일이 없다. 스크립트만 복사해 쓰고 필요 없으면 지운다.
