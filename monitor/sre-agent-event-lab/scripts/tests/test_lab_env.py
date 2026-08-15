"""Contract tests for the one-shot lab environment and its Codespaces entry.

An operator who opens the lab in Codespaces runs `az login` once and then
one `source`; every later command reads exported values instead of binding
each one by hand. These tests pin the pieces that promise makes: the
devcontainer Codespaces actually offers, the sourced script that resolves
and exports the values, and the guides that stopped re-binding them.
"""
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]
LAB_ROOT = REPO_ROOT / "monitor" / "sre-agent-event-lab"
LAB_ENV_SH = LAB_ROOT / "scripts" / "lab-env.sh"
GUIDES = LAB_ROOT / "guides"
README = LAB_ROOT / "README.md"

# GitHub only offers configurations stored at the repository root, either as
# `.devcontainer/devcontainer.json` or one level deep under `.devcontainer/`.
# A file anywhere else is invisible in the Codespaces creation UI.
DEVCONTAINER = REPO_ROOT / ".devcontainer" / "sre-agent-event-lab" / "devcontainer.json"

SCENARIO_GUIDES = {
    "02-scenario-s1.md": "s1",
    "03-scenario-s2.md": "s2",
    "04-scenario-s3.md": "s3",
}

# Every value the manual walkthrough consumes, and the azd output each one
# is resolved from.
EXPORTED_VALUES = {
    "RESOURCE_GROUP": "AZURE_RESOURCE_GROUP",
    "SUBSCRIPTION_ID": "AZURE_SUBSCRIPTION_ID",
    "APP_NAME": "AZURE_CONTAINER_APP_NAME",
    "APP_FQDN": "AZURE_CONTAINER_APP_FQDN",
    "WORKLOAD_PRINCIPAL_ID": "AZURE_CONTAINER_APP_PRINCIPAL_ID",
    "STORAGE_CONTAINER_SCOPE": "AZURE_STORAGE_CONTAINER_SCOPE",
    "BLOB_ROLE_ASSIGNMENT_NAME": "AZURE_BLOB_ROLE_ASSIGNMENT_NAME",
}


def manual_section(name):
    text = (GUIDES / name).read_text()
    return text[text.index("## 수동 실행"):text.index("## 지름길")]


# --- Codespaces entry point ------------------------------------------------


def test_codespaces_offers_a_configuration_for_this_lab():
    assert DEVCONTAINER.is_file(), (
        "Codespaces only lists configurations under the repository's own "
        f".devcontainer directory; expected {DEVCONTAINER}"
    )
    config = json.loads(DEVCONTAINER.read_text())
    assert config["name"]
    features = " ".join(config.get("features", {}))
    for required in ("azure-cli", "azure-dev/azd", "github-cli", "python"):
        assert required in features, required


def test_devcontainer_records_no_secret_and_no_subscription():
    raw = DEVCONTAINER.read_text()
    assert not re.search(
        r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b", raw
    ), "a GUID in the devcontainer would pin every user to one subscription"
    for forbidden in ("PASSWORD", "SECRET", "TOKEN", "_KEY", "CONNECTION_STRING"):
        assert forbidden not in raw.upper(), forbidden


def test_devcontainer_prepares_the_lab_without_logging_in_for_the_user():
    """`az login` is interactive and account-specific: the container may
    prepare the workspace, but it must never attempt a login or bake in
    credentials of whoever authored the file."""
    config = json.loads(DEVCONTAINER.read_text())
    lifecycle = " ".join(
        str(config.get(hook, ""))
        for hook in ("onCreateCommand", "postCreateCommand", "postStartCommand")
    )
    assert "setup-venv.sh" in lifecycle
    assert "az login" not in lifecycle


# --- One-shot environment --------------------------------------------------


def test_lab_env_is_sourced_not_executed():
    """Sourcing is the whole point: an executed copy would export into a
    child shell that exits immediately."""
    assert LAB_ENV_SH.is_file()
    text = LAB_ENV_SH.read_text()
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    assert "set -e" not in code, "set -e would kill the operator's shell"
    assert "BASH_SOURCE" in code, "the script must detect how it was invoked"


