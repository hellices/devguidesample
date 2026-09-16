# Java LTS Version Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a concise, source-backed Korean guide that compares Java 8, 17, 21, and 25, recommends a version by operating constraint, explains conditional performance benefits, and shows safe modernization patterns.

**Architecture:** Add one canonical `guide` topic under the existing `application-development` service. Keep feature claims vendor-neutral with OpenJDK release and JEP sources, use Microsoft Build of OpenJDK only as one concrete example of vendor-specific LTS support, and integrate the page through the repository's generated navigation and search pipeline.

**Tech Stack:** Markdown, YAML front matter, OpenJDK JEP documentation, Microsoft Learn, MkDocs Material, Python documentation validators

## Global Constraints

- Create the canonical topic at `docs/services/application-development/java-lts-version-selection/index.md`.
- Use `document_type: guide`, service `application-development`, technology `java`, and tags `evaluate`, `migrate`, `optimize`.
- Cover Java SE 8, 17, 21, and 25; Java 11 is outside this guide's requested comparison scope.
- Treat LTS as a JDK-vendor support policy, not an intrinsic OpenJDK or Java SE designation.
- Separate final features from preview, incubator, experimental, and opt-in features.
- Do not claim that a JDK upgrade alone guarantees a performance improvement.
- Recommend only final features in production modernization examples.
- Add no sample project, rendered image, manual navigation entry, README entry, or hard-coded catalog entry.
- Do not add a new service, technology, or tag.
- Keep `docs/superpowers/**` available as internal design history but exclude it
  from MkDocs pages, navigation, and the search index.
- Use `2026-09-16` for `sources_checked_at` and `last_verified` only after all material claims have been checked against the listed official sources.
- Use `python3.13` for local validation because CI uses Python 3.13, while
  `/usr/bin/python3` is Python 3.9 and cannot evaluate the repository's PEP 604
  type annotations during test collection.
- Do not commit generated `site/` output.

---

## File Structure

- Modify `docs-taxonomy.yml`
  - Allow `openjdk.org` as an official source host so Java feature claims can cite their canonical upstream documentation.
- Modify `mkdocs.yml`
  - Exclude internal `superpowers/**` design and plan artifacts from publication.
- Create `docs/services/application-development/java-lts-version-selection/index.md`
  - Own all version comparisons, decision guidance, performance caveats, migration stages, code patterns, and verification guidance.
- Modify `tests/docs/test_pages_artifact.py`
  - Assert that internal `superpowers/**` artifacts do not enter the built site or search index.
- Modify `tests/docs/test_site_pipeline.py`
  - Lock the intended MkDocs exclusion rules.

### Task 1: Publish the source-backed Java LTS guide

**Files:**
- Modify: `docs-taxonomy.yml`
- Create: `docs/services/application-development/java-lts-version-selection/index.md`
- Test: `tests/docs/test_content.py`
- Test: `tests/docs/test_topics.py`

**Interfaces:**
- Consumes: `services.application-development`, `technologies.java`, tags `evaluate`, `migrate`, and `optimize` from `docs-taxonomy.yml`.
- Consumes: the common and `guide` metadata contract in `scripts/docs/content.py`.
- Produces: canonical topic key `application-development/java-lts-version-selection`.
- Produces: an official-source set containing at least one `learn.microsoft.com` URL and canonical `openjdk.org` URLs.

- [ ] **Step 1: Verify the source set and record the claim boundaries**

Read the complete contents of these official sources before drafting:

