# Public GitHub Pages Implementation Plan

> 이 파일은 구현 이력이다. 현재 문서 작성 계약은 `AGENTS.md`와
> `docs/contributing/index.md`를 따른다. 아래 초기 작업의 파일 목록보다
> 마지막 정리 작업에서 확정한 최소 테스트 구성이 우선한다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the repository as a searchable public Material for MkDocs site whose navigation and indexes are generated from folders and front matter, with Microsoft Learn MCP-based technical verification guidance.

**Architecture:** Markdown page bundles under `docs/` are the only public content source. A shared Python content model validates metadata and official sources, generates collection/service indexes at build time, and feeds both pull-request checks and Pages deployment. A workspace MCP connection supplies Microsoft Learn tools; a repository skill defines the semantic review procedure while deterministic CI validates its recorded evidence.

**Tech Stack:** Python 3.13, pytest 9.1.1, PyYAML 6.0.3, Material for MkDocs 9.7.7, mkdocs-awesome-nav 3.3.0, mkdocs-gen-files 0.6.1, GitHub Actions, GitHub Pages

## Global Constraints

- The site is public and must not expose customer identifiers, credentials, internal hosts, subscriptions, tenants, or unapproved screenshots.
- Public technical pages live only under `docs/cases`, `docs/guides`, `docs/labs`, or `docs/research`.
- Adding a valid page bundle must not require editing `mkdocs.yml`, README, or a per-page navigation list.
- Full-text search must index Korean, English, headings, body text, and rendered tags.
- Every public technical page records at least one `https://learn.microsoft.com/` source and a source-check date.
- Microsoft Learn MCP tool names and parameter schemas are discovered at connection time, not hardcoded in application code.
- Existing URL compatibility is not required.
- Generated `site/`, generated index Markdown, and search index files are never committed.
- External official-site search results are optional and are not part of this implementation.
- This session executes inline because its policy does not authorize subagent dispatch.

---

### Task 1: Define and test the content contract

**Files:**
- Create: `docs-taxonomy.yml`
- Create: `scripts/docs/content.py`
- Create: `tests/docs/test_content.py`
- Create: `tests/docs/fixtures/valid-guide.md`
- Create: `tests/docs/fixtures/invalid-guide.md`
- Create: `requirements-docs.txt`

**Interfaces:**
- Consumes: public document paths and YAML front matter
- Produces: `load_taxonomy(path)`, `load_document(path)`, `iter_public_documents(docs_dir, taxonomy)`, and `validate_document(document, taxonomy, today)`

- [ ] **Step 1: Write failing parser and schema tests**

  Cover front matter parsing, folder/type agreement, kebab-case slugs, required common fields, type-specific fields, controlled taxonomy values, `verification_status`, source dates, and the mandatory Microsoft Learn host.

- [ ] **Step 2: Run the tests and confirm RED**

  Run: `python -m pytest tests/docs/test_content.py -q`

  Expected: collection fails because `scripts.docs.content` does not exist.

- [ ] **Step 3: Implement the shared model and declarative taxonomy**

  `docs-taxonomy.yml` is the only source for collection paths, document types, allowed statuses, service labels, technologies, tags, and official source hosts. `content.py` must derive path and enum validation from that data instead of duplicating lists in Python.

- [ ] **Step 4: Run the tests and confirm GREEN**

  Run: `python -m pytest tests/docs/test_content.py -q`

  Expected: all content-contract tests pass.

### Task 2: Build deterministic documentation checks

**Files:**
- Create: `scripts/docs/validate_metadata.py`
- Create: `scripts/docs/validate_sources.py`
- Create: `scripts/docs/validate_links.py`
- Create: `tests/docs/test_validators.py`

**Interfaces:**
- Consumes: Task 1 content model and repository root
- Produces: CLIs returning exit code 0 with a concise count, or exit code 1 with `path: message` diagnostics

- [ ] **Step 1: Write failing CLI tests**

  Test valid repositories, missing front matter, wrong collection paths, missing Learn sources, non-HTTPS sources, future check dates, missing images, broken relative Markdown links, and images without alt text.

- [ ] **Step 2: Run the tests and confirm RED**

  Run: `python -m pytest tests/docs/test_validators.py -q`

  Expected: failures report missing validator modules.

- [ ] **Step 3: Implement minimal validator CLIs**

  All validation functions reuse `content.py`. Link checks ignore URL schemes and anchors, resolve local paths relative to each document, and report every failure in a single run.

- [ ] **Step 4: Run the tests and confirm GREEN**

  Run: `python -m pytest tests/docs/test_validators.py -q`

  Expected: all validator tests pass.

