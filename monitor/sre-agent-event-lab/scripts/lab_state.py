#!/usr/bin/env python3
"""Ordered-run state for the SRE Agent event lab.

The lab's three scenarios only produce readable evidence when they happen
one at a time, in order, against a workload that has recovered from the
previous one. This module is the single place that decides whether the next
step is allowed, and the single place that records what actually happened:

* Ordering: a scenario may start only after the baseline passed, after a
  human acknowledged the portal-only Agent setup, and -- from S2 on --
  after the previous scenario both recovered and produced a real capture.
* Honesty: a capture is only "successful" when the normalized timeline
  holds a real `conclusion` event. `thread-not-created`,
  `investigation-missing` and `conclusion-missing` are recorded verbatim
  and never promoted to success, by any code path.
* Binding: the file records the azd environment, subscription and resource
  group it belongs to and refuses to be read against a different one, so a
  state file left behind by another lab can never unlock a run here.

Storage is `evidence/state.json`, written by rendering the whole document
into a sibling temporary file and `os.replace`-ing it into place; a
rename within a directory is the only write that cannot leave a
half-written state file behind.

Python 3.9 compatible (the lab's documented floor): no PEP 604 unions, no
structural pattern matching, and no third-party imports.
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


SCENARIOS = ("s1", "s2", "s3")

STAGES = (
    "deployed",
    "baseline_passed",
    "agent_setup_acknowledged",
    "s1_recovered",
    "s1_captured",
    "s2_recovered",
    "s2_captured",
    "s3_recovered",
    "s3_captured",
    "scored",
)

# The only capture outcome that counts as success, plus the three explicit
# markers `capture_model.normalize_capture` emits when the Agent produced
# nothing. They are stored exactly as they appear in the timeline.
SUCCESSFUL_CAPTURE = "conclusion"
MISSING_CAPTURE_STATES = (
    "thread-not-created",
    "investigation-missing",
    "conclusion-missing",
)
CAPTURE_STATES = (SUCCESSFUL_CAPTURE,) + MISSING_CAPTURE_STATES

RUN_RECOVERED = "recovered"
RUN_FAILED = "failed"

# Every scenario needs the two lab-wide prerequisites; S2 and S3 also need
# the previous scenario to have recovered *and* produced a real capture.
RUN_REQUIREMENTS = {
    "s1": ("baseline_passed", "agent_setup_acknowledged"),
    "s2": ("baseline_passed", "agent_setup_acknowledged", "s1_recovered", "s1_captured"),
    "s3": (
        "baseline_passed",
        "agent_setup_acknowledged",
        "s2_recovered",
        "s2_captured",
    ),
}

# The alert rules an operator must see wired to the Agent before S1. Fixed
# because `infra/alerts.bicep` creates exactly these three.
ALERT_RULE_NAMES = (
    "alert-sre-lab-s1-http500",
    "alert-sre-lab-s2-latency",
    "alert-sre-lab-s3-storage-rbac",
)
RESPONSE_PLAN_MODE = "Review"
ACKNOWLEDGE_WORD = "acknowledge"
PORTAL_URL = "https://sre.azure.com"

DEFAULT_STATE_PATH = Path(__file__).resolve().parents[1] / "evidence" / "state.json"


class LabStateError(RuntimeError):
    """Any refusal this module reports; the CLI turns it into exit code 1."""


class InvalidTransition(LabStateError):
    """The requested step is not allowed from the recorded state."""


class EnvironmentMismatch(LabStateError):
    """The state file belongs to a different lab environment."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def terminal_state(events: Iterable[Dict[str, Any]]) -> str:
    """The one capture outcome a normalized timeline proves.

    A real `conclusion` event wins over everything else. Otherwise the most
    upstream missing marker is reported, because that is the failure an
    operator has to fix first: no thread at all explains a missing
    investigation, which in turn explains a missing conclusion.
    """
    states = {str(event.get("state", "")) for event in events or []}
    if SUCCESSFUL_CAPTURE in states:
        return SUCCESSFUL_CAPTURE
    for marker in MISSING_CAPTURE_STATES:
        if marker in states:
            return marker
    return "thread-not-created"


def _scenario_stage(stage: str) -> Optional[Sequence[str]]:
    """('s1', 'recovered') for `s1_recovered`, else None."""
    for scenario in SCENARIOS:
        for suffix in ("recovered", "captured"):
            if stage == "{0}_{1}".format(scenario, suffix):
                return (scenario, suffix)
    return None


