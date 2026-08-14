"""Contract tests for the ordered lab walkthrough.

The README is the quickstart an operator reads first, and `guides/` holds
the step-by-step documents it hands off to. These tests check behaviour a
reader depends on -- that the commands are the ones `lab.sh` really
accepts, in the order `lab_state.py` really enforces; that every path,
link and screenshot resolves; and that nothing here asks anyone to paste a
credential into a file or an environment variable.
"""
import re
from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]
LAB_ROOT = REPO_ROOT / "monitor" / "sre-agent-event-lab"
README = LAB_ROOT / "README.md"
GUIDES = LAB_ROOT / "guides"
OFFICIAL_ASSETS = LAB_ROOT / "assets" / "official"
RUNBOOK = LAB_ROOT / "runbooks" / "incident-response.md"
LAB_SH = LAB_ROOT / "scripts" / "lab.sh"
VALIDATION_RESULTS = LAB_ROOT / "validation-results.md"
DYNAMIC_THRESHOLDS = LAB_ROOT / "dynamic-thresholds.md"
RESULTS_GUIDE = LAB_ROOT / "guides" / "05-results.md"
DEPLOYMENT_PLAN = REPO_ROOT / ".azure" / "deployment-plan.md"

# The table `infra/alerts.bicep` actually queries for each scenario --
# workspace schema, not the legacy Application Insights component schema.
SCENARIO_GUIDE_TABLES = {
    "02-scenario-s1.md": "AppRequests",
    "03-scenario-s2.md": "AppRequests",
    "04-scenario-s3.md": "AppDependencies",
}

GUIDE_NAMES = (
    "01-agent-setup.md",
    "02-scenario-s1.md",
    "03-scenario-s2.md",
    "04-scenario-s3.md",
    "05-results.md",
)

SCENARIO_GUIDES = {
    "02-scenario-s1.md": "s1",
    "03-scenario-s2.md": "s2",
    "04-scenario-s3.md": "s3",
}

# The screenshots selected from the live Learn articles, each tied to one
# portal action an operator performs by hand. Anything the lab can prove
# with its own captured evidence is deliberately not copied here.
GUIDE_SCREENSHOTS = {
    "portal-setup-status-bar.png": (
        "https://learn.microsoft.com/azure/sre-agent/complete-setup"
    ),
    "portal-complete-setup-page.png": (
        "https://learn.microsoft.com/azure/sre-agent/complete-setup"
    ),
    "portal-incident-response-plans-list.png": (
        "https://learn.microsoft.com/azure/sre-agent/automate-incidents"
    ),
    "portal-response-plan-autonomy-step.png": (
        "https://learn.microsoft.com/azure/sre-agent/automate-incidents"
    ),
}

# Every keyword is a string or state actually visible in the downloaded
# screenshot, so alt text that drifts from the picture fails here.
SCREENSHOT_ALT_KEYWORDS = {
    "portal-setup-status-bar.png": (
        "6 sources not configured",
        "Complete setup",
        "Code",
        "Logs",
        "Deployments",
        "Incidents",
        "Azure resources",
        "Knowledge files",
        "Builder",
    ),
    "portal-complete-setup-page.png": (
        "Quickstart",
        "Full setup",
        "Code",
        "Logs",
        "Recommended",
    ),
    "portal-incident-response-plans-list.png": (
        "Builder",
        "Incident response plans",
        "Azure Monitor is connected",
        "Autonomy level",
        "Autonomous",
        "On",
    ),
    "portal-response-plan-autonomy-step.png": (
        "Review (Default)",
        "Autonomous",
        "Save response plan",
        "Save",
    ),
}

# Claims the picture does not support. The two response-plan screenshots
# both show `Autonomous`, and this lab runs in `Review`: alt text may never
# describe them as showing the mode the lab asks for.
FORBIDDEN_ALT_CLAIMS = {
    "portal-incident-response-plans-list.png": ("Review 모드로", "Review로 표시"),
    "portal-response-plan-autonomy-step.png": ("Review가 선택", "Review를 선택한 상태"),
    "portal-complete-setup-page.png": ("Azure resources", "Knowledge files"),
}

SECRET_ASSIGNMENTS = (
    "GITHUB_PAT=",
    "OAUTH_TOKEN=",
    "CLIENT_SECRET=",
    "ACCESS_TOKEN=",
    "AZURE_CLIENT_SECRET=",
)

FIXED_SUBSCRIPTION_ID = "95933ae5-0201-4a21-a1fc-8051a7437982"
FIXED_RESOURCE_GROUP = "rg-sre-agent-event-lab-krc"