### Task 3: Generate a zero-maintenance site navigation and indexes

**Files:**
- Create: `mkdocs.yml`
- Create: `docs/.nav.yml`
- Create: `docs/index.md`
- Create: `docs/tags.md`
- Create: `scripts/docs/generate_indexes.py`
- Create: `scripts/docs/hooks.py`
- Create: `docs/assets/stylesheets/extra.css`
- Create: `tests/docs/test_site_generation.py`

**Interfaces:**
- Consumes: Task 1 documents and taxonomy
- Produces: virtual collection indexes, `services/index.md`, one virtual page per service, status/source callouts, Material tags, and browser-side search JSON

- [ ] **Step 1: Write failing generation tests**

  Create a temporary docs tree, call the pure index-rendering functions, and assert that every valid page appears once in its collection and each declared service page. Assert that `mkdocs.yml` contains no top-level `nav:` and that `.nav.yml` ends with a catch-all `"*"` entry.

- [ ] **Step 2: Run the tests and confirm RED**

  Run: `python -m pytest tests/docs/test_site_generation.py -q`

  Expected: generation module and MkDocs files are missing.

- [ ] **Step 3: Implement generation and MkDocs configuration**

  Configure `search` with `ko` and `en`, Material `tags`, `gen-files` before `awesome-nav`, `use_directory_urls: true`, repository links, strict Markdown extensions, and the status/source hook. The tags page contains `<!-- material/tags -->`. The root `.nav.yml` explicitly orders only the stable top-level sections and includes `"*"` for unmatched future sections.

- [ ] **Step 4: Run unit tests and a strict build**

  Run: `python -m pytest tests/docs/test_site_generation.py -q`

  Expected: tests pass.

  Run: `mkdocs build --strict`

  Expected: build completes and writes `site/search/search_index.json`.

### Task 4: Add the Microsoft Learn verification harness

**Files:**
- Create: `.vscode/mcp.json`
- Create: `.github/skills/verify-with-microsoft-learn/SKILL.md`
- Create: `tests/docs/test_microsoft_learn_skill.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Microsoft Learn remote Streamable HTTP endpoint and changed technical pages
- Produces: a discoverable repository skill that requires claim extraction, search, full-page fetch, comparison, and front matter evidence updates

- [ ] **Step 1: Write failing contract tests**

  Assert that the MCP JSON registers `https://learn.microsoft.com/api/mcp` as an HTTP server; the skill front matter name matches its folder; the description starts with `Use when`; and its body requires dynamic tool discovery, search, full-article fetch, mismatch handling, upstream checks, `official_sources`, `sources_checked_at`, and `verification_status`.

- [ ] **Step 2: Run the tests and confirm RED**

  Run: `python -m pytest tests/docs/test_microsoft_learn_skill.py -q`

  Expected: tests fail because the MCP and skill files are absent.

- [ ] **Step 3: Initialize and write the skill**

  Initialize `verify-with-microsoft-learn` with the system skill initializer under `.github/skills`, replace generated prose with a concise imperative workflow, and keep all procedural content in `SKILL.md`. Change `.gitignore` from ignoring the whole skills tree to ignoring every child except this named skill.

- [ ] **Step 4: Validate the skill and MCP configuration**

  Run: `python -m pytest tests/docs/test_microsoft_learn_skill.py -q`

  Expected: the repository-owned skill and MCP configuration harness tests pass.

### Task 5: Publish author and agent guidance

**Files:**
- Replace: `README.md`
- Create: `CONTRIBUTING.md`
- Create: `AGENTS.md`
- Create: `docs/contributing/index.md`
- Create: `docs/contributing/case-template.md`
- Create: `docs/contributing/guide-template.md`
- Create: `docs/contributing/lab-template.md`
- Create: `docs/contributing/research-template.md`
- Create: `tests/docs/test_authoring_guidance.py`

**Interfaces:**
- Consumes: content contract, validator commands, skill name, public Pages URL
- Produces: one detailed contributor source of truth, short GitHub/README entry points, and executable agent rules

- [ ] **Step 1: Write failing guidance tests**

  Assert that README links the Pages URL and contribution entry point; AGENTS requires the Microsoft Learn skill and the three validation commands; every template uses the correct collection/type fields; and the contribution page explains folder-only automatic inclusion and case/guide separation.

- [ ] **Step 2: Run the tests and confirm RED**

  Run: `python -m pytest tests/docs/test_authoring_guidance.py -q`

  Expected: required files and statements are missing.

- [ ] **Step 3: Write guidance and templates**

  Keep README and root CONTRIBUTING concise. Put explanations and examples in the Pages contribution document. Put only mandatory decisions and commands in AGENTS so future rule changes have one descriptive source.

