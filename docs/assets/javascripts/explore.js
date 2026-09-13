(function () {
  "use strict";

  const fields = {tag: "tags", service: "services", technology: "technologies"};
  const emptyFilters = () => ({tag: [], service: [], technology: [], q: []});
  const normalize = value => value.normalize("NFKC").toLocaleLowerCase().trim();

  function parseQuery(query, vocabulary) {
    const filters = emptyFilters();
    const invalid = [];
    for (const [key, value] of new URLSearchParams(query)) {
      if (key === "q") {
        if (value.trim() && !filters.q.includes(value.trim())) filters.q.push(value.trim());
      } else if (Object.hasOwn(fields, key) && vocabulary[key].includes(value)) {
        if (!filters[key].includes(value)) filters[key].push(value);
      } else {
        invalid.push(`${key}=${value}`);
      }
    }
    return {filters, invalid};
  }

  function matchesMember(member, filters) {
    return Object.entries(fields).every(([key, field]) =>
      filters[key].every(value => member[field].includes(value))
    ) && filters.q.every(value => normalize(member.search).includes(normalize(value)));
  }

  function queryString(filters) {
    const query = new URLSearchParams();
    for (const key of [...Object.keys(fields), "q"]) {
      for (const value of filters[key]) query.append(key, value);
    }
    return query.size ? `?${query}` : "";
  }

  function mount(root, environment) {
    if (root.dataset.exploreReady) return;
    root.dataset.exploreReady = "true";
    const form = root.querySelector("[data-explore-form]");
    const search = root.querySelector('[name="q"]');
    const controls = Array.from(root.querySelectorAll('input[type="checkbox"]'));
    const count = root.querySelector("[data-explore-count]");
    const summary = root.querySelector("[data-explore-summary]");
    const alert = root.querySelector("[data-explore-alert]");
    const empty = root.querySelector("[data-explore-empty]");
    const vocabulary = Object.fromEntries(Object.keys(fields).map(key => [
      key, controls.filter(control => control.name === key).map(control => control.value),
    ]));
    const topics = Array.from(root.querySelectorAll("[data-explore-topic]")).map(card => ({
      card,
      count: card.querySelector("[data-explore-topic-count]"),
      members: Array.from(card.querySelectorAll("[data-explore-member]")).map(row => ({
        row,
        data: {
          tags: JSON.parse(row.dataset.tags),
          services: JSON.parse(row.dataset.services),
          technologies: JSON.parse(row.dataset.technologies),
          search: row.dataset.search,
        },
      })),
    }));
    let filters = emptyFilters();

    function update() {
      let topicCount = 0;
      let documentCount = 0;
      for (const topic of topics) {
        let matching = 0;
        for (const member of topic.members) {
          member.row.hidden = !matchesMember(member.data, filters);
          if (!member.row.hidden) matching += 1;
        }
        topic.card.hidden = matching === 0;
        topic.count.textContent = matching === topic.members.length
          ? `${matching}개 문서` : `${matching} / ${topic.members.length}개 문서 일치`;
        topicCount += matching > 0 ? 1 : 0;
        documentCount += matching;
      }
      count.textContent = `${topicCount}개 주제 · ${documentCount}개 문서`;
      const selected = controls.filter(control => control.checked).map(control =>
        control.labels[0].textContent.trim());
      selected.push(...filters.q.map(value => `검색: ${value}`));
      summary.textContent = selected.length ? `선택한 조건 (AND): ${selected.join(" · ")}` : "모든 주제 · 선택한 조건 없음";
      empty.hidden = documentCount !== 0;
      const url = environment.location.pathname + queryString(filters) + environment.location.hash;
      environment.history.replaceState(null, "", url);
    }

    function readQuery() {
      const parsed = parseQuery(environment.location.search, vocabulary);
      filters = parsed.filters;
      for (const control of controls) control.checked = filters[control.name].includes(control.value);
      // Repeated q values remain separate AND terms until the reader edits text.
      search.value = filters.q.join(" ");
      alert.hidden = parsed.invalid.length === 0;
      alert.textContent = parsed.invalid.length
        ? `알 수 없는 필터를 제외했습니다: ${parsed.invalid.join(", ")}` : "";
      update();
    }

    form.addEventListener("change", () => {
      for (const key of Object.keys(fields)) {
        filters[key] = controls.filter(control => control.name === key && control.checked).map(control => control.value);
      }
      update();
    });
    form.addEventListener("input", event => {
      if (event.target !== search) return;
      filters.q = search.value.trim() ? [search.value.trim()] : [];
      update();
    });
    form.addEventListener("submit", event => event.preventDefault());
    form.addEventListener("reset", event => {
      event.preventDefault();
      filters = emptyFilters();
      controls.forEach(control => { control.checked = false; });
      search.value = "";
      alert.hidden = true;
      alert.textContent = "";
      update();
    });
    environment.addEventListener("popstate", readQuery);
    readQuery();
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {parseQuery, matchesMember, queryString, mount};
  }
  if (typeof document !== "undefined") {
    const start = () => {
      const root = document.querySelector("[data-explore]");
      if (root) mount(root, window);
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
  }
})();
