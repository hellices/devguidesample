const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const explore = require("../../docs/assets/javascripts/explore.js");
const {fixture} = require("./explore-fixture.cjs");

// Execute the installed theme's real deep-link/focus/cleanup block, not a copy
// of its q behavior. A changed upstream block fails explicitly for re-review.
const assets = path.join(__dirname, "../../site/assets/javascripts");
const mapPath = process.env.MATERIAL_SOURCE_MAP || path.join(assets,
  fs.readdirSync(assets).find(name => /^bundle.*\.js\.map$/.test(name)));
const map = JSON.parse(fs.readFileSync(mapPath, "utf8"));
const sourceIndex = map.sources.findIndex(source => source.endsWith("/components/search/query/index.ts"));
assert.ok(sourceIndex >= 0, "Material search query source is available");
const source = map.sourcesContent[sourceIndex];
const block = source.split("/* Support search deep linking */")[1]?.split("/* Intercept focus and input events */")[0];
assert.ok(block?.includes('url.searchParams.delete("q")'), "Material cleanup behavior must be inspected if changed");
const materialBootstrap = block.replace('searchParams.get("q")!', 'searchParams.get("q")');
const catalog = process.env.EXPLORE_FIXTURE ? JSON.parse(fs.readFileSync(process.env.EXPLORE_FIXTURE, "utf8")) : undefined;
const expected = catalog?.expectedCount || "1개 주제 · 1개 문서";

test("Material search sharing retains anchor behavior without an executable initializer", () => {
  if (!process.env.MATERIAL_SOURCE_MAP) {
    const html = fs.readFileSync(path.join(__dirname, "../../site/index.html"), "utf8");
    const anchorTag = html.match(/<a\b[^>]*data-md-component="search-share"[^>]*>/)?.[0];
    assert.ok(anchorTag, "search sharing remains enabled as an anchor");
    assert.equal(anchorTag.match(/\bhref="([^"]*)"/)?.[1], "#");
    assert.match(anchorTag, /data-clipboard/);
  }

  const index = map.sources.findIndex(name => name.endsWith("/components/search/share/index.ts"));
  assert.ok(index >= 0);
  const shareSource = map.sourcesContent[index];
  const update = shareSource.split("push$.subscribe(({ url }) => {")[1]?.split("\n  })")[0];
  assert.ok(update?.includes("el.href"), "review the installed share handler if its contract changes");
  const attributes = {};
  let href = "https://example.test/project/#";
  const el = {
    get href() { return href; },
    set href(value) { href = new URL(value, href).href; },
    setAttribute(name, value) { attributes[name] = value; },
  };
  const url = new URL("https://example.test/project/?q=Guide");
  vm.runInNewContext(update, {el, url});
  assert.equal(el.href, url.href);
  assert.equal(attributes["data-clipboard-text"], "https://example.test/project/#");
  const prevent = shareSource.match(/\.subscribe\((ev => ev\.preventDefault\(\))\)/)?.[1];
  assert.ok(prevent, "search sharing must prevent fragment navigation");
  let prevented = false;
  vm.runInNewContext(`(${prevent})`)({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
});

function material(f) {
  let onClose = () => {};
  const state = {open: false, focusCount: 0, value: ""};
  vm.runInNewContext(materialBootstrap, {
    el: {set value(value) { state.value = value; }, focus() { state.focusCount += 1; }},
    getLocation: () => new URL(f.env.location.href),
    setToggle: (name, active) => { assert.equal(name, "search"); state.open = active; },
    watchToggle: name => {
      assert.equal(name, "search");
      return {pipe: predicate => ({subscribe: callback => {
        onClose = () => { if (predicate(false)) callback(); };
      }})};
    },
    first: predicate => predicate,
    history: f.env.history,
  });
  return {state, close() { state.open = false; onClose(); }};
}

test("Material q cleanup positive control opens/focuses search and removes every q", () => {
  const f = fixture("?q=Global&q=Second&text=Agent", catalog);
  const search = material(f);
  assert.equal(search.state.open, true);
  assert.equal(search.state.focusCount, 1);
  assert.equal(search.state.value, "Global");
  search.close();
  assert.equal(f.env.location.searchParams.has("q"), false);
  assert.deepEqual(f.env.location.searchParams.getAll("text"), ["Agent"]);
});

for (const materialFirst of [true, false]) {
  test(`direct text deep link never opens Material search; reload reproduces count (Material first: ${materialFirst})`, () => {
    const f = fixture("?tag=design&text=Agent&text=Memory", catalog);
    let search;
    if (materialFirst) search = material(f);
    explore.mount(f.root, f.env);
    if (!materialFirst) search = material(f);
    assert.equal(search.state.open, false);
    assert.equal(search.state.focusCount, 0);
    assert.equal(f.nodes["[data-explore-alert]"].hidden, true);
    assert.equal(f.nodes["[data-explore-count]"].textContent, expected);
    assert.deepEqual(f.env.location.searchParams.getAll("text"), ["Agent", "Memory"]);
    search.close();
    const reload = fixture(f.env.location.search, catalog);
    const reloadedSearch = material(reload);
    explore.mount(reload.root, reload.env);
    assert.equal(reloadedSearch.state.focusCount, 0);
    assert.equal(reload.nodes["[data-explore-count]"].textContent, expected);
    assert.deepEqual(reload.rows.map(row => row.hidden), f.rows.map(row => row.hidden));
  });
}

test("Material dismissal deletes q but preserves Explore text, result count, and reload", () => {
  const f = fixture("?tag=design&text=Agent&text=Memory&q=Global&unknown=bad", catalog);
  const search = material(f);
  explore.mount(f.root, f.env);
  assert.equal(search.state.open, true);
  assert.equal(f.env.location.searchParams.get("q"), "Global");
  assert.equal(f.nodes["[data-explore-count]"].textContent, expected);
  assert.match(f.nodes["[data-explore-alert]"].textContent, /unknown=bad/);
  assert.doesNotMatch(f.nodes["[data-explore-alert]"].textContent, /q=Global/);
  f.form.listeners.change();
  assert.equal(f.env.location.searchParams.get("q"), "Global");
  search.close();
  assert.equal(f.env.location.searchParams.has("q"), false);
  assert.deepEqual(f.env.location.searchParams.getAll("text"), ["Agent", "Memory"]);
  assert.equal(f.nodes["[data-explore-count]"].textContent, expected);
  f.form.listeners.change();
  assert.equal(f.env.location.searchParams.has("q"), false);
  const reload = fixture(f.env.location.search, catalog);
  material(reload);
  explore.mount(reload.root, reload.env);
  assert.equal(reload.nodes["[data-explore-count]"].textContent, expected);
  assert.deepEqual(reload.rows.map(row => row.hidden), f.rows.map(row => row.hidden));
});