- [ ] **Step 4: Run the tests and confirm GREEN**

  Run: `python -m pytest tests/docs/test_authoring_guidance.py -q`

  Expected: all authoring guidance tests pass.

### Task 6: Migrate curated content and separate samples

**Files:**
- Create: `scripts/docs/migrate_content.py`
- Create: `scripts/docs/migration_manifest.yml`
- Create: `tests/docs/test_migration.py`
- Move: public Markdown into `docs/{cases,guides,labs,research}/<service>/<topic>/index.md`
- Move: executable projects and manifests into `samples/<service>/<topic>/`
- Move: page images into each page bundle's `images/`

**Interfaces:**
- Consumes: explicit old-path-to-document metadata manifest and the Task 1 taxonomy
- Produces: an idempotent migrated tree, rewritten site links, and GitHub source links for non-page artifacts

- [ ] **Step 1: Write failing migration tests**

  In a temporary repository, verify that one guide, one case, one lab, and one research page move to page bundles; local images copy into `images/`; Markdown links become new site-relative links; code links become repository `samples/` links; evidence Markdown remains under samples; and a second run makes no changes.

- [ ] **Step 2: Run the tests and confirm RED**

  Run: `python -m pytest tests/docs/test_migration.py -q`

  Expected: migration module and manifest do not exist.

- [ ] **Step 3: Implement and run the migration**

  Classify incident timelines and observed failures as cases, reusable current procedures as guides, deploy-and-clean-up walkthroughs as labs, and comparisons or benchmarks as research. Seed migrated technical pages with their service's Microsoft Learn source and `verification_status: needs-review`; do not claim semantic verification that was not performed.

  Run: `python scripts/docs/migrate_content.py --apply`

  Expected: every manifest entry reports `migrated` or `already migrated`, and legacy executable trees move under `samples/`.

- [ ] **Step 4: Run all document checks**

  Run: `python scripts/docs/validate_metadata.py`

  Expected: every published technical document satisfies its folder and metadata contract.

  Run: `python scripts/docs/validate_sources.py`

  Expected: every published technical document has a dated Microsoft Learn source; migrated unreviewed pages remain visibly marked `needs-review`.

  Run: `python scripts/docs/validate_links.py`

  Expected: no broken local page or image link and no missing image alt text.

### Task 7: Add CI and Pages deployment

**Files:**
- Create: `.github/workflows/docs-ci.yml`
- Create: `.github/workflows/pages.yml`
- Create: `.github/pull_request_template.md`
- Create: `tests/docs/test_workflows.py`

**Interfaces:**
- Consumes: pinned dependencies, validator CLIs, MkDocs config
- Produces: read-only PR validation and artifact-based deployment to the `github-pages` environment

- [ ] **Step 1: Write failing workflow tests**

  Parse workflow YAML with the GitHub `on` key preserved as a string and assert Python 3.13, least-privilege permissions, validation commands, strict build, Pages configure/upload/deploy actions, `main` trigger, concurrency, and no `gh-pages` branch write.

- [ ] **Step 2: Run the tests and confirm RED**

  Run: `python -m pytest tests/docs/test_workflows.py -q`

  Expected: workflow files are missing.

- [ ] **Step 3: Implement workflows and PR checklist**

  Pin document dependencies in `requirements-docs.txt`; use reviewed immutable action major versions; grant PR checks `contents: read`; and grant deployment only `contents: read`, `pages: write`, and `id-token: write`.

- [ ] **Step 4: Run repository-wide verification**

  Run: `python -m pytest tests/docs -q`

  Expected: all documentation tests pass.

  Run: `python scripts/docs/validate_metadata.py && python scripts/docs/validate_sources.py && python scripts/docs/validate_links.py && mkdocs build --strict`

  Expected: every command exits 0 and `site/search/search_index.json` contains Korean body text, English product terms, and tag strings.

  Run: `git diff --check`

  Expected: no whitespace errors.

### Task 8: Normalize service slugs and separate project records

**Files:**
- Modify: `tests/docs/test_content.py`
- Modify: `tests/docs/test_authoring_guidance.py`
- Modify: `tests/docs/test_migration.py`
- Modify: `docs-taxonomy.yml`
- Modify: `scripts/docs/migration_manifest.yml`
- Modify: `docs/contributing/index.md`
- Modify: `AGENTS.md`
- Modify: `mkdocs.yml`
- Move: `docs/superpowers/specs/2026-09-12-public-github-pages-design.md` to `project/specs/2026-09-12-public-github-pages-design.md`
- Move: `docs/superpowers/plans/2026-09-12-public-github-pages.md` to `project/plans/2026-09-12-public-github-pages.md`
- Move: affected `docs/<collection>/<service>/` and `samples/<service>/` directories