| Source | Claims it supports |
|---|---|
| `https://learn.microsoft.com/en-us/java/openjdk/support` | Vendors assign different support timelines; Microsoft lists 17, 21, and 25 as LTS releases and handles Java 8 separately through Temurin-based images in its stated scenarios. |
| `https://openjdk.org/projects/jdk8/` | JDK 8 GA date and its role as the Java SE 8 reference implementation. |
| `https://openjdk.org/projects/jdk8/features` | Java 8 lambda, collection bulk operations/Stream foundation, date/time API, and removal of PermGen. |
| `https://openjdk.org/projects/jdk/17/` | JDK 17 GA date and vendor-qualified LTS wording. |
| `https://openjdk.org/projects/jdk/17/jeps-since-jdk-11` | Final and preview additions from 12 through 17, including records, sealed classes, switch expressions, text blocks, strong encapsulation, ZGC, and G1 improvements. |
| `https://openjdk.org/jeps/248` | G1 becomes the default garbage collector in JDK 9. |
| `https://openjdk.org/jeps/261` | The Java Platform Module System is delivered in JDK 9. |
| `https://openjdk.org/jeps/286` | Local-variable type inference is delivered in JDK 10. |
| `https://openjdk.org/jeps/321` | The standard HTTP Client API is delivered in JDK 11. |
| `https://openjdk.org/projects/jdk/21/` | JDK 21 GA date and vendor-qualified LTS wording. |
| `https://openjdk.org/projects/jdk/21/jeps-since-jdk-17` | Final and preview additions from 18 through 21. |
| `https://openjdk.org/projects/jdk/25/` | JDK 25 GA date and vendor-qualified LTS wording. |
| `https://openjdk.org/projects/jdk/25/jeps-since-jdk-21` | Final, preview, experimental, deprecated, and removed changes from 22 through 25. |
| `https://openjdk.org/jeps/444` | Virtual threads improve the thread-per-request style and throughput for high-concurrency blocking workloads, not CPU execution speed or latency by themselves. |
| `https://openjdk.org/jeps/439` | Generational ZGC goals and trade-offs in JDK 21. |
| `https://openjdk.org/jeps/491` | JDK 24 removes nearly all `synchronized`-related virtual-thread pinning cases. |
| `https://openjdk.org/jeps/483` | Opt-in AOT class loading and linking in JDK 24 targets startup and warm-up time. |
| `https://openjdk.org/jeps/515` | AOT method profiles in JDK 25 target JIT warm-up time. |
| `https://openjdk.org/jeps/506` | Scoped values are final in JDK 25 and are intended for immutable context sharing. |
| `https://openjdk.org/jeps/519` | Compact object headers become a product feature in JDK 25 but are not enabled by default. |
| `https://openjdk.org/jeps/521` | Generational Shenandoah becomes a product feature in JDK 25 but remains opt-in. |

Do not generalize the Microsoft support dates to other vendors. Do not repeat
the workload-specific percentages shown in JEP 483 or JEP 519 as universal
performance expectations.

- [ ] **Step 2: Create the canonical document with upstream sources**

Create `docs/services/application-development/java-lts-version-selection/index.md`
with this front matter:

```yaml
---
services:
- application-development
official_sources:
- title: Support roadmap for the Microsoft Build of OpenJDK
  url: https://learn.microsoft.com/en-us/java/openjdk/support
- title: JDK 8 Project
  url: https://openjdk.org/projects/jdk8/
- title: JDK 8 Features
  url: https://openjdk.org/projects/jdk8/features
- title: JDK 17 Project
  url: https://openjdk.org/projects/jdk/17/
- title: JEPs in JDK 17 integrated since JDK 11
  url: https://openjdk.org/projects/jdk/17/jeps-since-jdk-11
- title: JEP 248 - Make G1 the Default Garbage Collector
  url: https://openjdk.org/jeps/248
- title: JEP 261 - Module System
  url: https://openjdk.org/jeps/261
- title: JEP 286 - Local-Variable Type Inference
  url: https://openjdk.org/jeps/286
- title: JEP 321 - HTTP Client API
  url: https://openjdk.org/jeps/321
- title: JDK 21 Project
  url: https://openjdk.org/projects/jdk/21/
- title: JEPs in JDK 21 integrated since JDK 17
  url: https://openjdk.org/projects/jdk/21/jeps-since-jdk-17
- title: JDK 25 Project
  url: https://openjdk.org/projects/jdk/25/
- title: JEPs in JDK 25 integrated since JDK 21
  url: https://openjdk.org/projects/jdk/25/jeps-since-jdk-21
- title: JEP 444 - Virtual Threads
  url: https://openjdk.org/jeps/444
- title: JEP 439 - Generational ZGC
  url: https://openjdk.org/jeps/439
- title: JEP 491 - Synchronize Virtual Threads without Pinning
  url: https://openjdk.org/jeps/491
- title: JEP 483 - Ahead-of-Time Class Loading and Linking
  url: https://openjdk.org/jeps/483
- title: JEP 515 - Ahead-of-Time Method Profiling
  url: https://openjdk.org/jeps/515
- title: JEP 506 - Scoped Values
  url: https://openjdk.org/jeps/506
- title: JEP 519 - Compact Object Headers
  url: https://openjdk.org/jeps/519
- title: JEP 521 - Generational Shenandoah
  url: https://openjdk.org/jeps/521
document_type: guide
status: current
verification_status: verified
sources_checked_at: 2026-09-16
last_verified: 2026-09-16
review_cycle_days: 180
applies_to:
- Java SE 8, 17, 21, 25
title: Java 8·17·21·25 LTS 선택과 현대화 가이드
description: Java 주요 LTS의 기능과 성능 특성을 비교하고 신규 도입 및 업그레이드 기준과 구현 패턴을 정리합니다.
technologies:
- java
tags:
- evaluate
- migrate
- optimize
---
```

