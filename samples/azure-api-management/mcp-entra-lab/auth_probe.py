"""Exercise real delegated tokens and OBO without writing tokens to evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
import jwt
import msal

from cloud_lab import az_json, load_state, private_path
from entra_setup import verify_binding
from evidence import check, write_results


def safe_obo_error(result: dict) -> str:
    for code in result.get("error_codes", []):
        if type(code) is int and 10000 <= code <= 999999999:
            return f"AADSTS{code}"
    return "AuthenticationFailed"


def api_token(state_path: Path, key: str) -> str:
    state = load_state(state_path)
    identities = load_state(state_path.with_name("identities.json"))
    verify_binding(identities, state)
    app = identities[key]
    response = az_json(
        [
            "account", "get-access-token", "--tenant", state["tenant_id"],
            "--scope", f"{app['identifier_uri']}/{app['scope_name']}",
        ],
        state_path,
    )
    return response["accessToken"]


def verified_claims(token: str, tenant: str, audience: str) -> dict:
    keys = jwt.PyJWKClient(
        f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
        timeout=30,
    )
    key = keys.get_signing_key_from_jwt(token).key
    return jwt.decode(
        token, key, algorithms=["RS256"], audience=audience,
        issuer=f"https://login.microsoftonline.com/{tenant}/v2.0",
        options={"require": ["exp", "iss", "aud", "tid", "scp", "oid"]},
        leeway=30,
    )


def run(state_path: Path, output: Path) -> int:
    write_results(output, [])
    state = load_state(state_path)
    identities = load_state(state_path.with_name("identities.json"))
    verify_binding(identities, state)
    results = []
    tokens = {}
    for key, identifier in (
        ("custom_api", "custom-api-user-token"),
        ("azure_api", "native-azure-user-token"),
    ):
        token = api_token(state_path, key)
        claims = verified_claims(
            token, state["tenant_id"], identities[key]["client_id"]
        )
        scope_matched = identities[key]["scope_name"] in claims["scp"].split()
        tenant_matched = claims["tid"] == state["tenant_id"]
        results.append(check(
            identifier, "live",
            "passed" if scope_matched and tenant_matched else "failed",
            audience_matched=True, scope_matched=scope_matched,
        ))
        if not scope_matched or not tenant_matched:
            write_results(output, results)
            raise RuntimeError("Azure returned a token outside the intended tenant/scope")
        tokens[key] = token
        write_results(output, results)

    custom = identities["custom_api"]
    confidential = msal.ConfidentialClientApplication(
        custom["client_id"],
        authority=f"https://login.microsoftonline.com/{state['tenant_id']}",
        client_credential=custom["client_secret"],
        enable_pii_log=False,
    )
    exchange = confidential.acquire_token_on_behalf_of(
        user_assertion=tokens["custom_api"],
        scopes=["https://management.azure.com/.default"],
    )
    if "access_token" not in exchange:
        results.append(check(
            "custom-obo-arm-local", "live", "blocked",
            error_code=safe_obo_error(exchange),
        ))
        write_results(output, results)
        print("OBO blocked:", safe_obo_error(exchange))
        return 1
    arm_url = (
        f"https://management.azure.com/subscriptions/{state['subscription_id']}"
        f"/resourcegroups/{state['resource_group']}?api-version=2024-03-01"
    )
    with httpx.Client(timeout=60) as client:
        response = client.get(
            arm_url, headers={"Authorization": "Bearer " + exchange["access_token"]}
        )
        authorized = (
            response.status_code == 200
            and response.json().get("tags", {}).get("labId") == state["suffix"]
        )
        results.append(check(
            "custom-obo-arm-local", "live", "passed" if authorized else "failed",
            http_status=response.status_code, obo=True, downstream_authorized=authorized,
        ))
        wrong_audience = client.get(
            arm_url, headers={"Authorization": "Bearer " + tokens["custom_api"]}
        )
        results.append(check(
            "arm-rejects-mcp-token", "live",
            "passed" if wrong_audience.status_code == 401 else "failed",
            http_status=wrong_audience.status_code,
        ))
    if all(item["status"] == "passed" for item in results):
        results.append(check("auth-suite-complete", "live", "passed", result_count=len(results)))
    write_results(output, results)
    print(json.dumps({
        "checks": len(results),
        "passed": sum(item["status"] == "passed" for item in results),
        "note": "Live Azure exchange from local code; not a hosted-MCP or PKCE-client proof.",
    }))
    return 0 if all(item["status"] == "passed" for item in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return run(private_path(args.state), args.output)


if __name__ == "__main__":
    raise SystemExit(main())
