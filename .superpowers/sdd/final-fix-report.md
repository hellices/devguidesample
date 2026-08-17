# Final Fix Report — Azure Monitor Dynamic Threshold branch

## Scope
Resolved the requested final-review set in one pass for C1, I1-I6, and the confirmed M1-M9 items without changing the three existing static alert rules and without attaching an Action Group to the dynamic rule.

## Fixes applied
- **C1 / M1 / M7:** Made Phase 2 independently resumable by repeating `cd monitor/sre-agent-event-lab` and `source ./scripts/lab-env.sh`, removing the `CONTAINER_APP_FQDN` alias, switching the load generator to `${APP_FQDN}`, and exporting `BASELINE_WEB_TEST_NAME` plus `DYNAMIC_THRESHOLD_ALERT_NAME` from `scripts/lab-env.sh`.
- **I1 / reviewer follow-up:** Reused the S2 revision-readiness pattern in Phase 2, including `OLD_REVISION`, new active/healthy revision polling, and an `INJECTED` guard so the wait/load path only runs after a successful latency injection.
- **I2:** Reused the S2 recovery-verification pattern: recovery now fails loudly, waits for a new healthy revision, and verifies `/api/orders` with `curl -w '%{time_total}s %{http_code}'`.
- **I3:** Documented the scenario-serialization precondition with `python3 scripts/lab_state.py show | jq -e ...`, required no `running`/`failed` scenarios in `evidence/state.json`, and warned that the unchanged static `alert-sre-lab-s2-latency` rule may also fire and open an Azure SRE Agent investigation.
- **I4 / M3 / M9:** Changed `infra/dynamic-threshold-case.bicep` from `timeAggregation: 'Maximum'` to `timeAggregation: 'Average'`, updated tests, and documented that the 2-of-4 evaluations overlap and that Log Search Dynamic Thresholds do not support 1-minute evaluation.
- **I5 / M2 / official-image policy:** Downloaded the official Microsoft chart to `monitor/sre-agent-event-lab/assets/official/dynamic-threshold-preview-chart.png`, referenced it locally from the English brief and Korean hands-on guide, kept explicit source attribution, added tests so this file is covered by the repository's local-official-image policy, and normalized prose links to locale-less Learn URLs while keeping working pricing URLs elsewhere unchanged.
- **I6:** Renamed the stale Azure SRE Agent link label to the hands-on case and added a reciprocal concept link from `dynamic-thresholds.md` back to `../azure-monitor-dynamic-thresholds-brief.md`.
- **M4:** Added a one-line rationale in `dynamic-threshold-case.bicep` for using one web-test location because `DurationMs` is measured server-side and the lab wants dense baseline samples without multiplying probe traffic.
- **M5:** Reconciled the brief's Preview Chart guidance with the ARM/Bicep-enabled shadow-rule flow by stating that portal preview-before-enable applies where supported, while this repository deploys the log-search rule enabled only in shadow mode and reviews the chart after deployment.
- **M6:** Refreshed `.azure/deployment-plan.md` inventory and verification counts to four alert rules, one web test, 520 tests, and six Bicep builds.
- **M8:** Added the telemetry-age-versus-rule-age caveat: the telemetry query only proves data age, not that a re-created rule has already relearned.

## Files changed
- `.azure/deployment-plan.md`
- `monitor/azure-monitor-dynamic-thresholds-brief.md`
- `monitor/azure-sre-agent.md`
- `monitor/sre-agent-event-lab/assets/official/dynamic-threshold-preview-chart.png`
- `monitor/sre-agent-event-lab/dynamic-thresholds.md`
- `monitor/sre-agent-event-lab/infra/dynamic-threshold-case.bicep`
- `monitor/sre-agent-event-lab/infra/tests/test_dynamic_threshold_case.py`
- `monitor/sre-agent-event-lab/scripts/lab-env.sh`
- `monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py`
- `monitor/sre-agent-event-lab/scripts/tests/test_dynamic_threshold_case_docs.py`
- `monitor/sre-agent-event-lab/scripts/tests/test_lab_env.py`
- `monitor/sre-agent-event-lab/scripts/tests/test_lab_guides.py`

## RED evidence
1. Targeted regression suite before implementation:
   - Command: `app/.venv/bin/python -m pytest infra/tests/test_dynamic_threshold_case.py infra/tests/test_azd_project.py scripts/tests/test_dynamic_threshold_case_docs.py scripts/tests/test_lab_guides.py scripts/tests/test_azd_env.py -q`
   - Result: **14 failed, 105 passed**.
   - Representative failures: missing `timeAggregation: 'Average'`, missing Phase 2 shell preamble, raw `azd env get-value` lookups still present, hot-linked Microsoft chart still present, missing reciprocal brief link, and stale deployment-plan build count.