Use exactly one H1 and organize the body under these H2 sections:

1. `먼저 내릴 결론`
2. `LTS를 해석할 때 주의할 점`
3. `버전별 누적 주요 변화`
4. `어떤 버전을 선택할까`
5. `최신 JDK가 성능에 유리할 수 있는 이유`
6. `업그레이드는 호환성과 현대화를 분리한다`
7. `버전 업그레이드 후 권장 구현 패턴`
8. `성능 검증 체크리스트`
9. `제약 사항`
10. `공식 참고 자료`

The opening decision table must give these conditional recommendations:

| Situation | Default choice | Reason |
|---|---|---|
| New service with a fully certified framework, libraries, agents, base image, and platform | Java 25 | Longest forward-looking support candidate and access to improvements delivered through 25 |
| Existing service where 25 support is not yet complete | Java 21 | Mature virtual-thread and pattern-matching baseline with broad ecosystem adoption |
| Dependency or product certification blocks 21 | Java 17 | Transitional compatibility target, not the preferred endpoint for unconstrained new work |
| Only legacy application/vendor constraints allow it | Java 8 | Maintain temporarily with a funded migration plan |

Immediately qualify the table: the selected JDK distribution's support policy,
not the version number alone, determines the actual support period.

The cumulative feature table must distinguish stable features from features
that require deliberate enablement:

| Version | Stable highlights to explain | Operational or migration highlights |
|---|---|---|
| 8 | lambda/method references, Stream, default methods, `Optional`, `java.time`, `CompletableFuture` | Metaspace replaces PermGen |
| 17 | module system, `var`, standard HTTP Client, switch expressions, text blocks, records, pattern matching for `instanceof`, sealed classes | G1 default since 9, production ZGC since 15, helpful NPEs, strong encapsulation of JDK internals |
| 21 | virtual threads, record patterns, pattern matching for `switch`, sequenced collections, UTF-8 by default | Generational ZGC; dynamic agent loading warning |
| 25 | unnamed variables/patterns, FFM API, Class-File API, Stream Gatherers, Scoped Values, module imports, flexible constructor bodies | improved virtual-thread `synchronized` behavior, AOT cache/tooling, compact object headers, opt-in Generational Shenandoah, richer JFR; Security Manager disabled and 32-bit x86 removed |

Add a separate note that Structured Concurrency, Stable Values, primitive
patterns, PEM encodings, and the Vector API are not final in JDK 25. Do not
recommend them as the default production migration pattern. State separately
that Generational Shenandoah and compact object headers are product features
but are not enabled by default.

Explain performance through mechanisms rather than promises:

- Newer HotSpot builds include cumulative JIT, GC, runtime, platform, and
  diagnostic work, but application results depend on workload and configuration.
- Virtual threads can increase throughput for high-concurrency blocking I/O by
  reducing the cost of one-thread-per-task; they do not make CPU-bound work
  faster and do not remove downstream capacity limits.
- Generational ZGC can reduce allocation stalls and memory overhead relative to
  non-generational ZGC for suitable workloads, but G1 can still be the better
  throughput or simplicity choice.
- JDK 24/25 AOT cache facilities target startup and warm-up, require a
  representative training workflow, and are not equivalent to native-image
  compilation.
- Compact object headers can improve object density when explicitly enabled,
  but JEP 519 says the layout is not the default.
- Language features mainly improve clarity, modeling, and maintainability;
  never present records or pattern matching as automatic runtime speedups.

Use a two-stage migration:

1. Compatibility: inventory the distribution/support policy, build tool,
   framework, dependencies, annotation processors, agents, native/JNI access,
   removed modules/APIs, internal JDK access, JVM flags, container image, and
   rollback artifact. Run the existing application on the target runtime before
   changing its programming model.