**Interfaces:**
- Consumes: service identifiers from `docs-taxonomy.yml` and explicit migration entries
- Produces: provider-consistent public URLs, matching front matter and sample links, and project records outside the Pages source tree

**Canonical service mappings:**
- `aks` → `azure-kubernetes-service`
- `application-gateway` → `azure-application-gateway`
- `azure-ai-foundry` → `microsoft-foundry`
- `azure-mysql` → `azure-database-for-mysql`
- `cosmos-db` → `azure-cosmos-db`
- `development` → `application-development`
- `hdinsight` → `azure-hdinsight`
- sample-only `app-service` → `azure-app-service`

- [x] **Step 1: Write failing naming and placement tests**

  Assert that every taxonomy label beginning with `Azure ` has an `azure-` service slug, every label beginning with `Microsoft ` has a `microsoft-` slug, public documents use only those taxonomy slugs, migration destinations use the canonical mappings, and no `docs/superpowers/` project record remains.

- [x] **Step 2: Run the focused tests and confirm RED**

  Run: `python -m pytest tests/docs/test_content.py tests/docs/test_authoring_guidance.py tests/docs/test_migration.py -q`

  Expected: failures identify the legacy service slugs and `docs/superpowers/` placement.

- [x] **Step 3: Verify official product names**

  Use `.github/skills/verify-with-microsoft-learn/SKILL.md`: discover current MCP tools, search Microsoft Learn, fetch the selected product pages in full, and confirm each public product label before changing the taxonomy.

- [x] **Step 4: Apply canonical directory and metadata moves**

  Move each affected service directory, update every document's `services` front matter, rewrite cross-document and GitHub sample links, and update the migration manifest so a dry run reports `0 planned changes`.

- [x] **Step 5: Move project records and remove the Pages exclusion**

  Keep the design and implementation plan under `project/`, delete the now-empty `docs/superpowers/` tree, remove the obsolete `exclude_docs: superpowers/` configuration, and document the slug policy in `docs/contributing/index.md` and `AGENTS.md`.

- [x] **Step 6: Run complete verification**

  Run: `python -m pytest tests/docs -q`

  Run all commands required by `AGENTS.md`, then run `python scripts/docs/migrate_content.py`, `python -m pip check`, and `git diff --check`.

  Expected: every command exits 0, the migration reports `0 planned changes`, and generated search entries contain only canonical service URLs.

- [ ] **Step 7: Commit and update PR #59**

  Commit the reviewed changes without amending existing commits, push `docs/public-github-pages`, update the PR description, and wait for Documentation CI and Oryx checks to pass.

### Task 9: Close review gaps in public validation and sample CI

**Files:**
- Modify: `scripts/docs/validate_public_safety.py`
- Modify: `scripts/docs/validate_metadata.py`
- Modify: `.github/workflows/docs-ci.yml`
- Modify: `samples/azure-monitor/source-material/sre-agent-event-lab/app/requirements-dev.txt`
- Modify: `samples/azure-monitor/source-material/sre-agent-event-lab/scripts/tests/test_dynamic_threshold_brief.py`
- Move: Dynamic Threshold chart into its page bundle
- Modify: Azure AI Search benchmark defaults and ConfigMap placeholders
- Add or modify: regression tests under `tests/docs/`

- [ ] **Step 1: Prove each reported gap with a failing regression test**

  Cover SVG/XML scanning, invalid UTF-8 failure, stray collection Markdown, explicit Azure resource configuration, bundle-local images, sample dependency compatibility, and sample-suite execution in CI.

- [ ] **Step 2: Apply the minimal validator, sample, bundle, and workflow fixes**

  Keep the published document schema unchanged and avoid adding manually maintained navigation entries.

- [ ] **Step 3: Run focused tests and all repository-required validation**

  Run `python -m pytest tests/docs -q`, the Dynamic Threshold tests, every command required by `AGENTS.md`, dependency check, and whitespace check.

- [ ] **Step 4: Update PR #59 and resolve the review threads**

  Push a new commit, wait for required GitHub checks, reply inline with the verified change for each comment, and resolve each thread only after CI succeeds.

### Task 10: Remove one-time tooling and keep only contract tests

- [x] Delete the completed content migration script, manifest, and migration tests.
- [x] Delete tests that pin README wording, workflow step layout, and relocated sample paths.
- [x] Keep focused coverage for the content contract, validators, generated site and search,
  public-safety failures, and Microsoft Learn MCP registration.
- [x] Run the remaining tests and every validation command required by `AGENTS.md`.