def test_lab_env_exports_every_value_the_manual_walkthrough_uses():
    text = LAB_ENV_SH.read_text()
    for shell_name, azd_name in EXPORTED_VALUES.items():
        assert shell_name in text, shell_name
        assert azd_name in text, azd_name
    # Whatever mechanism binds them, the values have to leave the script as
    # exported variables the next command can read.
    assert "export" in text


def run_sourced(tmp_path, azd_mode="ok", az_mode="ok", extra=""):
    """Source `lab-env.sh` against stub `azd`/`az` and report what it set."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    azd_stub = {
        "ok": textwrap.dedent(
            """\
            #!/bin/bash
            case "$3" in
              AZURE_RESOURCE_GROUP) echo rg-sre-lab ;;
              AZURE_SUBSCRIPTION_ID) echo 11111111-2222-3333-4444-555555555555 ;;
              AZURE_CONTAINER_APP_NAME) echo ca-sre-lab ;;
              AZURE_CONTAINER_APP_FQDN) echo ca-sre-lab.example.io ;;
              AZURE_CONTAINER_APP_PRINCIPAL_ID) echo 8c8a4f0e-0000-4000-8000-2b1f9a0c1234 ;;
              AZURE_STORAGE_CONTAINER_SCOPE) echo /subscriptions/s/rg/containers/documents ;;
              AZURE_BLOB_ROLE_ASSIGNMENT_NAME) echo 3f2504e0-4f89-11d3-9a0c-0305e82c3301 ;;
              *) echo "" ;;
            esac
            """
        ),
        # azd prints its failure on stdout, after a leading newline, and
        # exits 1 -- adopting that text as a value is the bug this guards.
        "fail": '#!/bin/bash\nprintf "\\nERROR: no environment\\n"\nexit 1\n',
    }[azd_mode]
    (bin_dir / "azd").write_text(azd_stub)
    (bin_dir / "azd").chmod(0o755)

    az_stub = {
        "ok": "#!/bin/bash\necho 11111111-2222-3333-4444-555555555555\n",
        "fail": "#!/bin/bash\nexit 1\n",
    }[az_mode]
    (bin_dir / "az").write_text(az_stub)
    (bin_dir / "az").chmod(0o755)

    script = textwrap.dedent(
        """\
        source "{path}"
        echo "READY=${{LAB_READY}}"
        for name in {names}; do
          eval "printf '%s=%s\\n' \\"${{name}}\\" \\"\\${{${{name}}}}\\""
        done
        {extra}
        """
    ).format(
        path=LAB_ENV_SH,
        names=" ".join(EXPORTED_VALUES),
        extra=extra,
    )
    return subprocess.run(
        ["/bin/bash"],
        input=script,
        text=True,
        capture_output=True,
        cwd=str(LAB_ROOT),
        env={**os.environ, "PATH": "{0}{1}{2}".format(bin_dir, os.pathsep, os.environ["PATH"])},
    )


def parsed(result):
    return dict(
        line.split("=", 1)
        for line in result.stdout.splitlines()
        if "=" in line
    )


def test_sourcing_exports_the_resolved_values(tmp_path):
    result = run_sourced(tmp_path)

    values = parsed(result)
    assert values["READY"] == "1", result.stdout + result.stderr
    assert values["RESOURCE_GROUP"] == "rg-sre-lab"
    assert values["APP_FQDN"] == "ca-sre-lab.example.io"
    assert values["BLOB_ROLE_ASSIGNMENT_NAME"] == "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


def test_a_failed_lookup_reports_zero_and_exports_nothing(tmp_path):
    """azd's error sentence must never become a resource name: a run built
    on it would target `https://ERROR: .../api/orders`."""
    result = run_sourced(tmp_path, azd_mode="fail")

    values = parsed(result)
    assert values["READY"] == "0"
    for shell_name in EXPORTED_VALUES:
        assert values[shell_name] == "", (shell_name, values[shell_name])
    assert "azd" in result.stderr.lower()


def test_sourcing_survives_a_missing_azure_login(tmp_path):
    """A shell that dies on `source` strands the operator with no way to
    read the very message telling them to log in."""
    result = run_sourced(
        tmp_path, az_mode="fail", extra='echo "SHELL_ALIVE=yes"'
    )

    assert "SHELL_ALIVE=yes" in result.stdout
    assert "az login" in result.stdout + result.stderr


def test_sourcing_never_prints_a_secret(tmp_path):
    result = run_sourced(tmp_path)

    combined = (result.stdout + result.stderr).upper()
    for forbidden in ("PASSWORD", "CLIENT_SECRET", "ACCESS_TOKEN", "BEARER "):
        assert forbidden not in combined, forbidden


# --- Guides consume the exported values ------------------------------------


def test_scenario_guides_source_the_environment_once(tmp_path):
    for name in SCENARIO_GUIDES:
        section = manual_section(name)
        assert "source ./scripts/lab-env.sh" in section, name


def test_scenario_guides_stopped_rebinding_each_value():
    """The point of the shared environment is that the walkthrough reads
    values instead of resolving them again in every guide."""
    for name in SCENARIO_GUIDES:
        section = manual_section(name)
        assert "azd env get-value" not in section, name


def test_scenario_guides_still_refuse_to_run_when_the_environment_is_missing():
    for name, scenario in SCENARIO_GUIDES.items():
        section = manual_section(name)
        assert "LAB_READY" in section, name
        assert "begin-run {0}".format(scenario) in section, name


# --- The container can actually run what it promises ------------------------


def test_devcontainer_provides_uv_because_setup_venv_requires_it():
    """`setup-venv.sh` is uv-only by design and exits 1 without it, so a
    container that runs it in postCreate must install uv or every Codespace
    starts with a failed lifecycle hook and no `app/.venv`."""
    config = json.loads(DEVCONTAINER.read_text())
    lifecycle = " ".join(
        str(config.get(hook, ""))
        for hook in ("onCreateCommand", "postCreateCommand", "postStartCommand")
    )
    if "setup-venv.sh" not in lifecycle:
        return
    raw = DEVCONTAINER.read_text()
    assert "uv" in raw, (
        "setup-venv.sh refuses to run without uv; the container must supply it"
    )


# --- The repository URL never carries a credential --------------------------


def normalized_repo_url(remote):
    """Ask `lab-env.sh` itself what it would publish for a given remote."""
    script = (
        'source "{path}" >/dev/null 2>&1\n'
        'lab_env_normalize_repo_url "{remote}"\n'
    ).format(path=LAB_ENV_SH, remote=remote)
    result = subprocess.run(
        ["/bin/bash"], input=script, text=True, capture_output=True,
        cwd=str(LAB_ROOT),
    )
    return result.stdout.strip()


def test_a_password_containing_an_at_sign_leaves_nothing_behind():
    """A basic-auth password may itself contain `@`; git reads the *last*
    one as the delimiter. Rebuilding a URL from such a remote would keep the
    tail of the secret, so the remote is dropped instead."""
    published = normalized_repo_url("https://me:p@ssw0rd@github.com/me/repo.git")

    assert "ssw0rd" not in published, published
    assert published == ""


def test_a_remote_with_an_embedded_token_is_refused(tmp_path):
    """Cloning with `https://user:<PAT>@github.com/...` is routine behind a
    corporate proxy. Publishing that remote would put the token in the
    terminal, in scrollback, and in every child process."""
    token = "ghp_000000000000000000000000000000000000"

    published = normalized_repo_url(
        "https://x-access-token:{0}@github.com/acme/lab.git".format(token)
    )

    assert token not in published, "the credential survived normalization"
    assert "x-access-token" not in published
    assert published in ("", "https://github.com/acme/lab")


def test_an_ssh_remote_becomes_the_https_form_the_connector_expects():
    assert normalized_repo_url("git@github.com:acme/lab.git") == (
        "https://github.com/acme/lab"
    )


def test_a_plain_https_remote_is_published_without_its_git_suffix():
    assert normalized_repo_url("https://github.com/acme/lab.git") == (
        "https://github.com/acme/lab"
    )