def guide_paths():
    return [GUIDES / name for name in GUIDE_NAMES]


def all_docs():
    return [README] + guide_paths()


def joined_docs() -> str:
    return "\n".join(path.read_text() for path in all_docs())


def images(text: str):
    """(alt, target) for every rendered image, Markdown or HTML."""
    markdown = re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", text)
    html = [("", target) for target in re.findall(r"<img[^>]*\ssrc=[\"']([^\"']+)", text)]
    return markdown + html


def body_sentences(markdown: str, minimum_length: int = 30):
    """Substantive body sentences, with code, images and captions removed."""
    markdown = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    markdown = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown)

    fragments = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ">")):
            continue
        if re.fullmatch(r"\|[\s:\-|]+\|", line):
            continue
        cells = line.strip("|").split("|") if line.startswith("|") else [line]
        for cell in cells:
            cell = re.sub(r"^[-*+]\s+", "", cell.strip())
            cell = re.sub(r"^\d+\.\s+", "", cell)
            cell = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cell)
            cell = cell.replace("**", "").replace("`", "").strip()
            if cell:
                fragments.append(cell)

    sentences = []
    for fragment in fragments:
        for sentence in re.split(r"(?<=다\.)\s+", fragment):
            sentence = re.sub(r"\s+", " ", sentence).strip()
            if len(sentence) >= minimum_length and re.search(r"(다|요)\.$", sentence):
                sentences.append(sentence)
    return sentences


def blocks(text: str):
    return [block for block in re.split(r"\n\s*\n", text) if block.strip()]


# --- README quickstart ---------------------------------------------------


def test_readme_is_azd_first_and_ordered():
    text = README.read_text()
    commands = [
        "azd env new",
        "azd up",
        "./scripts/lab.sh doctor",
        "./scripts/lab.sh baseline",
        "./scripts/lab.sh acknowledge agent-setup",
        "./scripts/lab.sh run s1",
        "./scripts/lab.sh capture s1",
        "./scripts/lab.sh run s2",
        "./scripts/lab.sh capture s2",
        "./scripts/lab.sh run s3",
        "./scripts/lab.sh capture s3",
        "./scripts/lab.sh score",
        "azd down --purge",
    ]
    positions = [text.index(command) for command in commands]
    assert positions == sorted(positions)


def test_readme_warns_about_cost_and_teardown_before_the_first_azure_command():
    text = README.read_text()

    warning = re.search(r"(과금|비용)", text)
    assert warning, "the README must state that the lab bills real resources"
    assert warning.start() < text.index("azd up")
    assert text.index("azd down --purge") > text.index("azd up")
    for driver in ("Container Apps", "Log Analytics", "Azure SRE Agent"):
        assert driver in text, driver


def test_readme_states_one_minute_alert_evaluation():
    """The `QueryNotContainKnownTable` failure came from the legacy
    Application Insights `requests`/`dependencies` schema on the component
    scope, not from the one-minute cadence: `az deployment group validate`
    accepts `evaluationFrequency: PT1M` for the workspace-scoped
    `AppRequests`/`AppDependencies` rules. The cost callout must state the
    one-minute cadence `infra/alerts.bicep` actually deploys.
    """
    text = README.read_text()

    assert "1분 주기 로그 검색 경고 규칙 3개" in text
    assert "5분 주기 로그 검색 경고 규칙" not in text


def test_dynamic_thresholds_guide_states_one_minute_static_evaluation():
    """The Static Threshold section of dynamic-thresholds.md describes the
    deployed infra/alerts.bicep rules, which evaluate every minute over a
    five-minute window. The separate, still-true statement that Log Search
    *dynamic* thresholds do not support one-minute evaluation stays.
    """
    text = DYNAMIC_THRESHOLDS.read_text()

    assert "- evaluation: 1분" in text
    assert "- evaluation: 5분" not in text
    assert "Log Search dynamic threshold는 1분 evaluation을 지원하지 않는다." in text


def test_dynamic_thresholds_sections_are_numbered_without_gaps():
    """A reader following "8절 참고" would find no section 8: the document
    jumped from 7 to 9. Numbered top-level sections must be consecutive."""
    numbers = [
        int(match)
        for match in re.findall(
            r"^## (\d+)\. ", DYNAMIC_THRESHOLDS.read_text(), re.MULTILINE
        )
    ]

    assert numbers, "dynamic-thresholds.md has no numbered sections"
    assert numbers == list(range(1, len(numbers) + 1)), numbers