2. `lab-env.sh` export coverage before binding the new azd outputs:
   - Command: `app/.venv/bin/python -m pytest scripts/tests/test_lab_env.py -q`
   - Result: **2 failed, 11 passed**.
   - Failures: `BASELINE_WEB_TEST_NAME` and `DYNAMIC_THRESHOLD_ALERT_NAME` were not exported/resolved.
3. Post-review regression for the injection guard:
   - Command: `app/.venv/bin/python -m pytest scripts/tests/test_dynamic_threshold_case_docs.py::test_case_reuses_s2_readiness_and_recovery_patterns -q`
   - Result: **1 failed**.
   - Failure: `INJECTED=0` / guarded readiness-wait pattern was absent from Phase 2.

## GREEN evidence
1. `app/.venv/bin/python -m pytest infra/tests/test_dynamic_threshold_case.py infra/tests/test_azd_project.py scripts/tests/test_dynamic_threshold_case_docs.py scripts/tests/test_lab_guides.py scripts/tests/test_azd_env.py -q`
   - Result: **119 passed in 8.47s**
2. `app/.venv/bin/python -m pytest app infra scripts/tests -q`
   - Result: **520 passed, 27 warnings in 131.69s (0:02:11)**
3. `bash -n scripts/*.sh`
   - Result: **passed**
4. `az bicep build --file infra/dynamic-threshold-case.bicep --stdout >/dev/null`
   - Result: **passed**
5. `az bicep build --file infra/main.bicep --stdout >/dev/null`
   - Result: **passed**
6. Local links and official URLs validation via `python3` checker over the changed docs (`monitor/azure-monitor-dynamic-thresholds-brief.md`, `monitor/azure-sre-agent.md`, `monitor/sre-agent-event-lab/dynamic-thresholds.md`)
   - Result: **all changed local links resolved; all checked URLs returned HTTP 200**
7. `git diff --check`
   - Result: **passed**
8. Additional consistency check used to support the refreshed deployment-plan count:
   - Command: `for file in infra/main.bicep infra/lab.bicep infra/workload.bicep infra/observability.bicep infra/alerts.bicep infra/dynamic-threshold-case.bicep; do az bicep build --file "$file" --stdout >/dev/null || exit 1; done`
   - Result: **all six Bicep templates passed**

## Self-review
- Kept the three static PT1M alert rules unchanged.
- Kept the dynamic rule in shadow mode with `actionGroups: []`; no Action Group parameter was added.
- Preserved the regression guard for the 5-minute Dynamic Threshold minimum and strengthened docs/tests around Phase 2 resumability, official assets, and azd output bindings.
- Requested a review pass before commit; it identified one additional high-confidence issue (unguarded revision wait after failed injection), which was fixed and re-tested RED→GREEN.

## Concerns
- The broad pytest run still emits **27 existing FastAPI deprecation warnings** from a dependency path (`asyncio.iscoroutinefunction`); no new warnings were introduced by this change.
- This work intentionally does **not** fabricate live alert results or screenshots; the multi-day Dynamic Threshold behavior remains documented and test-guarded rather than re-recorded here.
## 2026-08-17 final re-review fix pass

### Exact fixes
- Removed tracked `.superpowers/sdd/task-2-report.md` from the branch diff with `git rm --cached`, leaving ignored local `.superpowers/` state unmanaged.
- Reworked Phase 2 in `monitor/sre-agent-event-lab/dynamic-thresholds.md` to remove every `exit` from pasted bash blocks and follow the S2 fail-loud guard-flag pattern.
- Added a focused regression assertion that no Phase 2 bash block contains an `exit` shell command token.
- Added explicit rationale that Phase 2 checks scenario state only and intentionally does not call `begin-run` because that would overwrite existing S2 scoring/evidence state; documented the ~20 minute no-other-scenario window.
- Made `wait_for_new_healthy_revision` keep `NEW_REVISION` and `STATE` local.
- Made `restore_delay` idempotent by setting `INJECTED=0` immediately after successful recovery verification.
- Hardened both baseline revision lookups so failed/empty `az containerapp show` results fail loudly and block unsafe injection/recovery follow-up.
- Updated `.azure/deployment-plan.md` to quote `1분 주기 정적 로그 검색 경고 규칙 3개` exactly.

