const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const script = path.join(__dirname, "../../docs/assets/javascripts/explore.js");
const available = fs.existsSync(script);
const explore = available ? require(script) : {};
const vocabulary = {tag: ["design", "build", "operate", "identity"], service: ["one", "two"], technology: ["python", "kubernetes"]};
const member = {tags: ["design", "build"], services: ["one"], technologies: ["python"], search: "Agent Memory\nFast retrieval"};

test("explore script is present", () => assert.ok(available, "dependency-free explore script is required"));
test("repeated validated parameters are deduplicated, unknowns are reported", {skip: !available}, () => {
  const {filters, invalid} = explore.parseQuery("?tag=design&tag=design&tag=build&tag=old&service=one&technology=python&technology=rust&q=Agent&q=Memory&bad=x", vocabulary);
  assert.deepEqual(filters, {tag: ["design", "build"], service: ["one"], technology: ["python"], q: ["Agent", "Memory"]});
  assert.deepEqual(invalid, ["tag=old", "technology=rust", "bad=x"]);
});
test("all facets and text apply to the same member, never a topic union", {skip: !available}, () => {
  const base = {tag: ["design", "build"], service: ["one"], technology: ["python"], q: ["agent", "RETRIEVAL"]};
  assert.equal(explore.matchesMember(member, base), true);
  for (const [key, value] of [["tag", "operate"], ["service", "two"], ["technology", "kubernetes"], ["q", "absent"]]) {
    assert.equal(explore.matchesMember(member, {...base, [key]: [...base[key], value]}), false);
  }
  assert.equal(explore.matchesMember({...member, tags: ["design-advanced"]}, {...base, tag: ["design"]}), false);
  assert.equal(explore.matchesMember({...member, tags: ["design"]}, base), false);
  assert.equal(explore.matchesMember({...member, tags: ["build"]}, base), false);
});
test("URL roundtrip preserves repeated filters and text, excludes invalid values", {skip: !available}, () => {
  const {filters} = explore.parseQuery("?tag=design&tag=old&tag=build&q=a%26b&q=%EA%B2%80%EC%83%89", vocabulary);
  assert.deepEqual(explore.parseQuery(explore.queryString(filters), vocabulary).filters, filters);
  assert.equal(explore.queryString({tag: [], service: [], technology: [], q: []}), "");
});

function element(extra = {}) {
  return {
    hidden: false, textContent: "", value: "", checked: false, dataset: {},
    listeners: {}, addEventListener(type, callback) { this.listeners[type] = callback; },
    ...extra,
  };
}
function fixture(query = "") {
  const controls = Object.entries(vocabulary).flatMap(([name, values]) =>
    values.map(value => element({name, value, labels: [{textContent: value}]})));
  const rows = [
    element({dataset: {tags: '["design"]', services: '["one"]', technologies: '["python"]', search: "Agent entry"}}),
    element({dataset: {tags: '["design","build"]', services: '["one"]', technologies: '["python"]', search: "Agent Memory"}}),
    element({dataset: {tags: '["build"]', services: '["two"]', technologies: '["kubernetes"]', search: "Other"}}),
  ];
  const cards = [[rows[0], rows[1]], [rows[2]]].map(members => element({
    querySelectorAll: () => members, querySelector: () => element(),
  }));
  const nodes = Object.fromEntries(["form", "count", "summary", "alert", "empty"].map(key => [`[data-explore-${key}]`, element()]));
  const search = element({name: "q"});
  const root = element({
    querySelector: selector => selector === '[name="q"]' ? search : nodes[selector],
    querySelectorAll: selector => selector === 'input[type="checkbox"]' ? controls : cards,
  });
  const urls = [];
  const env = {location: {search: query, pathname: "/project/explore/", hash: ""}, history: {replaceState: (_, __, url) => urls.push(url)}, addEventListener() {}};
  return {root, env, urls, nodes, controls, rows, cards, search, form: nodes["[data-explore-form]"]};
}
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