def test_deployment_plan_status_matches_what_was_actually_deployed():
    """The plan carried both a `Validated` status *and* the pre-deployment
    notes it was written with: "Ready for Validation", "no resources
    deployed", a fresh environment still being needed and an unchecked
    provision preview. A live `azd up`/`azd down --purge` cycle has since
    run, so those cannot both be true. `Validated` is kept for the base azd
    deployment only, and it has to say so on the status line itself.
    """
    text = DEPLOYMENT_PLAN.read_text()

    status = re.search(r"^> \*\*Status:\*\* (.+)$", text, re.MULTILINE)
    assert status, "the plan has no status line"
    assert status.group(1).startswith("Validated — base azd deployment only"), (
        status.group(1)
    )

    for stale in (
        "Ready for Validation",
        "no resources deployed",
        "a fresh environment is needed",
    ):
        assert stale not in text, stale
    assert "- [ ]" not in text, (
        "an unchecked preflight item contradicts the recorded live deployment"
    )


def test_deployment_plan_does_not_claim_the_manual_scenario_sequence_ran():
    """The operator said they would connect the Agent and run S1/S2/S3 one
    by one themselves. Only the pre-acknowledgement refusal (`lab.sh run s1`
    rejected before `acknowledge agent-setup`) was exercised, so the plan
    must record the scenario sequence as pending -- in the Live Deployment
    Proof table, where a reader looks for what the deployment proved.
    """
    text = DEPLOYMENT_PLAN.read_text()

    proof = text.split("## Live Deployment Proof", 1)
    assert len(proof) == 2, "the plan has no Live Deployment Proof section"
    proof_table = proof[1]

    pending = re.search(r"^\| Manual scenario sequence \| (.+) \|$", proof_table, re.MULTILINE)
    assert pending, "no Live Deployment Proof row for the pending manual sequence"
    row = pending.group(1)
    assert row.startswith("Pending"), row
    for expected in ("S1", "S2", "S3", "capture", "score", "one by one"):
        assert expected in row, expected

    assert "have not been run" in text
    assert "pre-acknowledgement" in text or "pre-ack" in text


def test_deployment_plan_records_one_current_test_and_bicep_count():
    """The preflight list still claimed the 460-test, three-template run
    that predates the workspace-schema fix, while Section 7 records the
    current one. Two different suite sizes in one plan is exactly the kind
    of drift this document is read for.
    """
    text = DEPLOYMENT_PLAN.read_text()

    preflight = re.search(r"Build Verification — (\d+) tests and (\w+) Bicep builds", text)
    assert preflight, "the preflight list records no build verification count"
    section_seven = re.search(r"\| (\d+) passed", text)
    assert section_seven, "Section 7 records no test count"

    assert preflight.group(1) == section_seven.group(1), (
        preflight.group(1),
        section_seven.group(1),
    )
    assert int(preflight.group(1)) >= 472, "the recorded suite shrank"
    assert preflight.group(2) == "five", "five Bicep templates are built, not three"
    assert "460 tests" not in text


def test_scenario_guides_document_the_critical_recovery_failure_path():
    """`run-scenario.sh` reverts the injected fault from an EXIT trap, and
    that revert can itself fail (a rejected `az containerapp update`, a
    revision that never becomes ready, a refused role restore). It then
    prints `CRITICAL:` and exits non-zero with the fault still live, so each
    scenario guide has to tell the operator to revert it by hand instead of
    starting the next scenario.
    """
    for name in SCENARIO_GUIDES:
        recovery = (GUIDES / name).read_text().split("## 복구 확인", 1)
        assert len(recovery) == 2, name
        section = recovery[1].split("\n## ", 1)[0]
        assert "CRITICAL" in section, name
        assert "수동" in section or "직접 되돌" in section, name


def test_validation_results_opens_by_dating_itself_to_the_pre_azd_lab():
    """Everything in this report -- the fixed subscription, the
    `rg-sre-agent-event-lab-krc` resource group, the Logic App bridge --
    comes from a hand-built lab that ran before the azd rewrite. A reader
    who takes the header at face value goes looking for resources `azd up`
    never creates, so the note has to be at the top, above the numbers, not
    inferred from a bridge caveat 240 lines down.
    """
    text = VALIDATION_RESULTS.read_text()
    header = text.split("\n## ", 1)[0]
    note = "\n".join(block for block in blocks(header) if block.lstrip().startswith(">"))

    assert note, "validation-results.md opens with no note about what it records"
    assert "azd" in note
    assert re.search(r"(이전|예전|과거)", note), note
    assert FIXED_RESOURCE_GROUP in note or FIXED_SUBSCRIPTION_ID in note, note
    assert re.search(r"(현재|지금).{0,40}(실습|lab)", note), note