class LabState:
    """The lab's recorded progress, bound to one azd environment."""

    def __init__(
        self,
        path,
        environment: str = "",
        subscription_id: str = "",
        resource_group: str = "",
    ):
        self.path = Path(path)
        self.environment = environment or ""
        self.subscription_id = subscription_id or ""
        self.resource_group = resource_group or ""
        self._document = self._load()

    # --- storage ---------------------------------------------------------

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {
                "environment": self.environment,
                "subscription_id": self.subscription_id,
                "resource_group": self.resource_group,
                "stages": {},
                "scenarios": {},
            }
        try:
            document = json.loads(self.path.read_text())
        except (OSError, ValueError) as error:
            raise LabStateError(
                "Cannot read lab state {0}: {1}. Inspect or remove the file "
                "before continuing.".format(self.path, error)
            )
        if not isinstance(document, dict):
            raise LabStateError(
                "Lab state {0} is not a JSON object.".format(self.path)
            )
        document.setdefault("stages", {})
        document.setdefault("scenarios", {})
        self._verify_binding(document)
        for key, value in (
            ("environment", self.environment),
            ("subscription_id", self.subscription_id),
            ("resource_group", self.resource_group),
        ):
            if value and not document.get(key):
                document[key] = value
        return document

    def _verify_binding(self, document: Dict[str, Any]) -> None:
        for key, current in (
            ("environment", self.environment),
            ("subscription_id", self.subscription_id),
            ("resource_group", self.resource_group),
        ):
            recorded = document.get(key) or ""
            if current and recorded and recorded != current:
                raise EnvironmentMismatch(
                    "Lab state {0} belongs to {1} {2}, not {3}. Use that "
                    "environment or start a new lab with a fresh evidence "
                    "directory.".format(self.path, key, recorded, current)
                )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(self._document, indent=2, sort_keys=True) + "\n"
        handle, temporary_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w") as temporary_file:
                temporary_file.write(rendered)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_name, str(self.path))
        except BaseException:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
            raise

    @property
    def document(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self._document))

    # --- stages ----------------------------------------------------------

    def mark(self, stage: str, evidence_dir: Optional[str] = None, **details) -> None:
        if stage not in STAGES:
            raise ValueError(
                "Unknown stage: {0}. Known stages: {1}".format(stage, ", ".join(STAGES))
            )
        scenario_stage = _scenario_stage(stage)
        if scenario_stage is not None:
            scenario, suffix = scenario_stage
            if suffix == "recovered":
                self.mark_recovered(scenario, evidence_dir)
                return
            status = self.capture_status(scenario)
            if status != SUCCESSFUL_CAPTURE:
                raise InvalidTransition(
                    "Cannot mark {0}: the recorded capture status for {1} is "
                    "{2}. Only a captured conclusion counts as a successful "
                    "capture.".format(stage, scenario, status or "none")
                )
            return
        entry = {"at": utc_now()}
        if evidence_dir:
            entry["evidence_dir"] = str(evidence_dir)
        if details:
            entry["details"] = details
        self._document["stages"][stage] = entry
        self._save()

    def has(self, stage: str) -> bool:
        if stage not in STAGES:
            raise ValueError("Unknown stage: {0}".format(stage))
        scenario_stage = _scenario_stage(stage)
        if scenario_stage is None:
            return stage in self._document["stages"]
        scenario, suffix = scenario_stage
        if suffix == "recovered":
            return self.run_status(scenario) == RUN_RECOVERED
        return self.is_successful_capture(scenario)

    # --- scenarios -------------------------------------------------------

    def _scenario(self, scenario: str) -> Dict[str, Any]:
        if scenario not in SCENARIOS:
            raise ValueError(
                "Unknown scenario: {0}. Known scenarios: {1}".format(
                    scenario, ", ".join(SCENARIOS)
                )
            )
        return self._document["scenarios"].setdefault(scenario, {})

    def require_run(self, scenario: str) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(
                "Unknown scenario: {0}. Known scenarios: {1}".format(
                    scenario, ", ".join(SCENARIOS)
                )
            )
        missing = [stage for stage in RUN_REQUIREMENTS[scenario] if not self.has(stage)]
        if missing:
            raise InvalidTransition(
                "Cannot run {0}: missing {1}. {2}".format(
                    scenario, ", ".join(missing), self._remedy(missing)
                )
            )

    @staticmethod
    def _remedy(missing: Sequence[str]) -> str:
        remedies = {
            "baseline_passed": "Run: lab.sh baseline",
            "agent_setup_acknowledged": "Run: lab.sh acknowledge agent-setup",
        }
        for stage in missing:
            if stage in remedies:
                return remedies[stage]
            scenario_stage = _scenario_stage(stage)
            if scenario_stage is not None:
                scenario, suffix = scenario_stage
                if suffix == "recovered":
                    return "Run: lab.sh run {0}".format(scenario)
                return "Run: lab.sh capture {0}".format(scenario)
        return ""

    def mark_recovered(self, scenario: str, evidence_dir: Optional[str] = None) -> None:
        entry = self._scenario(scenario)
        entry["run_status"] = RUN_RECOVERED
        entry.pop("failure_reason", None)
        if evidence_dir:
            entry["evidence_dir"] = str(evidence_dir)
        self._save()

    def mark_failed(
        self,
        scenario: str,
        evidence_dir: Optional[str] = None,
        reason: str = "",
    ) -> None:
        entry = self._scenario(scenario)
        entry["run_status"] = RUN_FAILED
        if reason:
            entry["failure_reason"] = reason
        if evidence_dir:
            entry["evidence_dir"] = str(evidence_dir)
        self._save()

    def run_status(self, scenario: str) -> Optional[str]:
        return self._scenario(scenario).get("run_status")

    def record_capture(
        self,
        scenario: str,
        capture_status: str,
        evidence_dir: Optional[str] = None,
    ) -> None:
        if capture_status not in CAPTURE_STATES:
            raise ValueError(
                "Unknown capture status: {0}. Known statuses: {1}".format(
                    capture_status, ", ".join(CAPTURE_STATES)
                )
            )
        entry = self._scenario(scenario)
        entry["capture_status"] = capture_status
        if evidence_dir:
            entry["evidence_dir"] = str(evidence_dir)
        self._save()

    def capture_status(self, scenario: str) -> Optional[str]:
        return self._scenario(scenario).get("capture_status")

    def is_successful_capture(self, scenario: str) -> bool:
        return self.capture_status(scenario) == SUCCESSFUL_CAPTURE

    def evidence_dir(self, scenario: str) -> Optional[str]:
        return self._scenario(scenario).get("evidence_dir")


