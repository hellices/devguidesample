"""Sanitized, fixed Azure Resource Manager resource-group lookup.

Reads exactly one resource group, at one pinned api-version. The bearer
attached here is always the token `obo.py` exchanged for
`https://management.azure.com/.default`; this module never sees, and cannot
accidentally forward, the inbound MCP caller's own token. The response is
reduced to booleans and the region: no resource IDs or names cross this
boundary into a tool result.
"""

from __future__ import annotations

from typing import Protocol

import httpx
from pydantic import BaseModel

#: The one ARM api-version this lab reads against. Fixed, not caller-configurable.
ARM_API_VERSION = "2024-03-01"

_ARM_BASE_URL = "https://management.azure.com"


class ArmError(Exception):
    """A resource-group read failed. `safe_code` is the only detail meant to reach a caller."""

    def __init__(self, safe_code: str, http_status: int | None = None) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code
        self.http_status = http_status


class ResourceGroupStatus(BaseModel):
    exists: bool
    region: str | None = None
    provisioning_succeeded: bool | None = None


class ArmResourceGroupReader(Protocol):
    async def read(
        self, *, subscription_id: str, resource_group: str, bearer_token: str
    ) -> ResourceGroupStatus: ...  # pragma: no cover


class HttpArmResourceGroupReader:
    """Production reader: one fixed ARM GET over `httpx`.

    Pass a shared `client` to reuse connections; otherwise a short-lived
    client is created per call, which is fine for a low-traffic lab tool.
    """

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def read(
        self, *, subscription_id: str, resource_group: str, bearer_token: str
    ) -> ResourceGroupStatus:
        url = f"{_ARM_BASE_URL}/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        headers = {"Authorization": f"Bearer {bearer_token}"}
        params = {"api-version": ARM_API_VERSION}

        if self._client is not None:
            response = await self._get(self._client, url, headers, params)
        else:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await self._get(client, url, headers, params)
        return self._parse(response)

    @staticmethod
    async def _get(
        client: httpx.AsyncClient, url: str, headers: dict[str, str], params: dict[str, str]
    ) -> httpx.Response:
        try:
            return await client.get(url, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            raise ArmError("Timeout") from exc
        except httpx.HTTPError as exc:
            raise ArmError("NetworkUnavailable") from exc

    @staticmethod
    def _parse(response: httpx.Response) -> ResourceGroupStatus:
        if response.status_code == 404:
            return ResourceGroupStatus(exists=False, region=None, provisioning_succeeded=None)
        if response.status_code in (401, 403):
            raise ArmError("AuthorizationFailed", response.status_code)
        if response.status_code >= 400:
            raise ArmError("HttpError", response.status_code)

        body = response.json()
        properties = body.get("properties") or {}
        return ResourceGroupStatus(
            exists=True,
            region=body.get("location"),
            provisioning_succeeded=properties.get("provisioningState") == "Succeeded",
        )