def test_dynamic_thresholds_labels_the_logic_app_event_path_as_legacy():
    """The recommended-settings section proposed the Action Group → Logic
    App → HTTP Trigger chain as *the* event path. That bridge is the
    historical one this lab no longer deploys; naming it without the label
    tells an operator to rebuild it for a dynamic rule that should ride the
    same Azure Monitor incident platform the standard exercise uses.
    """
    text = DYNAMIC_THRESHOLDS.read_text()

    logic_app_lines = [line for line in text.splitlines() if "Logic App" in line]
    assert logic_app_lines, "the document no longer mentions the bridge at all"
    for line in logic_app_lines:
        assert re.search(r"(레거시|legacy)", line), line
    assert "incident platform" in text
    assert re.search(r"(기본|표준).{0,60}incident platform", text) or re.search(
        r"incident platform.{0,60}(기본|표준)", text
    ), "the standard Azure Monitor path is not named as the default"


def test_autonomy_screenshots_warn_that_the_lab_must_choose_review():
    """Both response-plan screenshots come from the Learn tutorial and show
    `Autonomous`, which is the mode this lab must not use: the scripts own
    fault injection and recovery, so an autonomous Agent and the scripts
    would revert the same resources at once. The alt text may not claim the
    picture shows `Review` (see FORBIDDEN_ALT_CLAIMS), which leaves the
    caption as the only place that can warn a reader copying the screen.
    """
    autonomy_screenshots = (
        "portal-incident-response-plans-list.png",
        "portal-response-plan-autonomy-step.png",
    )
    captions = {}
    for path in guide_paths():
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"!\[[^\]]*\]\(\.\./assets/official/([^)]+)\)", line.strip())
            if not match:
                continue
            caption = []
            for following in lines[index + 1 :]:
                stripped = following.strip()
                if stripped.startswith(">"):
                    caption.append(stripped)
                elif stripped:
                    break
            captions[match.group(1)] = "\n".join(caption)

    for name in autonomy_screenshots:
        caption = captions.get(name, "")
        assert caption, name
        assert "Autonomous" in caption, name
        assert "Review" in caption, name
        assert re.search(r"(주의|경고)", caption), (name, caption)
        assert re.search(r"(고릅니다|선택합니다|골라야|선택해야)", caption), (name, caption)


def test_scenario_guides_say_a_rerun_retires_the_previous_attempt():
    """`run-scenario.sh` records the new attempt before it injects
    anything, which clears whatever the previous attempt recorded --
    including a `conclusion` that was already unblocking the next
    scenario. An operator who re-runs a captured scenario to collect a
    second capture has to know the gate closes again at that moment, and
    stays closed if the re-run dies before it recovers.
    """
    for name, scenario in SCENARIO_GUIDES.items():
        text = (GUIDES / name).read_text()
        rerun = [line for line in text.splitlines() if "다시" in line or "새 시도" in line]
        assert rerun, name
        joined = "\n".join(rerun)
        assert "{0}_captured".format(scenario) in joined, name
        assert re.search(r"(지워|지웁|초기화|사라)", joined), (name, joined)


def test_validation_results_keeps_the_one_minute_static_run_and_explains_it():
    """The recorded S1/S2/S3 run used a one-minute static threshold. That
    result stays plausible because the later live failure was the legacy
    Application Insights schema on the component scope, not the cadence, and
    the report must say so instead of leaving readers to assume the run used
    an unsupported configuration.
    """
    text = VALIDATION_RESULTS.read_text()

    assert "1분 evaluation의 static threshold" in text
    assert "QueryNotContainKnownTable" in text
    assert "AppRequests" in text


def test_scenario_guides_name_the_workspace_table_not_the_legacy_schema():
    """`infra/alerts.bicep` scopes every rule to the Log Analytics workspace
    and queries the workspace-schema `AppRequests`/`AppDependencies` tables.
    The legacy Application Insights component-scope names (`requests`,
    `dependencies`) are not tables there -- they are functions over the
    workspace tables that reject one-minute evaluation (see
    dynamic-thresholds.md and validation-results.md). Each scenario guide's
    "Azure에서 발생하는 변화" table must name the table the deployed alert
    rule actually queries, not the legacy schema, so a reader who only
    reads the guide never learns a query the rule cannot run.
    """
    for name, table in SCENARIO_GUIDE_TABLES.items():
        text = (GUIDES / name).read_text()
        assert "`{0}`".format(table) in text, name
        assert "`requests`" not in text, name
        assert "`dependencies`" not in text, name