# --- configuration ------------------------------------------------------


def configured(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def state_from_environment(path) -> LabState:
    """A `LabState` bound to the configuration the shell scripts resolved.

    `common.sh` is the only place that resolves the lab's configuration
    (explicit environment > `azd env get-value` > default) and it passes the
    resolved values through the process environment, so nothing here has to
    re-implement that precedence -- or silently fall back to a different
    environment when a value is absent.
    """
    return LabState(
        path,
        environment=configured("AZURE_ENV_NAME"),
        subscription_id=configured("AZURE_SUBSCRIPTION_ID"),
        resource_group=configured("AZURE_RESOURCE_GROUP"),
    )


def agent_settings() -> List[Sequence[str]]:
    """The non-secret settings an operator must confirm in the portal.

    Every value is a name, path or resource ID that `.env.example` already
    documents; no credential, connection string or token is read here, so
    the printed block and the recorded evidence stay safe to share.
    """
    return [
        ("Agent name", configured("SRE_AGENT_NAME"), "agent_name"),
        ("Agent resource ID", configured("SRE_AGENT_RESOURCE_ID"), "agent_resource_id"),
        ("Repository URL", configured("SRE_REPOSITORY_URL"), "repository_url"),
        (
            "Repository branch",
            configured("SRE_REPOSITORY_BRANCH"),
            "repository_branch",
        ),
        ("Knowledge path", configured("SRE_KNOWLEDGE_PATH"), "knowledge_path"),
    ]


def acknowledge_agent(state: LabState, stream=None, output=None) -> int:
    """Print the configured Agent wiring and require a typed acknowledgement.

    None of these settings has an official, stable API to read back (see
    `doctor.sh`'s four permanent `MANUAL` rows), so the only honest evidence
    that the portal side is done is a human who looked at it. A configured
    environment variable proves intent, never completion -- which is why
    this command reads the answer from stdin and accepts nothing but the
    exact word `acknowledge`.
    """
    stream = sys.stdin if stream is None else stream
    output = sys.stdout if output is None else output

    details = {}
    print("Verify these Agent settings in the portal ({0}):".format(PORTAL_URL), file=output)
    for label, value, key in agent_settings():
        details[key] = value
        print("  {0}: {1}".format(label, value or "(not configured)"), file=output)
    details["response_plan_mode"] = RESPONSE_PLAN_MODE
    details["alert_rules"] = list(ALERT_RULE_NAMES)
    print("  Response plan mode: {0}".format(RESPONSE_PLAN_MODE), file=output)
    print("  Alert rules: {0}".format(", ".join(ALERT_RULE_NAMES)), file=output)
    print(
        'Type "{0}" to record that you verified them yourself: '.format(ACKNOWLEDGE_WORD),
        file=output,
    )
    output.flush()

    answer = stream.readline()
    if answer.strip() != ACKNOWLEDGE_WORD:
        print(
            "Agent setup was not acknowledged; nothing recorded.",
            file=sys.stderr,
        )
        return 1

    state.mark("agent_setup_acknowledged", **details)
    print("Recorded agent_setup_acknowledged.", file=output)
    return 0


# --- command line -------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SRE Agent event lab run state")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), type=Path)
    commands = parser.add_subparsers(dest="command")
    commands.required = True

    require_run = commands.add_parser("require-run", help="allow a scenario run")
    require_run.add_argument("scenario", choices=SCENARIOS)

    mark = commands.add_parser("mark", help="record a lab stage")
    mark.add_argument("stage", choices=STAGES)
    mark.add_argument("--evidence-dir")

    recovered = commands.add_parser("mark-recovered", help="record a recovered run")
    recovered.add_argument("scenario", choices=SCENARIOS)
    recovered.add_argument("evidence_dir", nargs="?")

    failed = commands.add_parser("mark-failed", help="record a failed run")
    failed.add_argument("scenario", choices=SCENARIOS)
    failed.add_argument("evidence_dir", nargs="?")
    failed.add_argument("--reason", default="")

    capture = commands.add_parser("record-capture", help="record a capture outcome")
    capture.add_argument("scenario", choices=SCENARIOS)
    capture.add_argument("--timeline", type=Path)
    capture.add_argument("--status", choices=CAPTURE_STATES)
    capture.add_argument("--evidence-dir")

    evidence = commands.add_parser("evidence-dir", help="print a scenario's evidence dir")
    evidence.add_argument("scenario", choices=SCENARIOS)

    commands.add_parser("acknowledge-agent", help="record manual Agent setup verification")
    commands.add_parser("show", help="print the recorded state as JSON")

    return parser.parse_args(argv)


def _capture_status_from(args: argparse.Namespace) -> str:
    if args.status:
        return args.status
    if not args.timeline:
        raise LabStateError("record-capture needs --timeline or --status.")
    try:
        events = json.loads(Path(args.timeline).read_text())
    except (OSError, ValueError) as error:
        raise LabStateError(
            "Cannot read normalized timeline {0}: {1}".format(args.timeline, error)
        )
    if not isinstance(events, list):
        raise LabStateError(
            "Normalized timeline {0} is not a JSON array.".format(args.timeline)
        )
    return terminal_state(events)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        state = state_from_environment(args.state)
        if args.command == "require-run":
            state.require_run(args.scenario)
            return 0
        if args.command == "mark":
            state.mark(args.stage, evidence_dir=args.evidence_dir)
            return 0
        if args.command == "mark-recovered":
            state.mark_recovered(args.scenario, args.evidence_dir)
            return 0
        if args.command == "mark-failed":
            state.mark_failed(args.scenario, args.evidence_dir, reason=args.reason)
            return 0
        if args.command == "record-capture":
            status = _capture_status_from(args)
            state.record_capture(args.scenario, status, args.evidence_dir)
            print(status)
            return 0
        if args.command == "evidence-dir":
            directory = state.evidence_dir(args.scenario)
            if not directory:
                raise LabStateError(
                    "No evidence directory recorded for {0}. "
                    "Run: lab.sh run {0}".format(args.scenario)
                )
            print(directory)
            return 0
        if args.command == "acknowledge-agent":
            return acknowledge_agent(state)
        if args.command == "show":
            print(json.dumps(state.document, indent=2, sort_keys=True))
            return 0
    except (LabStateError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