### RED evidence
- `cd monitor/sre-agent-event-lab && app/.venv/bin/python -m pytest scripts/tests/test_dynamic_threshold_case_docs.py scripts/tests/test_lab_guides.py -q`
  - Result before fixes: `4 failed, 77 passed`
  - New failures covered: Phase 2 `exit` usage, missing `begin-run` rationale, missing local revision locals / restore idempotence note, stale deployment-plan quote.
- `cd monitor/sre-agent-event-lab && app/.venv/bin/python -m pytest scripts/tests/test_dynamic_threshold_case_docs.py -q`
  - Result after reviewer-driven regression additions but before final guard fix: `1 failed, 14 passed`
  - Failure covered missing fail-loud baseline revision lookup guidance.

### GREEN evidence
- `cd monitor/sre-agent-event-lab && app/.venv/bin/python -m pytest scripts/tests/test_dynamic_threshold_case_docs.py scripts/tests/test_lab_guides.py -q`
  - Result: `82 passed`
- `cd monitor/sre-agent-event-lab && app/.venv/bin/python -m pytest app infra scripts/tests -q`
  - Result: `525 passed, 27 warnings` (existing FastAPI deprecation warnings only)
- `cd monitor/sre-agent-event-lab && bash -n scripts/*.sh`
  - Result: success
- Syntax-checked every `dynamic-thresholds.md` bash block with `bash -n`
  - Result: `8 bash blocks syntax OK`
- `az bicep build --file infra/main.bicep --stdout >/dev/null`
  - Result: success
- `git diff --check`
  - Result: success
- `git diff --name-only b378da83594f89f81deea40f1fadaaab0db891ad -- .superpowers`
  - Result: empty (`No tracked .superpowers paths remain in diff from base`)

### Commands and results
- `git rm --cached .superpowers/sdd/task-2-report.md`
  - Result: removed from index only.
- Requested read-only review on the final diff.
  - Review found one Important issue (unchecked baseline revision lookups) and one Minor issue (regex should catch bare `exit`), both fixed in this pass.
- Re-ran the full required verification suite after addressing review feedback.
  - Result: all required commands passed.

### Self-review
- Confirmed Phase 2 still preserves the earlier required fixes: preamble, Average aggregation references, local official image usage, readiness/recovery checks, no Action Group, and unchanged static alert rules.
- Confirmed the new guard flow blocks unsafe follow-up after failed state check, failed baseline lookup, failed revision wait, failed injection, or failed restore, while keeping the operator shell alive with stderr guidance.
- Confirmed the ignored local report path remains outside the tracked merge set.

## 2026-08-17 final-review minor fixes

### Exact fixes
- Updated `.azure/deployment-plan.md` recorded test counts from 520 to 525.
- Removed the stale claim that `dynamic-thresholds.md` carries the one-minute cadence annotation; the note now points to `validation-results.md`.
- Reworded the legacy Logic App/default incident-platform claim to reference only `validation-results.md`.
- Strengthened `monitor/sre-agent-event-lab/scripts/tests/test_dynamic_threshold_case_docs.py` so the Phase 2 exit detector catches line-leading `exit` plus inline forms like `|| exit 1` and `; exit 1`.

### RED evidence
- Old-regex probe before the fix:
  - Command: `python3 - <<'PY'` with `re.compile(r'(?m)^\s*exit(?:\s|;|$)')`
  - Result: `cmd || exit 1` -> `False`, `cmd ; exit 1` -> `False`
- Pre-wrap plan-string check:
  - Command: `app/.venv/bin/python -m pytest scripts/tests/test_lab_guides.py::test_deployment_plan_quotes_the_current_static_alert_callout scripts/tests/test_dynamic_threshold_case_docs.py -q`
  - Result before the final quote fix: `1 failed, 19 passed`

### GREEN evidence
- Focused validation after the fixes:
  - Command: `app/.venv/bin/python -m pytest scripts/tests/test_lab_guides.py::test_deployment_plan_quotes_the_current_static_alert_callout scripts/tests/test_dynamic_threshold_case_docs.py -q`
  - Result: `20 passed`
- Full lab suite:
  - Command: `app/.venv/bin/python -m pytest app/tests infra/tests scripts/tests`
  - Result: `529 passed, 27 warnings`
- Whitespace check:
  - Command: `git diff --check`
  - Result: passed

## 2026-08-17 deployment-plan count correction

- Command: `cd /Users/hwang-inhwan/workspace/devguidesample/.worktrees/azure-monitor-dynamic-threshold-brief && app/.venv/bin/python -m pytest monitor/sre-agent-event-lab/scripts/tests/test_lab_guides.py::test_deployment_plan_quotes_the_current_static_alert_callout -q && git diff --check`
- Result: `1 passed in 0.03s` and `passed`
