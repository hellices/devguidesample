# Korean rewrite examples

Each pair is "AI-like → rewritten". One or two occurrences are fine; rewrite when they cluster in a paragraph.

## Translationese

| Pattern | AI-like | Rewritten |
|---|---|---|
| `~에 의해` | 파일이 애플리케이션에 의해 저장된다 | 애플리케이션이 파일을 저장한다 |
| Double passive | 활용되어진다, 보여진다 | 활용된다, 보인다 |
| `~에 있어서` | 설계에 있어서 중요한 것은 | 설계에서 중요한 것은 |
| Padding verbs (수행·진행·제공) | 로그 파일을 삭제하는 작업을 수행한다 | 로그 파일을 삭제한다 |
| English-style nominalization | 인증 처리가 완료된 후 접속 설정 진행이 가능하다 | 사용자를 인증한 후 접속하도록 설정할 수 있다 |
| Chained `~의` | 흐름의 모양의 검사의 결과 | 흐름 모양을 검사한 결과 |
| `~을 가지고 있다` | 필요한 권한을 가지고 있지 않을 수 있다 | 필요한 권한이 없을 수 있다 |
| `~하는 것이 중요하다` | 검사하는 것이 중요하다 | 검사해야 한다 |
| Pronouns and `들` | 그것은 이것들을 통해 검증된다 | Drop the subject or name it |
| Comma after a connective ending | 설정을 바꾸고, 다시 배포하며, 로그를 본다 | 설정을 바꾸고 다시 배포한 뒤 로그를 본다 |

## LLM patterns in explanation paragraphs

| Pattern | AI-like | Rewritten |
|---|---|---|
| Conclusion box | **결론**: 코드가 문서를 이겼다. | 시간이 지나자 그림은 코드와 맞지 않게 됐다. |
| Habitual contrast | 효과는 지연이 아니라 신뢰성에서 나왔다 | 지연 시간은 그대로였고 화면 실패율이 줄었다 |
| Vague intensifier | 다양한 요소를 고려한다 | Name the factors, or delete the sentence if none are known |
| Enumeration opener | 크게 세 가지로 나눌 수 있다 | Start with the first item |
| Dash joining clauses | 확장한다 — 이것이 핵심이다 | 확장한다. |
| English term on every mention | 구간(hop) … 구간(hop) | 구간(hop) once, then 구간 |

## Result section kept in scan format

Fix wording only. The table, bold winning numbers, bold labels, and noun-ending bullets stay.

```markdown
**분석:**
- **T4: ~60 texts/s 부근에서 상한 도달.** 본 벤치마크 조건에서는 batch/concurrency 조정만으로는 유의미한 추가 향상을 확인하지 못했으며, 64×4에서는 오히려 소폭 하락(스케줄링 오버헤드 추정).
```

```markdown
**분석:**
- **T4: ~60 texts/s 부근에서 상한 도달.** 본 벤치마크 조건에서는 batch/concurrency를 조정해도 의미 있는 추가 향상을 확인하지 못했고 64×4에서는 오히려 소폭 하락(스케줄링 오버헤드 추정).
```
