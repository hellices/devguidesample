#!/usr/bin/env bash
# Resolves the lab's configuration once and exports it into the current
# shell. Source it; do not execute it:
#
#   cd monitor/sre-agent-event-lab
#   source ./scripts/lab-env.sh
#
# Every value here is a name, an ID or a URL that `azd provision` already
# published as a deployment output. Nothing secret is read, printed or
# written: authentication stays in the Azure CLI and azd credential stores.
#
# Why sourcing rather than a wrapper: the scenario walkthroughs are meant to
# be read and run command by command, and each command needs the same values.
# Resolving them once, in the operator's own shell, keeps every later step a
# plain `az` invocation instead of a nested substitution.
#
# `set -e` is deliberately absent. A sourced script runs in the operator's
# interactive shell, so a failed lookup here must set `LAB_READY=0` and
# explain itself -- never close the terminal that is about to show why.

# Refuse to run as a program: exports would land in a child shell that exits
# immediately, and the operator would be left with an empty environment and
# no error. `BASH_SOURCE` is also how this file finds itself, so an empty
# value means a non-bash shell (zsh is macOS's default) where the path
# resolution below would silently point at the wrong directory.
if [[ -z "${BASH_SOURCE[0]:-}" ]]; then
  echo "lab-env.sh needs bash. Start one first, then source it:" >&2
  echo "  bash" >&2
  echo "  source ./scripts/lab-env.sh" >&2
  return 1 2>/dev/null || exit 1
fi

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "lab-env.sh must be sourced, not executed:" >&2
  echo "  source ./scripts/lab-env.sh" >&2
  exit 2
fi

LAB_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LAB_ROOT="$(cd "${LAB_ENV_DIR}/.." && pwd -P)"
export LAB_ROOT

# Refuse to resolve against a directory that is not this lab: every lookup
# below is `--cwd "${LAB_ROOT}"`, and a wrong root would bind another azd
# project's outputs -- which the S3 scenario would then delete a role from.
if [[ ! -f "${LAB_ROOT}/azure.yaml" ]]; then
  echo "Not the lab directory: ${LAB_ROOT}/azure.yaml is missing." >&2
  return 1 2>/dev/null || exit 1
fi

LAB_READY=1
export LAB_READY

# lab_env_read NAME -- one azd output, or empty when azd could not answer.
#
# azd reports failure only through its exit status: it prints an `ERROR: ...`
# sentence on *stdout* (after a leading newline) and exits 1, so keeping
# stdout regardless of the status would adopt that sentence as a resource
# name. `--cwd` pins the lookup to this lab's azd project so the script works
# from any directory.
lab_env_read() {
  local name="$1"
  local value
  if ! value="$(azd env get-value "${name}" --cwd "${LAB_ROOT}" 2>/dev/null)"; then
    return 1
  fi
  # A blank answer is not a value: azd prints nothing for an output the
  # current environment has never had.
  if [[ -z "${value//[[:space:]]/}" ]]; then
    return 1
  fi
  printf '%s\n' "${value}"
}

# lab_env_bind SHELL_NAME AZD_NAME -- export one resolved value, or clear it
# and lower LAB_READY when it cannot be resolved.
lab_env_bind() {
  local shell_name="$1"
  local azd_name="$2"
  local value
  if value="$(lab_env_read "${azd_name}")"; then
    printf -v "${shell_name}" '%s' "${value}"
    export "${shell_name?}"
    return 0
  fi
  printf -v "${shell_name}" '%s' ""
  export "${shell_name?}"
  LAB_READY=0
  echo "Missing deployment output: ${azd_name}" >&2
  return 1
}

if ! command -v azd >/dev/null 2>&1; then
  LAB_READY=0
  echo "azd not found on PATH. In Codespaces this comes from the devcontainer." >&2
fi

if ! command -v az >/dev/null 2>&1; then
  LAB_READY=0
  echo "az not found on PATH. In Codespaces this comes from the devcontainer." >&2
fi

# The Azure CLI session is what every later command runs as. Report it as a
# prerequisite rather than letting the first `az` call fail mid-scenario.
LAB_ACTIVE_SUBSCRIPTION=""
if command -v az >/dev/null 2>&1; then
  if ! LAB_ACTIVE_SUBSCRIPTION="$(az account show --query id -o tsv 2>/dev/null)"; then
    LAB_READY=0
    LAB_ACTIVE_SUBSCRIPTION=""
    echo "Not signed in to Azure CLI. Run: az login --use-device-code" >&2
  fi
fi

