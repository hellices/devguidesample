import pytest

from service.config import ConfigError, load_config

VALID_ENV = {
    "ENTRA_TENANT_ID": "11111111-1111-1111-1111-111111111111",
    "ENTRA_API_CLIENT_ID": "22222222-2222-2222-2222-222222222222",
    "ENTRA_API_CLIENT_SECRET": "lab-secret-value",
    "MCP_RESOURCE_URL": "https://mcp-lab.internal.example/mcp",
    "LAB_SUBSCRIPTION_ID": "33333333-3333-3333-3333-333333333333",
    "LAB_RESOURCE_GROUP": "rg-mcp-lab",
    "ENTRA_ALLOWED_CLIENT_IDS": "11111111-aaaa-bbbb-cccc-222222222222",
}


def test_loads_a_fully_valid_environment():
    config = load_config(VALID_ENV)
    assert config.tenant_id == "11111111-1111-1111-1111-111111111111"
    assert config.api_client_id == "22222222-2222-2222-2222-222222222222"
    assert config.resource_url == "https://mcp-lab.internal.example/mcp"
    assert config.allowed_client_ids == frozenset({"11111111-aaaa-bbbb-cccc-222222222222"})
    assert config.issuer == "https://login.microsoftonline.com/11111111-1111-1111-1111-111111111111/v2.0"
    assert config.jwks_uri == (
        "https://login.microsoftonline.com/11111111-1111-1111-1111-111111111111/discovery/v2.0/keys"
    )


def test_empty_environment_is_rejected():
    with pytest.raises(ConfigError):
        load_config({})


@pytest.mark.parametrize(
    "missing",
    [
        "ENTRA_TENANT_ID",
        "ENTRA_API_CLIENT_ID",
        "ENTRA_API_CLIENT_SECRET",
        "MCP_RESOURCE_URL",
        "LAB_SUBSCRIPTION_ID",
        "LAB_RESOURCE_GROUP",
        "ENTRA_ALLOWED_CLIENT_IDS",
    ],
)
def test_each_required_variable_is_mandatory(missing):
    env = dict(VALID_ENV)
    del env[missing]
    with pytest.raises(ConfigError):
        load_config(env)


@pytest.mark.parametrize(
    "missing",
    [
        "ENTRA_TENANT_ID",
        "ENTRA_API_CLIENT_ID",
        "ENTRA_API_CLIENT_SECRET",
        "MCP_RESOURCE_URL",
        "LAB_SUBSCRIPTION_ID",
        "LAB_RESOURCE_GROUP",
        "ENTRA_ALLOWED_CLIENT_IDS",
    ],
)
def test_blank_value_is_treated_as_missing(missing):
    env = dict(VALID_ENV)
    env[missing] = "   "
    with pytest.raises(ConfigError):
        load_config(env)


def test_rejects_non_guid_client_id():
    env = dict(VALID_ENV, ENTRA_API_CLIENT_ID="not-a-guid")
    with pytest.raises(ConfigError, match="ENTRA_API_CLIENT_ID"):
        load_config(env)


def test_rejects_non_guid_subscription_id():
    env = dict(VALID_ENV, LAB_SUBSCRIPTION_ID="not-a-guid")
    with pytest.raises(ConfigError, match="LAB_SUBSCRIPTION_ID"):
        load_config(env)


def test_guid_fields_are_lowercased():
    env = dict(VALID_ENV, ENTRA_API_CLIENT_ID="22222222-2222-2222-2222-222222222222".upper())
    config = load_config(env)
    assert config.api_client_id == "22222222-2222-2222-2222-222222222222"


@pytest.mark.parametrize(
    "resource_url",
    [
        "http://mcp-lab.internal.example/mcp",  # plain http, never permitted
        "ftp://mcp-lab.internal.example/mcp",
        "not-a-url",
        "https://",
    ],
)
def test_resource_url_must_be_an_absolute_https_url(resource_url):
    env = dict(VALID_ENV, MCP_RESOURCE_URL=resource_url)
    with pytest.raises(ConfigError, match="MCP_RESOURCE_URL"):
        load_config(env)


@pytest.mark.parametrize("resource_group", ["rg/with/slash", "rg with space?", "trailing.", ""])
def test_rejects_malformed_resource_group_names(resource_group):
    env = dict(VALID_ENV, LAB_RESOURCE_GROUP=resource_group)
    with pytest.raises(ConfigError):
        load_config(env)


def test_tenant_id_rejects_unsafe_characters():
    env = dict(VALID_ENV, ENTRA_TENANT_ID="tenant/with/slash")
    with pytest.raises(ConfigError, match="ENTRA_TENANT_ID"):
        load_config(env)


def test_tenant_id_requires_a_guid_for_exact_v2_issuer_matching():
    env = dict(VALID_ENV, ENTRA_TENANT_ID="contoso.onmicrosoft.com")
    with pytest.raises(ConfigError, match="ENTRA_TENANT_ID"):
        load_config(env)


def test_allowed_client_ids_are_required():
    env = dict(VALID_ENV)
    del env["ENTRA_ALLOWED_CLIENT_IDS"]
    with pytest.raises(ConfigError, match="ENTRA_ALLOWED_CLIENT_IDS"):
        load_config(env)


def test_allowed_client_ids_parses_csv_and_lowercases():
    guid_a = "44444444-4444-4444-4444-444444444444"
    guid_b = "55555555-5555-5555-5555-555555555555"
    env = dict(VALID_ENV, ENTRA_ALLOWED_CLIENT_IDS=f" {guid_a.upper()} , {guid_b} ,")
    config = load_config(env)
    assert config.allowed_client_ids == frozenset({guid_a, guid_b})


def test_allowed_client_ids_rejects_a_non_guid_entry():
    env = dict(VALID_ENV, ENTRA_ALLOWED_CLIENT_IDS="not-a-guid")
    with pytest.raises(ConfigError, match="ENTRA_ALLOWED_CLIENT_IDS"):
        load_config(env)


def test_allowed_client_ids_blank_string_is_rejected():
    env = dict(VALID_ENV, ENTRA_ALLOWED_CLIENT_IDS="   ")
    with pytest.raises(ConfigError, match="ENTRA_ALLOWED_CLIENT_IDS"):
        load_config(env)


def test_config_is_immutable():
    config = load_config(VALID_ENV)
    with pytest.raises(AttributeError):
        config.tenant_id = "other"  # type: ignore[misc]
