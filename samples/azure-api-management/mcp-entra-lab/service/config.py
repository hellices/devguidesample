"""Environment configuration, validated fail-closed.

There is no permissive default: `load_config` raises `ConfigError` for any
missing or malformed setting, so `create_app()` refuses to build a server
rather than start one with an implicit "accept anything" auth posture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit

_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
REQUIRED_SCOPE = "Mcp.Access"
# Azure resource group names: alphanumerics, underscore, parentheses, hyphen, period,
# Unicode letters (\w is Unicode-aware for str patterns); trailing period is rejected below.
_RESOURCE_GROUP_RE = re.compile(r"^[\w().-]{1,90}$", re.UNICODE)


class ConfigError(ValueError):
    """The environment is missing a required setting or one is malformed."""


@dataclass(frozen=True, slots=True)
class Config:
    tenant_id: str
    api_client_id: str
    api_client_secret: str = field(repr=False)
    resource_url: str
    subscription_id: str
    resource_group: str
    allowed_client_ids: frozenset[str]

    @property
    def scope_prefix(self) -> str:
        return f"api://{self.api_client_id}/"

    @property
    def scope_uri(self) -> str:
        return self.scope_prefix + REQUIRED_SCOPE

    @property
    def issuer(self) -> str:
        """The Entra v2 issuer for this tenant, matched exactly against `iss`."""
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

    @property
    def jwks_uri(self) -> str:
        """The tenant's JSON Web Key Set endpoint, used to verify token signatures."""
        return f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys"


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required and must not be empty")
    return value


def _require_guid(env: Mapping[str, str], name: str) -> str:
    value = _require(env, name)
    if not _GUID_RE.match(value):
        raise ConfigError(f"{name} must be a GUID, got {value!r}")
    return value.lower()


def _require_https_url(env: Mapping[str, str], name: str) -> str:
    value = _require(env, name)
    parts = urlsplit(value)
    if (
        parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443)
        or parts.username is not None or parts.password is not None
        or parts.query or parts.fragment or parts.path != "/mcp"
    ):
        raise ConfigError(f"{name} must be a credential-free https:// URL ending in /mcp")
    return value


def _require_resource_group(env: Mapping[str, str], name: str) -> str:
    value = _require(env, name)
    if not _RESOURCE_GROUP_RE.match(value) or value.endswith("."):
        raise ConfigError(f"{name} is not a valid Azure resource group name: {value!r}")
    return value


def _parse_allowed_client_ids(env: Mapping[str, str]) -> frozenset[str]:
    raw = _require(env, "ENTRA_ALLOWED_CLIENT_IDS")
    ids: set[str] = set()
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        if not _GUID_RE.match(candidate):
            raise ConfigError(
                f"ENTRA_ALLOWED_CLIENT_IDS contains a non-GUID entry: {candidate!r}"
            )
        ids.add(candidate.lower())
    if not ids:
        raise ConfigError(
            "ENTRA_ALLOWED_CLIENT_IDS is set but contains no usable client IDs"
        )
    return frozenset(ids)


def load_config(env: Mapping[str, str]) -> Config:
    """Build a `Config` from an environment mapping, or raise `ConfigError`.

    Every required setting is checked; nothing is defaulted to a permissive
    value. Call this once at process startup (`create_app()` does), not per
    request.
    """
    return Config(
        tenant_id=_require_guid(env, "ENTRA_TENANT_ID"),
        api_client_id=_require_guid(env, "ENTRA_API_CLIENT_ID"),
        api_client_secret=_require(env, "ENTRA_API_CLIENT_SECRET"),
        resource_url=_require_https_url(env, "MCP_RESOURCE_URL"),
        subscription_id=_require_guid(env, "LAB_SUBSCRIPTION_ID"),
        resource_group=_require_resource_group(env, "LAB_RESOURCE_GROUP"),
        allowed_client_ids=_parse_allowed_client_ids(env),
    )
