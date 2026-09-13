import published_layout


def test_published_layout_resolves_only_declared_virtual_assets():
    assert hasattr(published_layout, "resolve_published_file")
    resolve = published_layout.resolve_published_file
    target = published_layout.TOPIC_ROOT / "images/incident-response-flow.svg"
    source = published_layout.OFFICIAL_ASSETS / "incident-response-flow.svg"

    assert not target.exists()
    assert resolve(target) == source
    assert source.is_file()
    assert resolve(published_layout.BRIEFING) == published_layout.BRIEFING
    missing = published_layout.TOPIC_ROOT / "images/not-declared.svg"
    assert resolve(missing) == missing
    assert not resolve(missing).exists()