def test_runbook_distinguishes_the_alert_scope_from_the_workload_impact():
    """The alert rules are scoped to the Log Analytics workspace
    (`infra/alerts.bicep`'s `scopes`/`targetResourceTypes:
    Microsoft.OperationalInsights/workspaces`), so Azure Monitor's own
    "affected resource" for the alert *is* that workspace -- not the
    Container App. The `AppRequests`/`AppDependencies`/`AppExceptions` rows
    the runbook queries next additionally carry a `_ResourceId` column that
    resolves to the Application Insights component, one indirection closer
    but still not the workload. Neither of those is the incident's impact
    scope: the runbook must tell the Agent to identify the actually
    affected Container App/service from the telemetry itself
    (`AppRoleName`/`Name`), and must say not to report the alert's own
    scope as that impact.
    """
    text = RUNBOOK.read_text()

    assert "Log Analytics workspace" in text
    assert "_ResourceId" in text
    assert "AppRoleName" in text
    assert re.search(r"[Nn]ot (the )?(Container App|workload)", text)
    assert re.search(r"[Dd]o not report .*workspace.* as", text)


def test_results_guide_impact_scope_rejects_the_alert_target_as_the_answer():
    """Scoring guidance for `impact_scope` must not credit an answer that
    only restates the alert rule's own scope (the Log Analytics workspace)
    or the `_ResourceId` telemetry column (the Application Insights
    component) -- both are one or two indirections away from the actually
    affected Container App/service, which is what the criterion scores.
    """
    text = RESULTS_GUIDE.read_text()

    assert "impact_scope" in text
    assert "Log Analytics workspace" in text
    assert "_ResourceId" in text
    assert "AppRoleName" in text


def test_deployment_plan_does_not_overclaim_appinsights_resource_id_usage():
    """`appInsightsResourceId` (observability -> lab -> main.bicep) remains
    an output for backward compatibility, but no lab script and no module
    reads it anymore: `infra/alerts.bicep` takes `workspaceResourceId`, and
    every script that queries telemetry reads `workspaceCustomerId`
    (`scripts/common.sh`'s `deployment_output`/`load_lab_config`). The plan
    must not claim scripts still consume `appInsightsResourceId`.
    """
    text = DEPLOYMENT_PLAN.read_text()

    assert "appInsightsResourceId" in text
    assert "workspaceCustomerId" in text
    assert "scripts that read it" not in text
    assert not re.search(r"appInsightsResourceId[^\n.]*scripts that read", text)


def test_readme_is_a_quickstart_not_the_full_walkthrough():
    """Scenario, capture and scoring detail belongs in the guides."""
    text = README.read_text()

    assert len(text.splitlines()) <= 200, "README is no longer a quickstart"
    for moved in ("impact_scope", "conclusion-review.json", "FAILURE_MODE=http500"):
        assert moved not in text, moved
    assert "impact_scope" in (GUIDES / "05-results.md").read_text()


def test_readme_links_every_numbered_guide_in_order():
    text = README.read_text()

    positions = [text.index("guides/{0}".format(name)) for name in GUIDE_NAMES]
    assert positions == sorted(positions)


def test_readme_troubleshooting_index_routes_to_doctor_and_guides():
    text = README.read_text()
    heading = "## 문제 해결"

    assert heading in text
    section = text.split(heading, 1)[1]
    assert "lab.sh doctor" in section
    assert "guides/" in section


def test_manual_steps_distinguish_product_path_from_old_bridge():
    text = README.read_text()
    assert "Azure Monitor incident platform" in text
    assert "기본 실습에는 Logic App bridge를 배포하지 않습니다" in text


def test_logic_app_bridge_is_only_described_as_legacy():
    for path in all_docs():
        for block in blocks(path.read_text()):
            if "Logic App" not in block:
                continue
            assert "레거시" in block, (path.name, block)


def test_incident_platform_path_is_the_documented_default():
    setup = (GUIDES / "01-agent-setup.md").read_text()

    assert "Builder > Incident platform" in setup
    assert "Azure Monitor" in setup
    plan_index = setup.index("Review")
    assert setup.index("Builder > Incident platform") < plan_index


def test_azuresre_dev_audience_fact_is_preserved_as_legacy_history():
    """Finding #3: the Task 6 rewrite deleted a verified fact (the HTTP
    Trigger endpoint only accepts an `https://azuresre.dev` audience token,
    not `https://management.azure.com/`) instead of relocating it. It must
    survive somewhere user-facing, framed as historical record for the
    (non-default) Logic App bridge -- not restored as a default-flow
    instruction anywhere in the README/guides."""
    text = VALIDATION_RESULTS.read_text()

    assert "azuresre.dev" in text
    assert "management.azure.com" in text
    audience_block = next(block for block in blocks(text) if "azuresre.dev" in block)
    assert "레거시" in audience_block

    for path in all_docs():
        assert "azuresre.dev" not in path.read_text(), path.name


