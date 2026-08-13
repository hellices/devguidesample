# Task 2 Report: Place each image in its matching product section

## Commit SHA

`fb03268`

## Files changed

- `monitor/azure-sre-agent.md` — added five official SVG placements across new and existing sections; moved local process image to `이번 실증에서 사용한 방식`
- `monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py` — added `test_official_images_are_placed_with_sections_and_sources`

## Red → Green sequence

### Step 1 — Failing test added

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py::test_official_images_are_placed_with_sections_and_sources -v
```

```
FAILED monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py::test_official_images_are_placed_with_sections_and_sources
AssertionError: assert 'incident-response-flow.svg' in '...'
1 failed in 0.04s
```

### Step 2 — Briefing updated, all tests green

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py \
  monitor/sre-agent-event-lab/scripts/tests/test_briefing_assets.py -v
```

```
PASSED test_briefing_uses_natural_korean_terms
PASSED test_briefing_uses_customer_facing_honorific_style
PASSED test_briefing_uses_official_korean_localization_reference
PASSED test_briefing_uses_only_local_images_and_no_storyboards
PASSED test_briefing_distinguishes_product_and_lab_behavior
PASSED test_official_images_are_placed_with_sections_and_sources
PASSED test_official_sre_agent_svgs_are_stored_locally
PASSED test_render_briefing_assets_creates_required_files
PASSED test_svg_diagrams_contain_required_korean_labels
PASSED test_public_assets_do_not_expose_sensitive_identifiers
10 passed in 0.30s
```

## One-line test summary

10/10 passed — `test_official_images_are_placed_with_sections_and_sources` green, all pre-existing tests preserved.

## Concerns

- The task brief specified English link text (e.g., "Automate Incident Response in Azure SRE Agent") for the `> 출처:` blockquotes. These were replaced with Korean equivalents (e.g., `인시던트 대응 자동화`) because the `prose_only` filter in `test_briefing_uses_natural_korean_terms` extracts link display text and would have matched the `\bincident\b` and `\broot cause\b` patterns. The source URLs are unchanged, satisfying the placement test.
- No other concerns.

## Fix Review

- File changed: `monitor/azure-sre-agent.md`
- Exact command: `monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest monitor/sre-agent-event-lab/scripts/tests/test_briefing_docs.py monitor/sre-agent-event-lab/scripts/tests/test_briefing_assets.py`
- Output count: `10 passed`
- Commit SHA: `7c1daf6`
