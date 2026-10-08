const assert = require("node:assert/strict");
const {existsSync} = require("node:fs");
const path = require("node:path");
const {test} = require("node:test");

const script = path.resolve(__dirname, "../../docs/assets/javascripts/daily-updates.js");

function behavior() {
  assert.ok(existsSync(script), "The daily archive behavior script must exist");
  return require(script);
}

function report(date, text = "Container networking 연결 진단") {
  return {date, title: `Update ${date}`, description: "Daily summary", url: `${date}/`, text};
}

function calendarReport(day) {
  const {date, title, url} = report(day);
  return {date, title, url};
}

function element(tag = "div") {
  return {
    tagName: tag, children: [], attributes: {}, dataset: {}, listeners: {},
    hidden: false, disabled: true, textContent: "", value: "",
    setAttribute(name, value) { this.attributes[name] = value; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(type, listener) {
      (this.listeners[type] ||= []).push(listener);
    },
    dispatch(type) {
      for (const listener of this.listeners[type] || []) listener({preventDefault() {}});
    },
  };
}

function fixture(kind) {
  const names = kind === "calendar"
    ? {prev: "button", next: "button", month: "select", days: "tbody", grid: "table", status: "p"}
    : {form: "form", query: "input", reset: "button", "search-status": "p", results: "ol", more: "button"};
  const nodes = Object.fromEntries(Object.entries({...names, error: "p"}).map(
    ([name, tag]) => [name, element(tag)]
  ));
  nodes.error.hidden = true;
  const ownerDocument = {createElement: element};
  const root = element();
  root.ownerDocument = ownerDocument;
  root.dataset = {
    dailySource: kind === "calendar" ? "../../assets/daily-updates-calendar.json" : "../../assets/daily-updates.json",
    dailyBase: "../",
    ...(kind === "calendar"
      ? {dailyCalendar: "2024-02", dailySelected: "2024-02-29"}
      : {dailySearch: ""}),
  };
  root.querySelector = selector => selector === 'button[type="reset"]'
    ? nodes.reset : nodes[selector.slice(12, -1)];
  const environment = {
    location: new URL("https://example.test/project/azure-daily-update/2024-02-29/?q=keep"),
  };
  return {root, nodes, environment};
}

function descendants(root) {
  return root.children.flatMap(child => [child, ...descendants(child)]);
}

test("calendar weeks use calendar dates, including leap years and year boundaries", () => {
  const {calendarWeeks} = behavior();
  const leap = calendarWeeks("2024-02");
  assert.deepEqual(leap[0], [null, null, null, null, "2024-02-01", "2024-02-02", "2024-02-03"]);
  assert.equal(leap.flat().filter(Boolean).length, 29);
  assert.equal(calendarWeeks("2026-02").length, 4);
  assert.equal(calendarWeeks("2025-12").flat().filter(Boolean).at(-1), "2025-12-31");
  assert.equal(calendarWeeks("2026-01").flat().filter(Boolean)[0], "2026-01-01");
  assert.throws(() => calendarWeeks("2026-13"), /Invalid/);
});

test("archive parsing validates dates, duplicate records, text and local URLs", () => {
  const {parseArchive} = behavior();
  assert.deepEqual(parseArchive({reports: []}), []);
  assert.deepEqual(
    parseArchive({reports: [report("2025-12-31"), report("2026-10-07")]}).map(item => item.date),
    ["2026-10-07", "2025-12-31"]
  );
  for (const reports of [
    [report("2026-02-29")],
    [report("2024-02-29"), report("2024-02-29")],
    [{...report("2024-02-29"), url: "https://example.test/unrelated/"}],
    [{...report("2024-02-29"), text: null}],
  ]) assert.throws(() => parseArchive({reports}), /Invalid/);
  assert.throws(() => parseArchive({}), /Invalid/);
});

test("calendar parsing accepts metadata without weakening full-text validation", () => {
  const {parseCalendar, parseArchive} = behavior();
  const records = [calendarReport("2024-02-29")];
  assert.deepEqual(parseCalendar({reports: records}), records);
  assert.throws(() => parseArchive({reports: records}), /Invalid/);
  for (const reports of [
    [calendarReport("2026-02-29")],
    [records[0], records[0]],
    [{...records[0], title: ""}],
    [{...records[0], url: "https://example.test/unrelated/"}],
  ]) assert.throws(() => parseCalendar({reports}), /Invalid/);
});

test("archive search ANDs terms over each report's date, title, summary and body", () => {
  const {createSearchIndex, searchReports} = behavior();
  const index = createSearchIndex([
    report("2026-10-07", "Storage release"),
    report("2025-12-31", "Container networking 연결 진단"),
  ]);
  assert.deepEqual(searchReports(index, "  CONTAINER   진단 ").map(item => item.date), ["2025-12-31"]);
  assert.deepEqual(searchReports(index, "2026-10 summary").map(item => item.date), ["2026-10-07"]);
  assert.deepEqual(searchReports(index, "Storage Container"), []);
  assert.deepEqual(searchReports(index, " \t "), []);
});

test("search builds its normalized body index once instead of on every input", () => {
  const {mountSearch} = behavior();
  const {root, nodes, environment} = fixture("search");
  let bodyReads = 0;
  const item = {
    ...report("2024-02-29"),
    get text() { bodyReads++; return "Ｃｏｎｔａｉｎｅｒ 연결 진단"; },
  };
  mountSearch(root, [item], environment);
  for (const query of ["CONTAINER", "연결", "Container 진단"]) {
    nodes.query.value = query;
    nodes.query.dispatch("input");
    assert.equal(nodes.results.children.length, 1);
  }
  assert.equal(bodyReads, 1);
});

test("calendar marks published and current dates and moves between available months", () => {
  const {mountCalendar} = behavior();
  const {root, nodes, environment} = fixture("calendar");
  const reports = ["2026-10-07", "2024-02-29", "2024-02-01", "2023-12-31"].map(day => report(day));
  mountCalendar(root, reports, environment);

  const links = descendants(nodes.days).filter(node => node.tagName === "a");
  assert.deepEqual(links.map(link => link.dataset.dailyDate), ["2024-02-01", "2024-02-29"]);
  assert.equal(links[0].href, "https://example.test/project/azure-daily-update/2024-02-01/");
  assert.equal(links[1].attributes["aria-current"], "page");
  assert.equal(links[0].attributes["aria-current"], undefined);
  assert.equal(descendants(nodes.days).filter(node => node.tagName === "span").length, 27);
  assert.deepEqual(nodes.month.children.map(option => option.value), ["2026-10", "2024-02", "2023-12"]);

  nodes.prev.dispatch("click");
  assert.equal(root.dataset.dailyCalendar, "2023-12");
  assert.equal(nodes.prev.disabled, true);
  nodes.next.dispatch("click");
  assert.equal(root.dataset.dailyCalendar, "2024-02");
  nodes.next.dispatch("click");
  assert.equal(root.dataset.dailyCalendar, "2026-10");
  assert.equal(nodes.next.disabled, true);
  nodes.month.value = "2023-12";
  nodes.month.dispatch("change");
  assert.match(nodes.status.textContent, /2023년 12월/);
  assert.equal(environment.location.search, "?q=keep");
});

test("search results are bounded, expandable, escaped and reset without touching global search", () => {
  const {mountSearch} = behavior();
  const {root, nodes, environment} = fixture("search");
  const reports = Array.from({length: 25}, (_, index) => report(`2026-10-${String(25 - index).padStart(2, "0")}`));
  reports[0].title = '<img src=x onerror="alert(1)">';
  mountSearch(root, reports, environment);
  assert.equal(nodes.results.hidden, true);
  nodes.query.value = "Container";
  nodes.query.dispatch("input");
  assert.equal(nodes.results.children.length, 10);
  assert.match(nodes["search-status"].textContent, /25개 결과.*10개 표시/);
  assert.equal(nodes.more.hidden, false);
  const links = descendants(nodes.results).filter(node => node.tagName === "a");
  assert.equal(links[0].textContent, reports[0].title);
  assert.equal(descendants(nodes.results).some(node => node.tagName === "img"), false);
  nodes.more.dispatch("click");
  assert.equal(nodes.results.children.length, 20);
  nodes.more.dispatch("click");
  assert.equal(nodes.results.children.length, 25);
  assert.equal(nodes.more.hidden, true);
  nodes.query.value = "does-not-exist";
  nodes.query.dispatch("input");
  assert.match(nodes["search-status"].textContent, /일치하는 업데이트가 없습니다/);
  nodes.form.dispatch("reset");
  assert.equal(nodes.query.value, "");
  assert.equal(nodes.results.hidden, true);
  assert.equal(environment.location.search, "?q=keep");
});

test("calendars share metadata while only search loads the full archive", async () => {
  const {mountDailyUpdates} = behavior();
  const calendar = fixture("calendar");
  const secondCalendar = fixture("calendar");
  const search = fixture("search");
  const documentRef = {
    querySelectorAll: selector => selector === "[data-daily-calendar]" ? [calendar.root, secondCalendar.root] : [search.root],
  };
  const requested = [];
  const environment = {
    ...calendar.environment,
    fetch: async url => {
      requested.push(url);
      const record = url.endsWith("daily-updates-calendar.json") ? calendarReport("2024-02-29") : report("2024-02-29");
      return {ok: true, json: async () => ({reports: [record]})};
    },
    console: {error: (...args) => assert.fail(args.join(" "))},
  };
  await mountDailyUpdates(documentRef, environment);
  await mountDailyUpdates(documentRef, environment);
  assert.deepEqual(requested, [
    "https://example.test/project/assets/daily-updates-calendar.json",
    "https://example.test/project/assets/daily-updates.json",
  ]);
  assert.equal(calendar.nodes.month.listeners.change.length, 1);
  assert.equal(secondCalendar.nodes.month.listeners.change.length, 1);
  assert.equal(search.nodes.query.disabled, false);
});

test("dated pages never request the full-text search asset", async () => {
  const {mountDailyUpdates} = behavior();
  const {root, nodes, environment} = fixture("calendar");
  const requested = [];
  await mountDailyUpdates({
    querySelectorAll: selector => selector === "[data-daily-calendar]" ? [root] : [],
  }, {
    ...environment,
    fetch: async url => {
      requested.push(url);
      return {ok: true, json: async () => ({reports: [calendarReport("2024-02-29")]})};
    },
    console: {error: (...args) => assert.fail(args.join(" "))},
  });
  assert.deepEqual(requested, ["https://example.test/project/assets/daily-updates-calendar.json"]);
  assert.equal(nodes.month.disabled, false);
});

test("a search payload failure does not disable the calendar", async () => {
  const {mountDailyUpdates} = behavior();
  const calendar = fixture("calendar");
  const search = fixture("search");
  const errors = [];
  await mountDailyUpdates({
    querySelectorAll: selector => selector === "[data-daily-calendar]" ? [calendar.root] : [search.root],
  }, {
    ...calendar.environment,
    fetch: async url => url.endsWith("daily-updates-calendar.json")
      ? {ok: true, json: async () => ({reports: [calendarReport("2024-02-29")]})}
      : {ok: false, status: 503},
    console: {error: (...args) => errors.push(args)},
  });
  assert.equal(calendar.nodes.month.disabled, false);
  assert.equal(calendar.nodes.error.hidden, true);
  assert.equal(search.nodes.error.hidden, false);
  assert.equal(search.nodes.query.disabled, true);
  assert.equal(errors.length, 1);
});

test("load failures are visible and keep the server-rendered date links usable", async () => {
  const {mountDailyUpdates} = behavior();
  for (const response of [
    {ok: false, status: 503},
    {ok: true, json: async () => ({reports: [report("2026-02-29")]})},
  ]) {
    const {root, nodes, environment} = fixture("calendar");
    const originalLink = element("a");
    nodes.days.append(originalLink);
    const errors = [];
    const documentRef = {querySelectorAll: selector => selector === "[data-daily-calendar]" ? [root] : []};
    await mountDailyUpdates(documentRef, {
      ...environment, fetch: async () => response, console: {error: (...args) => errors.push(args)},
    });
    assert.equal(nodes.error.hidden, false);
    assert.match(nodes.error.textContent, /불러오지 못했습니다/);
    assert.equal(nodes.month.disabled, true);
    assert.equal(nodes.days.children[0], originalLink);
    assert.equal(errors.length, 1);
  }
});