2. Modernization: adopt final language/API features in small reviewable changes,
   re-run correctness and load tests after each change, and keep preview
   features outside the default production path.

Include these complete code patterns.

Record for an immutable value:

```java
public record CustomerId(String value) {
    public CustomerId {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("value must not be blank");
        }
    }
}
```

Sealed domain model with exhaustive Java 21 matching:

```java
sealed interface PaymentResult permits Approved, Declined {}

record Approved(String approvalId) implements PaymentResult {}

record Declined(String reason) implements PaymentResult {}

final class PaymentMessages {
    private PaymentMessages() {}

    static String message(PaymentResult result) {
        return switch (result) {
            case Approved(var approvalId) -> "approved: " + approvalId;
            case Declined(var reason) -> "declined: " + reason;
        };
    }
}
```

Virtual-thread fan-out with an explicit downstream limit:

```java
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.Semaphore;

final class DownstreamCalls {
    private static final Semaphore DOWNSTREAM_LIMIT = new Semaphore(100);

    private DownstreamCalls() {}

    static String fetch(Callable<String> request) throws Exception {
        DOWNSTREAM_LIMIT.acquire();
        try {
            return request.call();
        } finally {
            DOWNSTREAM_LIMIT.release();
        }
    }

    static List<String> fetchAll(List<Callable<String>> requests)
            throws InterruptedException, ExecutionException {
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var futures = requests.stream()
                    .map(request -> executor.submit(() -> fetch(request)))
                    .toList();

            try {
                var results = new ArrayList<String>(futures.size());
                for (var future : futures) {
                    results.add(future.get());
                }
                return List.copyOf(results);
            } catch (InterruptedException error) {
                cancelAll(futures);
                Thread.currentThread().interrupt();
                throw error;
            } catch (ExecutionException error) {
                cancelAll(futures);
                throw error;
            }
        }
    }

    private static void cancelAll(List<? extends Future<?>> futures) {
        futures.forEach(future -> future.cancel(true));
    }
}
```

Explain that a connection pool, rate limiter, semaphore, or downstream quota
still controls real concurrency. Do not pool virtual threads themselves.
Require client-level connect, request, and read deadlines because interruption
and future cancellation do not replace I/O timeouts.

JDK 25 scoped value for immutable request context:

```java
final class RequestContext {
    private static final ScopedValue<String> TRACE_ID =
            ScopedValue.newInstance();

    private RequestContext() {}

    static void handle(String traceId, Runnable action) {
        ScopedValue.where(TRACE_ID, traceId).run(action);
    }

    static String traceId() {
        return TRACE_ID.get();
    }
}
```

State that framework-provided context propagation should remain authoritative
when it already defines the request context lifecycle. Scope the stable example
to callees on the same thread. State that ordinary threads and executor tasks
do not inherit bindings, while inheritance through `StructuredTaskScope`
depends on Structured Concurrency, which remains preview in JDK 25.

End with a measurement matrix requiring the same application artifact, traffic,
data set, CPU/memory limits, warm-up policy, framework and dependency versions,
and explicit JVM/GC flags. Compare throughput, errors, p50/p95/p99 latency,
startup, warm-up, CPU, RSS, heap, allocation rate, GC frequency, and GC pauses.
Require canary rollout and a rollback that restores both the JDK image and JVM
flags.

- [ ] **Step 3: Run source validation to prove the new upstream host is rejected**

Run:

```bash
python3.13 scripts/docs/validate_sources.py
```

Expected: FAIL and report `official source host is not allowed: openjdk.org`
for the new guide. This proves the document is discovered and the source
allowlist must be updated rather than bypassed.

- [ ] **Step 4: Allow the canonical OpenJDK source host**

Add `openjdk.org` to `official_source_hosts` in `docs-taxonomy.yml`, keeping the
existing hosts and `required_source_host: learn.microsoft.com` unchanged:

```yaml
official_source_hosts:
  - learn.microsoft.com
  - openjdk.org
  - kubernetes.io
  - www.cncf.io
  - cncf.io
  - github.com
  - modelcontextprotocol.io
  - py.sdk.modelcontextprotocol.io
  - prices.azure.com
  - www.rfc-editor.org
```

- [ ] **Step 5: Write a failing publication-boundary test**

In `tests/docs/test_pages_artifact.py`, after the real-site build, assert:

```python
assert not (site / "superpowers").exists()
search = json.loads(
    (site / "search" / "search_index.json").read_text(encoding="utf-8")
)
assert not any(
    entry["location"].startswith("superpowers/")
    for entry in search["docs"]
)
```

Run:

```bash
python3.13 -m pytest \
  tests/docs/test_pages_artifact.py::test_current_published_assets_survive_pages_artifact_hidden_exclusion \
  -q
```

Expected: FAIL because `site/superpowers/` exists before the exclusion is added.

- [ ] **Step 6: Exclude internal planning artifacts**

Append `superpowers/**` to `exclude_docs` in `mkdocs.yml`. Update
`test_mkdocs_keeps_navigation_and_search_metadata_driven` to expect:

```python
assert config["exclude_docs"].splitlines() == [
    "services/**/samples/**",
    "superpowers/**",
]
```

Run the failing test and the config contract test together. Expected: both pass.

- [ ] **Step 7: Run targeted document-contract tests**

Run:

```bash
python3.13 scripts/docs/validate_metadata.py
python3.13 scripts/docs/validate_sources.py
python3.13 scripts/docs/validate_links.py
python3.13 scripts/docs/validate_public_safety.py
python3.13 -m pytest tests/docs/test_content.py tests/docs/test_topics.py -q
```

Expected: every validator exits 0 and all selected tests pass. If a command
fails, use `superpowers:systematic-debugging` before changing the document or
validator.

- [ ] **Step 8: Review the rendered-content contract**

Check:

```bash
git diff --check
git diff -- docs-taxonomy.yml docs/services/application-development/java-lts-version-selection/index.md
```

Expected:

- one H1 and no skipped heading levels;
- no `topic_order`, `redirect_from`, sample, image, or manual navigation change;
- every Java 25 preview/incubator feature is visibly separated from stable
  recommendations;
- no universal performance percentage;
- no claim that all vendors share Microsoft's support dates;
- no secret, customer identifier, internal host, or private endpoint.

- [ ] **Step 9: Commit the guide and publication boundary**

```bash
git add docs-taxonomy.yml mkdocs.yml \
  docs/services/application-development/java-lts-version-selection/index.md \
  tests/docs/test_pages_artifact.py tests/docs/test_site_pipeline.py
git commit -m "docs(java): LTS 버전 선택과 현대화 가이드 추가" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Verify generated navigation, search, and compatibility output

**Files:**
- Verify: `docs/services/application-development/java-lts-version-selection/index.md`
- Verify: generated `site/services/application-development/java-lts-version-selection/index.html`
- Verify: generated service and explore indexes
- Modify: none unless a validation failure identifies a defect introduced by Task 1

**Interfaces:**
- Consumes: the canonical topic and taxonomy from Task 1.
- Produces: a strict MkDocs build in which the new topic appears once under `application-development`, is filterable by `java`, `evaluate`, `migrate`, and `optimize`, and does not alter the pre-Pages baseline mapping.

- [ ] **Step 1: Run the complete documentation test suite**

Run:

```bash
python3.13 -m pytest tests/docs -q
```

Expected: all tests pass.

- [ ] **Step 2: Run every repository-required validator**

Run:

```bash
python3.13 scripts/docs/validate_metadata.py
python3.13 scripts/docs/validate_sources.py
python3.13 scripts/docs/validate_links.py
python3.13 scripts/docs/validate_public_safety.py
mkdocs build --strict
python3.13 scripts/docs/validate_search_index.py
python3.13 scripts/docs/audit_pre_pages.py
```

Expected: every command exits 0. `mkdocs build --strict` creates the canonical
HTML page, and the pre-Pages audit accepts the increased current document count
without changing the fixed baseline inventory.

- [ ] **Step 3: Verify the generated page and discovery metadata**

Run:

```bash
test -f site/services/application-development/java-lts-version-selection/index.html
grep -q "Java 8·17·21·25 LTS 선택과 현대화 가이드" \
  site/services/application-development/java-lts-version-selection/index.html
grep -q "java-lts-version-selection" site/services/application-development/index.html
git status --short
```

Expected: the page exists, its H1 text is rendered, the application-development
service index links to it, and generated `site/` output is ignored rather than
staged.

- [ ] **Step 4: Record final verification without committing generated files**

Run:

```bash
git status --short
git --no-pager log -3 --oneline
```

Expected: no uncommitted source changes remain, `site/` is absent from status,
and the guide commit follows the committed design and plan history.