def test_readme_and_guides_use_exactly_one_cd_per_document():
    """Finding #4: every command in a document must be runnable
    sequentially from the single working directory that document's own
    (at most one) `cd` establishes -- a second `cd monitor/sre-agent-event-lab`
    later in the same document would fail, since no such nested directory
    exists once the first `cd` already landed there."""
    for path in all_docs():
        cd_count = len(re.findall(r"(?m)^cd\s+\S", path.read_text()))
        assert cd_count <= 1, (path.name, cd_count)


def test_readme_scorecard_row_states_per_scenario_and_overall_maximums():
    """Finding #5: `scripts/score.py` computes MAX_POINTS = 10 per scenario
    and MAX_POINTS * len(SCENARIOS) = 30 overall; the README's summary
    table must describe both, not label the whole lab "10점 만점"."""
    text = README.read_text()

    row = next(line for line in text.splitlines() if "scorecard.json" in line)
    assert "10점" in row
    assert "30점" in row


def test_guide02_start_conditions_do_not_claim_an_unenforced_concurrency_lock():
    """Finding #6: `lab_state.py` has no concurrency lock (its own
    docstring says so); S1's start conditions must only claim what
    `RUN_REQUIREMENTS["s1"]` actually enforces."""
    text = (GUIDES / "02-scenario-s1.md").read_text()
    conditions = text.split("## 시작 조건", 1)[1].split("\n## ", 1)[0]

    assert "진행 중인 다른 시나리오가 없습니다" not in conditions
    assert "baseline_passed" in conditions
    assert "agent_setup_acknowledged" in conditions


def test_guide05_generate_notifications_runs_under_plain_python3():
    """Finding #6: `generate_notifications.py` only imports the standard
    library (html, json, re, email.*, pathlib, typing) -- unlike
    `render_capture.py`, it has no Pillow/venv dependency, so the guide
    must not invoke it through `app/.venv/bin/python`."""
    text = (GUIDES / "05-results.md").read_text()

    assert "python3 scripts/generate_notifications.py" in text
    assert "app/.venv/bin/python scripts/generate_notifications.py" not in text


# --- guide structure -----------------------------------------------------


def test_guides_directory_holds_exactly_the_five_numbered_guides():
    assert {path.name for path in GUIDES.glob("*.md")} == set(GUIDE_NAMES)


def test_every_guide_opens_with_prerequisites_and_closes_with_a_next_step():
    for path in guide_paths():
        text = path.read_text()
        assert "## 시작 조건" in text, path.name
        assert "## 다음 단계" in text, path.name
        assert text.index("## 시작 조건") < text.index("## 다음 단계"), path.name


def test_scenario_guides_use_the_required_section_order():
    required = [
        "## 시작 조건",
        "## 실행 명령",
        "## Azure에서 발생하는 변화",
        "## SRE Agent에서 확인할 항목",
        "## 성공·부분 성공·실패 판정",
        "## 복구 확인",
        "## 다음 단계",
    ]
    for name in SCENARIO_GUIDES:
        text = (GUIDES / name).read_text()
        positions = [text.index(heading) for heading in required]
        assert positions == sorted(positions), name


def test_each_guide_hands_off_to_the_next_document():
    for index, name in enumerate(GUIDE_NAMES[:-1]):
        section = (GUIDES / name).read_text().split("## 다음 단계", 1)[1]
        assert GUIDE_NAMES[index + 1] in section, name

    final = (GUIDES / GUIDE_NAMES[-1]).read_text().split("## 다음 단계", 1)[1]
    assert "azd down --purge" in final


def test_scenario_guides_name_the_injected_change_and_its_alert_rule():
    expected = {
        "02-scenario-s1.md": ("FAILURE_MODE=http500", "alert-sre-lab-s1-http500", "500"),
        "03-scenario-s2.md": ("ORDER_DELAY_MS=4000", "alert-sre-lab-s2-latency", "p95"),
        "04-scenario-s3.md": (
            "Storage Blob Data Reader",
            "alert-sre-lab-s3-storage-rbac",
            "403",
        ),
    }
    for name, markers in expected.items():
        text = (GUIDES / name).read_text()
        for marker in markers:
            assert marker in text, (name, marker)