lab_env_bind RESOURCE_GROUP AZURE_RESOURCE_GROUP || true
lab_env_bind SUBSCRIPTION_ID AZURE_SUBSCRIPTION_ID || true
lab_env_bind APP_NAME AZURE_CONTAINER_APP_NAME || true
lab_env_bind APP_FQDN AZURE_CONTAINER_APP_FQDN || true
lab_env_bind WORKLOAD_PRINCIPAL_ID AZURE_CONTAINER_APP_PRINCIPAL_ID || true
lab_env_bind STORAGE_CONTAINER_SCOPE AZURE_STORAGE_CONTAINER_SCOPE || true
lab_env_bind BLOB_ROLE_ASSIGNMENT_NAME AZURE_BLOB_ROLE_ASSIGNMENT_NAME || true
lab_env_bind WORKSPACE_CUSTOMER_ID AZURE_WORKSPACE_CUSTOMER_ID || true
lab_env_bind TELEMETRY_SERVICE_NAME AZURE_TELEMETRY_SERVICE_NAME || true

# The manual walkthrough issues `az` commands that inherit the CLI's active
# subscription, so a mismatch would inject the failure into a same-named
# resource group somewhere else. `common.sh` refuses this for the scripted
# path; the sourced environment is where the manual path can catch it.
if [[ -n "${LAB_ACTIVE_SUBSCRIPTION}" && -n "${SUBSCRIPTION_ID}" ]]; then
  if [[ "$(printf '%s' "${LAB_ACTIVE_SUBSCRIPTION}" | tr '[:upper:]' '[:lower:]')" \
     != "$(printf '%s' "${SUBSCRIPTION_ID}" | tr '[:upper:]' '[:lower:]')" ]]; then
    LAB_READY=0
    echo "Active Azure CLI subscription is not the lab's." >&2
    echo "  active: ${LAB_ACTIVE_SUBSCRIPTION}" >&2
    echo "  lab   : ${SUBSCRIPTION_ID}" >&2
    echo "Switch with: az account set --subscription ${SUBSCRIPTION_ID}" >&2
  fi
fi

# lab_env_normalize_repo_url REMOTE -- the HTTPS form of a git remote, or
# empty when it cannot be published safely.
#
# A remote cloned behind a proxy can carry credentials
# (`https://user:<token>@host/owner/repo`). Printing or exporting that would
# put the token in the terminal, in scrollback and in every child process,
# so a remote whose authority carries userinfo is dropped entirely rather
# than rewritten: a password may itself contain `@`, and reconstructing a
# "clean" URL from it risks keeping part of the secret. The operator is
# asked for the URL instead. SSH remotes are rewritten because the Agent's
# source connector takes an HTTPS URL.
lab_env_normalize_repo_url() {
  local remote="$1"
  [[ -n "${remote}" ]] || return 0

  local url="${remote%.git}"
  case "${url}" in
    git@*:*)
      local host="${url#git@}"
      host="${host%%:*}"
      local path="${url#*:}"
      printf 'https://%s/%s\n' "${host}" "${path#/}"
      return 0
      ;;
    ssh://*)
      url="https://${url#ssh://}"
      ;;
  esac

  case "${url}" in
    *://*)
      local scheme="${url%%://*}"
      local rest="${url#*://}"
      local authority="${rest%%/*}"
      case "${authority}" in
        *@*)
          # `git@host` is the SSH identity, not a credential; anything else
          # in the userinfo position is treated as one and refused.
          if [[ "${authority%@*}" == "git" ]]; then
            printf '%s://%s\n' "${scheme}" "${rest#*@}"
            return 0
          fi
          echo "Ignoring the git remote: it embeds credentials." >&2
          echo "Set the repository explicitly: azd env set SRE_REPOSITORY_URL \"https://github.com/<owner>/<repo>\"" >&2
          return 0
          ;;
      esac
      printf '%s\n' "${url}"
      return 0
      ;;
  esac
  return 0
}

# The repository the Agent investigates and files issues into. It must be
# the operator's own fork: the GitHub connector writes into whatever
# repository it is connected to, and a shared upstream would collect every
# participant's incidents.
SRE_REPOSITORY_URL="$(lab_env_read SRE_REPOSITORY_URL || true)"
if [[ -z "${SRE_REPOSITORY_URL}" ]] && command -v git >/dev/null 2>&1; then
  # `origin` in a Codespace created from a fork is that fork, which is
  # exactly the repository the Agent should be pointed at. It is only a
  # suggestion: the operator confirms it when running `azd env set`.
  SRE_REPOSITORY_URL="$(lab_env_normalize_repo_url \
    "$(git -C "${LAB_ROOT}" remote get-url origin 2>/dev/null || true)")"
fi
export SRE_REPOSITORY_URL

if (( LAB_READY )); then
  echo "Lab environment ready."
else
  echo "Lab environment incomplete. Run 'azd provision' (or fix the errors above), then source this file again." >&2
fi

cat <<SUMMARY
  Resource group : ${RESOURCE_GROUP:-<unset>}
  Subscription   : ${SUBSCRIPTION_ID:-<unset>}
  Container App  : ${APP_NAME:-<unset>}
  Endpoint       : ${APP_FQDN:-<unset>}
  Repository     : ${SRE_REPOSITORY_URL:-<unset>}
SUMMARY
