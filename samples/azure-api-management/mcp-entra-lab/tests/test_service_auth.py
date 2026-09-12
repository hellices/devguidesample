import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from service.auth import REQUIRED_SCOPE, EntraTokenVerifier, StaticSigningKeyResolver
from test_service_helpers import (
    OMIT,
    build_test_config,
    generate_rsa_keypair,
    make_hs256_confusion_token,
    make_token,
    run_async,
)

PRIVATE_KEY, PUBLIC_KEY = generate_rsa_keypair()
CONFIG = build_test_config()


def _verifier(**config_overrides) -> EntraTokenVerifier:
    config = build_test_config(**config_overrides) if config_overrides else CONFIG
    return EntraTokenVerifier(config, key_resolver=StaticSigningKeyResolver(public_key=PUBLIC_KEY))


def test_accepts_a_fully_valid_delegated_token():
    token = make_token(PRIVATE_KEY, CONFIG)

    result = run_async(lambda: _verifier().verify_token(token))

    assert result is not None
    assert result.client_id == "11111111-aaaa-bbbb-cccc-222222222222"
    assert result.scopes == [CONFIG.scope_uri]
    assert result.subject == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert result.resource == CONFIG.resource_url
    assert result.token == token


def test_rejects_wrong_audience():
    token = make_token(PRIVATE_KEY, CONFIG, aud="99999999-9999-9999-9999-999999999999")
    assert run_async(lambda: _verifier().verify_token(token)) is None


@pytest.mark.parametrize(
    "arm_style_audience",
    [
        "https://management.azure.com",
        "https://management.azure.com/",
        "https://management.core.windows.net/",
        "api://some-other-registered-api",
    ],
)
def test_rejects_arm_or_arbitrary_api_audience_tokens(arm_style_audience):
    # A real ARM access token (or any other API's token) must never be
    # accepted just because it is a validly-signed Entra token: the audience
    # must be exactly this app's client id, nothing else.
    token = make_token(PRIVATE_KEY, CONFIG, aud=arm_style_audience)
    assert run_async(lambda: _verifier().verify_token(token)) is None


def test_rejects_wrong_issuer():
    token = make_token(
        PRIVATE_KEY, CONFIG, iss="https://login.microsoftonline.com/other-tenant/v2.0"
    )
    assert run_async(lambda: _verifier().verify_token(token)) is None


def test_rejects_tid_mismatch_even_if_issuer_string_matched():
    # A same-shaped issuer string but a different `tid` claim: defense in
    # depth beyond the `iss` string comparison alone.
    token = make_token(PRIVATE_KEY, CONFIG, tid="66666666-6666-6666-6666-666666666666")
    assert run_async(lambda: _verifier().verify_token(token)) is None


def test_rejects_expired_token():
    token = make_token(PRIVATE_KEY, CONFIG, exp=1)
    assert run_async(lambda: _verifier().verify_token(token)) is None


def test_rejects_not_yet_valid_token():
    import time

    token = make_token(PRIVATE_KEY, CONFIG, nbf=int(time.time()) + 3600)
    assert run_async(lambda: _verifier().verify_token(token)) is None


def test_rejects_token_missing_exp():
    token = make_token(PRIVATE_KEY, CONFIG, exp=OMIT)
    assert run_async(lambda: _verifier().verify_token(token)) is None


def test_rejects_token_missing_nbf():
    token = make_token(PRIVATE_KEY, CONFIG, nbf=OMIT)
    assert run_async(lambda: _verifier().verify_token(token)) is None


def test_rejects_a_token_with_no_subject_oid():
    token = make_token(PRIVATE_KEY, CONFIG, oid=OMIT)
    assert run_async(lambda: _verifier().verify_token(token)) is None


def test_token_with_no_scp_claim_is_valid_but_carries_no_scopes():
    # An oid can identify a user or service principal. A trusted JWT without
    # delegated scopes must still fail the HTTP authorization gate.
    token = make_token(PRIVATE_KEY, CONFIG, scp=OMIT)
    result = run_async(lambda: _verifier().verify_token(token))
    assert result is not None
    assert result.scopes == []


def test_token_missing_required_scope_is_valid_but_reports_its_real_scopes():
    token = make_token(PRIVATE_KEY, CONFIG, scp="SomeOther.Scope")
    result = run_async(lambda: _verifier().verify_token(token))
    assert result is not None
    assert result.scopes == [CONFIG.scope_prefix + "SomeOther.Scope"]
    assert CONFIG.scope_uri not in result.scopes


def test_accepts_token_with_required_scope_among_several():
    token = make_token(PRIVATE_KEY, CONFIG, scp=f"SomeOther.Scope {REQUIRED_SCOPE}")
    result = run_async(lambda: _verifier().verify_token(token))
    assert result is not None
    assert CONFIG.scope_uri in result.scopes


def test_rejects_signature_from_a_different_key():
    other_private_key, _ = generate_rsa_keypair()
    token = make_token(other_private_key, CONFIG)
    assert run_async(lambda: _verifier().verify_token(token)) is None


def test_rejects_alg_confusion_downgrade_to_hs256():
    forged = make_hs256_confusion_token(PUBLIC_KEY, CONFIG)
    assert run_async(lambda: _verifier().verify_token(forged)) is None


def test_rejects_unparseable_token():
    assert run_async(lambda: _verifier().verify_token("not-a-jwt")) is None


def test_azp_allowlist_rejects_a_client_not_on_the_list():
    verifier = _verifier(allowed_client_ids=frozenset({"77777777-7777-7777-7777-777777777777"}))
    token = make_token(PRIVATE_KEY, CONFIG, azp="11111111-aaaa-bbbb-cccc-222222222222")
    assert run_async(lambda: verifier.verify_token(token)) is None


def test_azp_allowlist_accepts_a_listed_client():
    allowed = "11111111-aaaa-bbbb-cccc-222222222222"
    verifier = _verifier(allowed_client_ids=frozenset({allowed}))
    token = make_token(PRIVATE_KEY, CONFIG, azp=allowed)
    result = run_async(lambda: verifier.verify_token(token))
    assert result is not None


def test_azp_allowlist_rejects_missing_azp_when_configured():
    verifier = _verifier(allowed_client_ids=frozenset({"77777777-7777-7777-7777-777777777777"}))
    token = make_token(PRIVATE_KEY, CONFIG, azp=OMIT)
    assert run_async(lambda: verifier.verify_token(token)) is None


def test_empty_allowlist_never_authorizes_a_token():
    token = make_token(PRIVATE_KEY, CONFIG)
    result = run_async(lambda: _verifier(allowed_client_ids=frozenset()).verify_token(token))
    assert result is None


def test_jwks_connection_errors_propagate_instead_of_becoming_invalid_token():
    import jwt as pyjwt

    class BrokenResolver:
        def resolve(self, kid):
            raise pyjwt.PyJWKClientConnectionError("jwks endpoint unreachable")

    verifier = EntraTokenVerifier(CONFIG, key_resolver=BrokenResolver())
    token = make_token(PRIVATE_KEY, CONFIG)

    with pytest.raises(pyjwt.PyJWKClientConnectionError):
        run_async(lambda: verifier.verify_token(token))