def test_scenario_guides_judge_success_partial_and_failure_with_recovery():
    for name, scenario in SCENARIO_GUIDES.items():
        text = (GUIDES / name).read_text()
        verdict = text.split("## 성공·부분 성공·실패 판정", 1)[1].split("\n## ", 1)[0]
        for state in ("conclusion", "thread-not-created", "investigation-missing", "conclusion-missing"):
            assert state in verdict, (name, state)

        recovery = text.split("## 복구 확인", 1)[1].split("\n## ", 1)[0]
        assert "Resolved" in recovery, name
        assert "state.json" in text, name
        assert "./scripts/lab.sh run {0}".format(scenario) in text, name
        assert "./scripts/lab.sh capture {0}".format(scenario) in text, name


def test_results_guide_documents_the_scoring_thresholds_and_manual_gap():
    text = (GUIDES / "05-results.md").read_text()

    for marker in ("8", "5", "MANUAL", "INCOMPLETE", "scorecard.json"):
        assert marker in text, marker
    for criterion in (
        "impact_scope",
        "direct_cause",
        "actual_evidence",
        "safe_minimum_mitigation",
        "uncertainty",
    ):
        assert criterion in text, criterion


# --- commands match the scripts -----------------------------------------


def test_documented_lab_commands_exist_in_lab_sh():
    documented = set(re.findall(r"lab\.sh\s+([a-z-]+)", joined_docs()))
    supported = set(re.findall(r"^\s{2}([a-z-]+)\)", LAB_SH.read_text(), re.MULTILINE))

    assert documented, "no lab.sh commands are documented"
    assert documented <= supported, sorted(documented - supported)


def test_agent_setup_guide_matches_the_interactive_acknowledge_contract():
    text = (GUIDES / "01-agent-setup.md").read_text()

    assert "./scripts/lab.sh acknowledge agent-setup" in text
    assert "acknowledge" in text
    assert "표준 입력" in text or "stdin" in text
    assert re.search(r"환경 변수[^.]{0,60}(대체할 수 없|불가)", text), (
        "the guide must say no environment variable can replace the typed word"
    )


def test_agent_setup_guide_offers_azd_env_set_without_storing_secrets():
    text = (GUIDES / "01-agent-setup.md").read_text()

    for setting in (
        "azd env set SRE_AGENT_NAME",
        "azd env set SRE_AGENT_RESOURCE_ID",
        "azd env set SRE_REPOSITORY_URL",
        "azd env set SRE_KNOWLEDGE_PATH",
    ):
        assert setting in text, setting
    assert "evidence/agent-setup.json" in text
    for key in ("agent_principal_id", "agent_user_assigned_principal_id", "agent_endpoint"):
        assert key in text, key


def test_agent_setup_guide_offers_a_python_environment_remedy():
    """Finding #4 (Task 6 follow-up): `doctor.sh` gained a `Python
    environment` check, but the guide's failure table never told an
    operator what to do about it. The remedy is local-only and independent
    of the postprovision-hook ordering contract (see
    `test_setup_venv_orders_local_recovery_correctly` below), so it may --
    and should -- name `./scripts/setup-venv.sh` directly.
    """
    text = (GUIDES / "01-agent-setup.md").read_text()
    heading = "## 실패했을 때"

    assert heading in text
    section = text.split(heading, 1)[1]
    assert "Python environment" in section
    assert "./scripts/setup-venv.sh" in section


def test_readme_documents_the_two_phase_provision_and_deploy_flow():
    """`azd provision` alone leaves the public placeholder image running:
    the lab image is built and switched in only during the deploy phase,
    after the workload identity's `AcrPull` grant is observable at the
    registry. The README's deployment section is the one place an operator
    learns that, so it must name both phases and the gate between them --
    and must not describe the image build as part of postprovision.
    """
    text = README.read_text()
    heading = "## 배포"

    assert heading in text
    section = text.split(heading, 1)[1].split("## ", 1)[0]

    assert "azd up" in section
    assert "azd provision" in section
    assert "azd deploy" in section
    assert "AcrPull" in section, (
        "the gate the deploy phase waits on has to be named"
    )
    assert "postprovision" not in section or "setup-venv.sh" in section
    assert not re.search(r"postprovision[^\n]*(ACR 빌드|이미지 교체)", section), (
        "the README must not describe the ACR build or the image switch as "
        "part of the postprovision hook"
    )


def test_readme_recovery_matches_the_hook_that_actually_failed():
    """The provision-phase hook only prepares `app/.venv`, so
    `./scripts/setup-venv.sh` is a complete recovery for it -- and the
    application deployment is a separate `azd deploy` the operator still
    has to run.
    """
    text = README.read_text()
    heading = "## 배포"
    section = text.split(heading, 1)[1].split("## ", 1)[0]

    assert "setup-venv.sh" in section
    assert "azd deploy" in section


