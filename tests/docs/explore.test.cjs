const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const script = path.join(__dirname, "../../docs/assets/javascripts/explore.js");
const available = fs.existsSync(script);
const explore = available ? require(script) : {};
const {fixture, vocabulary} = require("./explore-fixture.cjs");
const member = {tags: ["design", "build"], services: ["one"], technologies: ["python"], search: "Agent Memory\nFast retrieval"};

test("explore script is present", () => assert.ok(available, "dependency-free explore script is required"));
test("repeated validated parameters are deduplicated, unknowns are reported", {skip: !available}, () => {
  const {filters, invalid} = explore.parseQuery("?tag=design&tag=design&tag=build&tag=old&service=one&technology=python&technology=rust&text=Agent&text=Memory&bad=x", vocabulary);
  assert.deepEqual(filters, {tag: ["design", "build"], service: ["one"], technology: ["python"], text: ["Agent", "Memory"]});
  assert.deepEqual(invalid, ["tag=old", "technology=rust", "bad=x"]);
});
test("all facets and text apply to the same member, never a topic union", {skip: !available}, () => {
  const base = {tag: ["design", "build"], service: ["one"], technology: ["python"], text: ["agent", "RETRIEVAL"]};
  assert.equal(explore.matchesMember(member, base), true);
  for (const [key, value] of [["tag", "operate"], ["service", "two"], ["technology", "kubernetes"], ["text", "absent"]]) {
    assert.equal(explore.matchesMember(member, {...base, [key]: [...base[key], value]}), false);
  }
  assert.equal(explore.matchesMember({...member, tags: ["design-advanced"]}, {...base, tag: ["design"]}), false);
  assert.equal(explore.matchesMember({...member, tags: ["design"]}, base), false);
  assert.equal(explore.matchesMember({...member, tags: ["build"]}, base), false);
});
test("URL roundtrip preserves repeated filters and text, excludes invalid values", {skip: !available}, () => {
  const {filters} = explore.parseQuery("?tag=design&tag=old&tag=build&text=a%26b&text=%EA%B2%80%EC%83%89", vocabulary);
  assert.deepEqual(explore.parseQuery(explore.queryString(filters), vocabulary).filters, filters);
  assert.equal(explore.queryString({tag: [], service: [], technology: [], text: []}), "");
});
test("mount hides nonmatching members, keeps their topic, counts and resets", {skip: !available}, () => {
  const f = fixture("?tag=design&tag=build");
  explore.mount(f.root, f.env);
  assert.deepEqual(f.rows.map(row => row.hidden), [true, false, true]);
  assert.deepEqual(f.cards.map(card => card.hidden), [false, true]);
  assert.equal(f.nodes["[data-explore-count]"].textContent, "1개 주제 · 1개 문서");
  assert.match(f.nodes["[data-explore-summary]"].textContent, /design.*build/);
  f.search.value = "missing";
  f.form.listeners.input({target: f.search});
  assert.equal(f.nodes["[data-explore-empty]"].hidden, false);
  assert.equal(f.nodes["[data-explore-count]"].textContent, "0개 주제 · 0개 문서");
  f.form.listeners.reset({preventDefault() {}});
  assert.deepEqual(f.rows.map(row => row.hidden), [false, false, false]);
  assert.equal(f.search.value, "");
  assert.ok(f.controls.every(control => !control.checked));
  assert.equal(f.urls.at(-1), "/project/explore/");
  assert.equal(f.nodes["[data-explore-count]"].textContent, "2개 주제 · 3개 문서");
});
test("invalid query values alert visibly and are removed from URL", {skip: !available}, () => {
  const f = fixture("?tag=old&service=one");
  explore.mount(f.root, f.env);
  assert.equal(f.nodes["[data-explore-alert]"].hidden, false);
  assert.match(f.nodes["[data-explore-alert]"].textContent, /tag=old/);
  assert.deepEqual(f.rows.map(row => row.hidden), [false, false, true]);
  assert.equal(f.urls.at(-1), "/project/explore/?service=one");
});

test("Material q is external: not a text filter, not invalid, preserved on rewrites", () => {
  const query = "?q=Global&q=Search&text=Agent&tag=design&unknown=x";
  const {filters, invalid} = explore.parseQuery(query, vocabulary);
  assert.deepEqual(filters, {tag: ["design"], service: [], technology: [], text: ["Agent"]});
  assert.deepEqual(invalid, ["unknown=x"]);
  const serialized = new URLSearchParams(explore.queryString(filters, query));
  assert.deepEqual(serialized.getAll("q"), ["Global", "Search"]);
  assert.deepEqual(serialized.getAll("text"), ["Agent"]);
  assert.equal(serialized.has("unknown"), false);
});

test("Explore edit, popstate, and reset preserve current external q without reviving deleted q", () => {
  const f = fixture("?q=Global&text=Agent&text=Memory&tag=design");
  explore.mount(f.root, f.env);
  assert.equal(f.nodes["[data-explore-alert]"].hidden, true);
  assert.equal(f.search.value, "Agent Memory");
  assert.equal(f.nodes["[data-explore-count]"].textContent, "1개 주제 · 1개 문서");
  f.search.value = "entry";
  f.form.listeners.input({target: f.search});
  assert.equal(f.env.location.searchParams.get("q"), "Global");
  assert.deepEqual(f.env.location.searchParams.getAll("text"), ["entry"]);
  assert.match(f.nodes["[data-explore-summary]"].textContent, /검색: entry/);
  f.env.location = new URL("https://example.test/project/explore/?tag=design&text=Agent&text=Memory&q=Next#results");
  f.listeners.popstate();
  assert.equal(f.search.value, "Agent Memory");
  assert.equal(f.nodes["[data-explore-count]"].textContent, "1개 주제 · 1개 문서");
  f.form.listeners.reset({preventDefault() {}});
  assert.equal(f.env.location.search, "?q=Next");
  assert.equal(f.env.location.hash, "#results");
  assert.equal(f.search.value, "");
  f.env.location.searchParams.delete("q");
  f.form.listeners.change();
  assert.equal(f.env.location.search, "");
});
