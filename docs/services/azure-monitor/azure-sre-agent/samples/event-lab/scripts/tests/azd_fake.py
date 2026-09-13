"""A fake `azd` that reproduces azd 1.29.0's observable command contract.

Recorded from the real CLI (`azd version 1.29.0`) on 2026-08-14:

```
$ azd env get-value MISSING            # inside the project, no environment
rc=1, stdout="\nERROR: ensuring environment exists: environment not specified"

$ azd env get-value AZURE_LOCATION     # outside any azd project
rc=1, stdout="\nERROR: no project exists; to create a new project, run `azd init`"

$ azd env get-value AZURE_LOCATION --cwd <project>   # from any cwd
rc=1, stdout="\nERROR: ensuring environment exists: environment not specified"

$ azd auth login --check-status
rc=0, stdout="Logged in to Azure as <account>"

$ azd auth login --check-status --output json
rc=0, stdout='{"status": "success", "expiresOn": "2026-08-14T07:57:15Z"}'
```

Three properties matter for `common.sh` and its callers, and are therefore
modelled here:

1. azd writes its `ERROR:` diagnostics to **stdout**, not stderr, and signals
   failure only through the exit status. A caller that keeps stdout when the
   command failed silently adopts the error text as a configuration value.
2. azd resolves the project from `--cwd` when given, otherwise from the
   process working directory, and fails when that directory holds no
   `azure.yaml`. A lookup that does not pin the project root breaks as soon
   as a script is invoked from the repository root or any other directory.
3. `azd auth login --check-status` is the one non-interactive way to read the
   login state, and it **always exits 0** -- "In check status mode, we always
   print the final status to stdout. ... We always return a zero exit code."
   (`cli/azd/cmd/auth_login.go`). The answer lives only in the output:
   `{"status": "success"}` or `{"status": "unauthenticated"}` under
   `--output json`, a human sentence otherwise. A caller that trusts the exit
   status reports every signed-out operator as signed in.

`MISSING_KEY_MODES` exposes both observed missing-value shapes so tests can
prove the reader is driven by the exit status rather than by stdout text.
"""
import stat


NO_PROJECT_ERROR = (
    "\nERROR: no project exists; to create a new project, run `azd init`"
)
NO_ENVIRONMENT_ERROR = (
    "\nERROR: ensuring environment exists: environment not specified"
)
LOGGED_IN_MESSAGE = "Logged in to Azure as lab-operator@example.com"
NOT_LOGGED_IN_MESSAGE = "Not logged in, run `azd auth login` to login to Azure"

# How the fake reports a value it does not have.
#   "azd_1_29" -- what the real CLI does: ERROR text on stdout, exit 1.
#   "silent"   -- nothing on stdout, exit 1 (the shape the first version of
#                 this harness assumed).
MISSING_KEY_MODES = ("azd_1_29", "silent")


def _missing_key_branch(missing_key_mode):
    if missing_key_mode not in MISSING_KEY_MODES:
        raise ValueError(f"unknown missing_key_mode: {missing_key_mode}")
    if missing_key_mode == "silent":
        return "    exit 1"
    return f"    printf '%s\\n' '{NO_ENVIRONMENT_ERROR.lstrip(chr(10))}'\n    exit 1"


def azd_stub_source(azd_values, missing_key_mode="azd_1_29", log_path=None, logged_in=True):
    """Bash source for a fake `azd` honouring the contract described above."""
    lines = [
        "#!/usr/bin/env bash",
        "project_dir=\"${PWD}\"",
        "argv=()",
        "while [[ \"$#\" -gt 0 ]]; do",
        "  case \"$1\" in",
        "    --cwd|-C) project_dir=\"$2\"; shift 2 ;;",
        "    --cwd=*) project_dir=\"${1#--cwd=}\"; shift ;;",
        "    *) argv+=(\"$1\"); shift ;;",
        "  esac",
        "done",
    ]
    if log_path is not None:
        # `%q` per argument, not `"${argv[*]}"`: a value azd is asked to
        # clear (`azd env set KEY ""`) is an empty argument, which would
        # otherwise vanish from the log and read exactly like a call that
        # never happened.
        lines.append(f'printf \'%q \' "${{argv[@]}}" >> "{log_path}"')
        lines.append(f'printf \'\\n\' >> "{log_path}"')
        lines.append(f'printf \'cwd=%s\\n\' "${{project_dir}}" >> "{log_path}"')
    status_json = (
        '{"status": "success", "expiresOn": "2026-08-14T07:57:15Z"}'
        if logged_in
        else '{"status": "unauthenticated"}'
    )
    status_message = LOGGED_IN_MESSAGE if logged_in else NOT_LOGGED_IN_MESSAGE
    lines += [
        # `auth` needs no azd project. `--check-status` never fails: the exit
        # code is 0 whether or not anyone is signed in, so only the printed
        # status carries the answer.
        'if [[ "${argv[0]:-}" == "auth" ]]; then',
        '  if [[ "${argv[*]:-}" == *--check-status* ]]; then',
        '    if [[ "${argv[*]:-}" == *"--output json"* ]]; then',
        f"      printf '%s\\n' '{status_json}'",
        "    else",
        f"      printf '%s\\n' '{status_message}'",
        "    fi",
        "  fi",
        "  exit 0",
        "fi",
    ]
    lines += [
        '# Only the `env` commands need an azd project; `auth` does not.',
        'if [[ "${argv[0]:-}" == "env" && ! -f "${project_dir}/azure.yaml" ]]; then',
        f"  printf '%s\\n' '{NO_PROJECT_ERROR.lstrip(chr(10))}'",
        "  exit 1",
        "fi",
        'if [[ "${argv[0]:-}" == "env" && "${argv[1]:-}" == "get-value" ]]; then',
        '  case "${argv[2]:-}" in',
    ]
    for name, value in azd_values.items():
        escaped = str(value).replace("'", "'\\''")
        lines.append(f"    {name}) printf '%s\\n' '{escaped}'; exit 0 ;;")
    lines.append("    *)")
    lines.append(_missing_key_branch(missing_key_mode))
    lines.append("      ;;")
    lines.append("  esac")
    lines.append("fi")
    lines.append('if [[ "${argv[0]:-}" == "env" && "${argv[1]:-}" == "set" ]]; then')
    lines.append("  exit 0")
    lines.append("fi")
    lines.append('printf \'azd stub: unsupported invocation: %s\\n\' "${argv[*]:-}" >&2')
    lines.append("exit 1")
    return "\n".join(lines) + "\n"


def write_executable(path, content):
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def write_azd_stub(bin_dir, azd_values, missing_key_mode="azd_1_29", log_path=None, logged_in=True):
    return write_executable(
        bin_dir / "azd",
        azd_stub_source(azd_values, missing_key_mode, log_path, logged_in),
    )