def test_guides_do_not_request_secrets_in_environment():
    text = "\n".join(path.read_text() for path in GUIDES.glob("*.md"))
    for forbidden in ("GITHUB_PAT=", "OAUTH_TOKEN=", "CLIENT_SECRET="):
        assert forbidden not in text


def test_docs_never_show_a_credential_value():
    text = joined_docs()

    for forbidden in SECRET_ASSIGNMENTS:
        assert forbidden not in text, forbidden
    for pattern in (r"ghp_[A-Za-z0-9]", r"github_pat_", r"\bsig=", r"--password\b"):
        assert not re.search(pattern, text), pattern


def test_docs_do_not_pin_the_original_subscription_or_resource_group():
    for path in all_docs() + [RUNBOOK]:
        text = path.read_text()
        assert FIXED_SUBSCRIPTION_ID not in text, path.name
        assert FIXED_RESOURCE_GROUP not in text, path.name


def test_runbook_scopes_itself_to_the_provisioned_resource_group():
    text = RUNBOOK.read_text()

    assert "AZURE_RESOURCE_GROUP" in text
    assert "purpose=sre-agent-event-lab" in text


# --- links and screenshots ----------------------------------------------


def test_every_relative_link_in_the_walkthrough_resolves():
    checked = 0
    for path in all_docs():
        targets = re.findall(r"\]\((?!https?://|mailto:)([^)#]+)", path.read_text())
        for target in targets:
            checked += 1
            assert (path.parent / target).resolve().exists(), (path.name, target)
    assert checked


def test_guides_render_only_local_official_screenshots():
    for path in guide_paths():
        for alt, target in images(path.read_text()):
            assert not target.startswith(("http://", "https://")), target
            assert target.startswith("../assets/official/"), target
            resolved = (path.parent / target).resolve()
            assert resolved.is_file(), target
            assert resolved.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", target
            assert alt.strip(), target


def test_selected_screenshots_are_stored_and_referenced_exactly_once():
    rendered = []
    for path in guide_paths():
        rendered.extend(target.rsplit("/", 1)[-1] for _, target in images(path.read_text()))

    assert sorted(rendered) == sorted(GUIDE_SCREENSHOTS), rendered
    for name in GUIDE_SCREENSHOTS:
        assert (OFFICIAL_ASSETS / name).is_file(), name


def test_no_result_screenshots_are_copied_from_the_tutorial():
    """Investigation results are shown with this lab's own captures."""
    stored = {path.name for path in OFFICIAL_ASSETS.glob("*")}

    for tutorial_only in (
        "incident-completed.png",
        "incident-full-page-top.png",
        "incident-full-page-code-fix.png",
        "response-plan-step-1.png",
    ):
        assert tutorial_only not in stored, tutorial_only


def test_every_screenshot_names_its_learn_source_next_to_the_image():
    for path in guide_paths():
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"!\[[^\]]*\]\(\.\./assets/official/([^)]+)\)", line.strip())
            if not match:
                continue
            name = match.group(1)
            caption = "\n".join(lines[index + 1 : index + 4])
            assert caption.lstrip().startswith(">"), name
            assert "출처" in caption, name
            assert GUIDE_SCREENSHOTS[name] in caption, name


def test_screenshot_alt_text_describes_the_captured_screen_in_korean():
    alts = {}
    for path in guide_paths():
        for alt, target in images(path.read_text()):
            alts[target.rsplit("/", 1)[-1]] = alt

    assert set(alts) == set(GUIDE_SCREENSHOTS)
    for name, keywords in SCREENSHOT_ALT_KEYWORDS.items():
        alt = alts[name]
        assert len(alt) >= 60, (name, len(alt))
        assert re.search(r"[가-힣]", alt), name
        for keyword in keywords:
            assert keyword in alt, (name, keyword)


def test_screenshot_alt_text_does_not_claim_what_the_picture_lacks():
    alts = {}
    for path in guide_paths():
        for alt, target in images(path.read_text()):
            alts[target.rsplit("/", 1)[-1]] = alt

    for name, forbidden in FORBIDDEN_ALT_CLAIMS.items():
        for claim in forbidden:
            assert claim not in alts[name], (name, claim)


def test_screenshot_alt_text_is_not_repeated_as_body_prose():
    for path in guide_paths():
        text = path.read_text()
        body = re.sub(r"\s+", " ", re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text))
        repeated = [
            sentence
            for alt, _ in images(text)
            for sentence in body_sentences(alt)
            if sentence in body
        ]
        assert repeated == [], (path.name, repeated)
