#!/usr/bin/env python3
"""Ordered-run state for the SRE Agent event lab.

The lab's three scenarios only produce readable evidence when they happen
one at a time, in order, against a workload that has recovered from the
previous one. This module is the single place that decides whether the next
step is allowed, and the single place that records what actually happened:

* Ordering: a scenario may start only after the baseline passed, after a
  human acknowledged the portal-only Agent setup, and -- from S2 on --
  after the previous scenario both recovered and produced a real capture.
  Those rules look exactly one scenario back and stay that way: a run that
  *recovered* is finished, so a scenario whose capture is still
  outstanding blocks only the scenario that names it, never the whole lab.
* Exclusivity: on top of the ordered rules, no run may start while *any*
  scenario is `running` or `failed`. All three scenarios share one
  Container App, and an unfinished run is exactly the case where its fault
  may still be live -- a rejected injection, a recovery the EXIT trap
  could not complete, a Ctrl-C. The ordered rules cannot see that: after a
  full lab, a broken S1 re-run leaves `s2_recovered`/`s2_captured`
  untouched, so S3 was admitted and injected a third fault on top of an
  incident nobody had resolved. Re-running the scenario that *failed* is
  the one exception, because that is how an operator clears it; re-running
  one that is still `running` is refused too, since two live injections of
  the same fault leave neither capture readable. Only the *earliest*
  unfinished run may be repaired, so working the list from the top always
  terminates and no editable state can lock the lab.
* Honesty: a capture is only "successful" when the normalized timeline
  holds a real `conclusion` event, *and* the run it belongs to recovered.
  `thread-not-created`, `investigation-missing` and `conclusion-missing`
  are recorded verbatim whatever the run did -- they measure what the
  Agent failed to produce and can neither unblock a scenario nor earn a
  point -- but a `conclusion` is refused outright for a run that is
  `running`, `failed` or unrecorded, because nothing downstream can tell
  such a conclusion from a real one. A re-run retires the scenario's
  previous outcome the moment it *starts* -- `begin_run` clears the whole
  entry and records `run_status: running` before the first destructive
  call -- and `mark_recovered`/`mark_failed` clear the previous
  `capture_status` again when they end one. A conclusion captured against
  a run that no longer exists must never let a later run's capture stage,
  or the scorer, reuse it, not even when the new run dies before it can
  record an outcome of its own. Only a capture recorded *after* the
  current run counts.
* Binding: the file records the azd environment, subscription and resource
  group it belongs to and refuses to be read against a different one, so a
  state file left behind by another lab can never unlock a run here.

Storage is `evidence/state.json`, written by rendering the whole document
into a sibling temporary file and `os.replace`-ing it into place; a
rename within a directory is the only write that cannot leave a
half-written state file behind. Decoded JSON is validated before use:
`stages`, `scenarios`, and every entry inside them must be JSON objects,
or the file is refused with a clean `LabStateError` -- never a raw
`TypeError`/`AttributeError` traceback, and never a silent reset that
would discard whatever an operator had already recorded.

Concurrency: this module assumes one operator drives the lab at a time.
Nothing here locks `state.json` across processes, so two commands that
read-modify-write it at the same moment can race and the later write
wins; the atomic `os.replace` only guarantees each individual write is
whole, not that concurrent writes are serialized. That is a deliberate
trade for a single-operator lab -- add real file locking (e.g.
`fcntl.flock` around load-mutate-save) only if concurrent operators
become a real, observed need, not in anticipation of one.

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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


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

RUN_RUNNING = "running"
RUN_RECOVERED = "recovered"
RUN_FAILED = "failed"

# A run that is neither recovered nor absent has not finished: `running`
# may still have a fault injected right now, and `failed` ended with one
# that recovery could not be confirmed for. Both mean the shared workload
# is not known to be clean, so no scenario at all may start on top of one.
UNFINISHED_RUN_STATUSES = (RUN_RUNNING, RUN_FAILED)

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


# The document that walks an operator through each scenario. Refusal
# messages name it instead of a command, because the lab is run by hand:
# there is no script that performs a scenario.
SCENARIO_GUIDES = {
    "s1": "guides/02-scenario-s1.md",
    "s2": "guides/03-scenario-s2.md",
    "s3": "guides/04-scenario-s3.md",
}


def scenario_guide(scenario: str) -> str:
    return SCENARIO_GUIDES.get(scenario, "the scenario guide")


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
        self._verify_shape(document)
        self._verify_binding(document)
        for key, value in (
            ("environment", self.environment),
            ("subscription_id", self.subscription_id),
            ("resource_group", self.resource_group),
        ):
            if value and not document.get(key):
                document[key] = value
        return document

    def _verify_shape(self, document: Dict[str, Any]) -> None:
        """Refuse decoded JSON whose containers are not JSON objects.

        `stages` and `scenarios`, and every entry inside them, are always
        treated as objects (subscripted, `.setdefault`-ed, mutated in
        place). A wrong type there -- a list, a string, `null`, a number --
        would otherwise surface many calls later as a raw `TypeError` or
        `AttributeError` from deep inside `mark`/`mark_recovered`/
        `record_capture`. Catching it here, once, turns every such case
        into the same clean `LabStateError` a corrupt file already
        produces, and never silently discards the bad value by resetting
        it to `{}`.
        """
        for container_key in ("stages", "scenarios"):
            container = document.get(container_key)
            if not isinstance(container, dict):
                raise LabStateError(
                    "Lab state {0} field {1!r} must be a JSON object, not "
                    "{2}. Inspect or remove the file before "
                    "continuing.".format(
                        self.path, container_key, type(container).__name__
                    )
                )
            for entry_name, entry in container.items():
                if not isinstance(entry, dict):
                    raise LabStateError(
                        "Lab state {0} field {1}.{2!r} must be a JSON "
                        "object, not {3}. Inspect or remove the file "
                        "before continuing.".format(
                            self.path,
                            container_key,
                            entry_name,
                            type(entry).__name__,
                        )
                    )

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
        """Refuse a scenario run the recorded state cannot justify.

        Two independent rules, checked in this order:

        1. The ordered prerequisites in `RUN_REQUIREMENTS` -- the lab-wide
           ones, plus (from S2 on) the previous scenario's recovery and
           capture. They look exactly one scenario back and are unchanged:
           a run that *recovered* is finished, so a scenario whose capture
           is still outstanding blocks only the scenario that names it, not
           the whole lab.
        2. The unfinished-run gate: no run may start while any scenario is
           `running` or `failed`. The three scenarios share one Container
           App, and an unfinished run is exactly the case where its fault
           may still be live -- an injection that was rejected, a recovery
           the EXIT trap could not complete, a Ctrl-C. The ordered rules
           cannot see that: after a full lab, a broken S1 re-run leaves
           `s2_recovered`/`s2_captured` untouched, so S3 was admitted and
           injected a third fault on top of an unresolved incident. The one
           exception is repairing the *earliest* unfinished run when it
           failed, which is both the documented remedy and what keeps the
           gate from ever locking the lab.

        The ordered rules run first so the more specific message -- which
        stage is missing, and for which scenario -- is what an operator
        sees whenever it applies; `_remedy` then reports the *reachable*
        next command for that stage, which is not "run it again" while the
        run in question is still `running`.
        """
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
        self._require_no_unfinished_run(scenario)

    def _unfinished_runs(self) -> List[Tuple[str, str]]:
        """Every scenario whose run is `running` or `failed`, in lab order."""
        return [
            (scenario, self.run_status(scenario) or "")
            for scenario in SCENARIOS
            if self.run_status(scenario) in UNFINISHED_RUN_STATUSES
        ]

    def _blockers_for(self, scenario: str) -> List[Tuple[str, str]]:
        """The unfinished runs that stand between `scenario` and a start.

        Repairing the *earliest* failed run is always allowed, and is the
        only exception: it is the documented remedy for a failure, and
        making it unconditional is what guarantees the gate can always be
        worked off from the top. Without that, two scenarios `failed` at
        once -- unreachable through this API, but one hand-edit away --
        would refuse every command the lab has.

        `running` is never repairable this way: nobody can tell whether
        that run is still working, so it has to be ended explicitly first.
        """
        unfinished = self._unfinished_runs()
        if unfinished and unfinished[0] == (scenario, RUN_FAILED):
            return []
        return unfinished

    def _require_no_unfinished_run(self, scenario: str) -> None:
        """Refuse while any scenario's run is `running` or `failed`.

        Every blocker is named, earliest first, with its status and the
        command that resolves it, so an operator never has to read
        `state.json` to find out what is holding the lab -- and never
        clears one blocker only to hit the next one blind.
        """
        blockers = self._blockers_for(scenario)
        if not blockers:
            return
        raise InvalidTransition(
            "Cannot run {0}: {1}. All three scenarios share one workload, so "
            "no run may start while another is unfinished; deal with the "
            "first one listed first.".format(
                scenario,
                "; ".join(
                    "{0} is {1} ({2})".format(
                        blocked, status, self._unfinished_remedy(blocked, status)
                    )
                    for blocked, status in blockers
                ),
            )
        )

    @staticmethod
    def _unfinished_remedy(scenario: str, status: str) -> str:
        if status == RUN_RUNNING:
            return (
                "wait for it to finish, or record how it ended with "
                "lab_state.py mark-failed {0}".format(scenario)
            )
        return "follow {0}".format(scenario_guide(scenario))

    def _remedy(self, missing: Sequence[str]) -> str:
        """The next command that is actually reachable for a missing stage.

        Naming the stage's own scenario is only useful when starting that
        scenario would in fact be admitted. It is not while the scenario is
        `running`, and not while some *other* unfinished run blocks it --
        telling an operator to run a command the very next gate refuses is
        how a refusal stops being actionable. So the remedy is whatever the
        gate would demand first.
        """
        remedies = {
            "baseline_passed": (
                "Run the baseline steps in guides/01-agent-setup.md, then: "
                "lab_state.py mark baseline_passed"
            ),
            "agent_setup_acknowledged": "Run: lab_state.py acknowledge-agent",
        }
        for stage in missing:
            if stage in remedies:
                return remedies[stage]
            scenario_stage = _scenario_stage(stage)
            if scenario_stage is not None:
                scenario, suffix = scenario_stage
                blockers = self._blockers_for(scenario)
                if blockers:
                    blocked, status = blockers[0]
                    return "{0} is {1}; {2}.".format(
                        blocked, status, self._unfinished_remedy(blocked, status)
                    )
                if suffix == "recovered":
                    return "Run the {0} steps in {1}".format(
                        scenario, scenario_guide(scenario)
                    )
                return "Capture the {0} evidence as {1} describes".format(
                    scenario, scenario_guide(scenario)
                )
        return ""

    @staticmethod
    def _start_new_attempt(entry: Dict[str, Any]) -> None:
        """Discard the previous run's terminal capture outcome.

        `mark_recovered` and `mark_failed` both mean "a run of this
        scenario just ended"; every previous `capture_status` (and the
        capture-side `evidence_dir` it was recorded against) describes a
        run that no longer exists once a new one starts. Leaving it in
        place would let a stale `conclusion` from an earlier attempt keep
        satisfying `sX_captured` -- and therefore the next scenario's gate,
        and the scorer -- even though nothing has been captured for *this*
        run yet. A fresh capture, recorded after this call, is the only
        thing that can set it again.

        `begin_run` clears the same thing (and everything else) when the
        attempt starts; this stays because a run that ends is proof the
        previous one is over even if nothing recorded its start -- an
        operator marking an outcome by hand, or a state file written by an
        older version of this module.
        """
        entry.pop("capture_status", None)

    def begin_run(self, scenario: str, evidence_dir: Optional[str] = None) -> None:
        """Record that a new attempt of `scenario` has started.

        Called after `require_run` and *before* the first destructive
        Azure call, which is the only ordering that holds when the run
        does not survive to record an outcome. A rejected injection, a
        recovery the EXIT trap could not complete, an operator's Ctrl-C:
        each of those exits before `mark_recovered`/`mark_failed`, and
        until this existed they left the *previous* attempt's
        `recovered` + `conclusion` in the file. The next scenario's gate
        and the scorer read exactly those two fields, so a re-run that
        broke early was indistinguishable from the successful run it
        replaced.

        The whole entry is cleared rather than a named list of fields:
        every value in it -- `run_status`, `capture_status`,
        `failure_reason`, `alert_resolved_at`, the evidence directory, any
        terminal capture metadata a later version records -- describes the
        attempt that just ended, and a field added later must not silently
        start surviving a re-run. What replaces it is the new attempt:
        `run_status: running`, when it started, and the evidence directory
        it writes into.

        `running` deliberately satisfies nothing: `has('sX_recovered')`
        only accepts `recovered`, `has('sX_captured')` only a recorded
        `conclusion`. An attempt that never finishes therefore keeps the
        next scenario blocked and scores as "no capture recorded" until a
        run really recovers and a capture really lands.
        """
        self.require_run(scenario)
        entry = self._scenario(scenario)
        entry.clear()
        entry["run_status"] = RUN_RUNNING
        entry["started_at"] = utc_now()
        if evidence_dir:
            entry["evidence_dir"] = str(evidence_dir)
        self._save()

    def mark_recovered(self, scenario: str, evidence_dir: Optional[str] = None) -> None:
        entry = self._scenario(scenario)
        self._start_new_attempt(entry)
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
        self._start_new_attempt(entry)
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
        """Record what a capture actually proved about this scenario's run.

        `conclusion` is the one outcome that satisfies `sX_captured`,
        admits the next scenario and earns rubric points, so it may only
        ever describe a run that recovered. A conclusion recorded while the
        scenario is `running`, `failed`, or has no recorded run at all
        describes an incident nobody resolved -- and nothing downstream can
        tell the difference, because the captured timeline looks identical
        either way. This is the only place that can refuse it, so it does.

        The three missing markers stay recordable whatever the run did:
        what the Agent failed to produce is a measurement worth keeping,
        and none of them can unblock a scenario (`has('sX_captured')`
        accepts only `conclusion`) or award a point (`score.py` fails every
        criterion for them). Recording them is diagnostic honesty with no
        way to inflate a result.
        """
        if capture_status not in CAPTURE_STATES:
            raise ValueError(
                "Unknown capture status: {0}. Known statuses: {1}".format(
                    capture_status, ", ".join(CAPTURE_STATES)
                )
            )
        entry = self._scenario(scenario)
        run_status = entry.get("run_status")
        previous_capture_status = entry.get("capture_status")
        if (
            previous_capture_status == SUCCESSFUL_CAPTURE
            and capture_status != SUCCESSFUL_CAPTURE
        ):
            raise InvalidTransition(
                "{0} already has a conclusion for its current run. Re-run the "
                "scenario before collecting another capture; the successful "
                "result will not be replaced by {1}.".format(scenario, capture_status)
            )
        if capture_status == SUCCESSFUL_CAPTURE and run_status != RUN_RECOVERED:
            raise InvalidTransition(
                "Cannot record a {0} for {1}: its run is {2}, not {3}. Only a "
                "run whose fault was reverted and whose alert Azure Monitor "
                "closed can be credited with a conclusion; {4}".format(
                    SUCCESSFUL_CAPTURE,
                    scenario,
                    run_status or "none",
                    RUN_RECOVERED,
                    self._unfinished_remedy(scenario, run_status or ""),
                )
            )
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
    the four settings no stable API exposes), so the only honest evidence
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

    begin_run = commands.add_parser(
        "begin-run", help="start a scenario run, retiring the previous attempt"
    )
    begin_run.add_argument("scenario", choices=SCENARIOS)
    begin_run.add_argument("evidence_dir", nargs="?")

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

    capture_status = commands.add_parser(
        "capture-status", help="print a scenario's recorded capture status"
    )
    capture_status.add_argument("scenario", choices=SCENARIOS)

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
        if args.command == "begin-run":
            state.begin_run(args.scenario, args.evidence_dir)
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
        if args.command == "capture-status":
            print(state.capture_status(args.scenario) or "")
            return 0
        if args.command == "evidence-dir":
            directory = state.evidence_dir(args.scenario)
            if not directory:
                raise LabStateError(
                    "No evidence directory recorded for {0}. "
                    "Run the {0} steps in {1}".format(
                        args.scenario, scenario_guide(args.scenario)
                    )
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
