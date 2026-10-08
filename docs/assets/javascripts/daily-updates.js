(function () {
  "use strict";

  function validDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false;
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
  }

  function parseCalendar(data) {
    if (!data || !Array.isArray(data.reports)) throw new Error("Invalid daily update archive");
    const dates = new Set();
    for (const report of data.reports) {
      if (!report || !validDate(report.date) || dates.has(report.date) ||
          report.url !== `${report.date}/` ||
          typeof report.title !== "string" || !report.title.trim()) {
        throw new Error("Invalid daily update archive record");
      }
      dates.add(report.date);
    }
    return [...data.reports].sort((left, right) => right.date.localeCompare(left.date));
  }

  function parseArchive(data) {
    const reports = parseCalendar(data);
    for (const report of reports) {
      if (typeof report.description !== "string" || !report.description.trim() ||
          typeof report.text !== "string" || typeof report.excerpt !== "string") {
        throw new Error("Invalid daily update archive search record");
      }
    }
    return reports;
  }

  function calendarWeeks(month) {
    if (typeof month !== "string" || !/^\d{4}-\d{2}$/.test(month) || !validDate(`${month}-01`)) {
      throw new Error("Invalid calendar month");
    }
    const first = new Date(`${month}-01T00:00:00Z`);
    const last = new Date(first);
    last.setUTCMonth(last.getUTCMonth() + 1);
    last.setUTCDate(0);
    const offset = first.getUTCDay();
    const days = last.getUTCDate();
    return Array.from({length: Math.ceil((offset + days) / 7)}, (_, week) =>
      Array.from({length: 7}, (_, weekday) => {
        const day = week * 7 + weekday - offset + 1;
        return day < 1 || day > days ? null : `${month}-${String(day).padStart(2, "0")}`;
      })
    );
  }

  function monthLabel(month) {
    const [year, number] = month.split("-").map(Number);
    return `${year}년 ${number}월`;
  }

  function normalized(value) {
    return value.normalize("NFKC").toLowerCase();
  }

  function queryTerms(query) {
    return [...new Set(normalized(query).trim().split(/\s+/).filter(Boolean))];
  }

  function searchableText(value) {
    const text = value.normalize("NFKC").replace(/[^\S\n]+/g, " ").trim();
    const search = text.toLowerCase();
    const offsets = [];
    // Lowercasing can expand a character (for example, İ), shifting highlight offsets.
    if (text.length !== search.length) {
      let start = 0;
      for (const character of text) {
        const end = start + character.length;
        for (let index = 0; index < character.toLowerCase().length; index++) {
          offsets.push({start, end});
        }
        start = end;
      }
    }
    return {text, search, offsets};
  }

  function createSearchIndex(reports) {
    return reports.map(report => {
      const fields = Object.fromEntries(
        ["date", "title", "description", "text", "excerpt"].map(key => [key, searchableText(report[key])])
      );
      return {report, fields, text: Object.values(fields).map(field => field.search).join(" ")};
    });
  }

  function matchingEntries(index, terms) {
    return terms.length ? index.filter(entry => terms.every(term => entry.text.includes(term))) : [];
  }

  function searchReports(index, query) {
    return matchingEntries(index, queryTerms(query)).map(entry => entry.report);
  }

  function matchRanges(field, terms, firstOnly = false) {
    const ranges = [];
    for (const term of terms) {
      let position = field.search.indexOf(term);
      while (position !== -1) {
        ranges.push({
          start: field.offsets[position]?.start ?? position,
          end: field.offsets[position + term.length - 1]?.end ?? position + term.length,
        });
        if (firstOnly) break;
        position = field.search.indexOf(term, position + term.length);
      }
    }
    const merged = [];
    for (const range of ranges.sort((left, right) => left.start - right.start)) {
      const previous = merged.at(-1);
      if (previous && range.start <= previous.end) previous.end = Math.max(previous.end, range.end);
      else merged.push(range);
    }
    return merged;
  }

  function highlightedElement(documentRef, tag, field, terms, from = 0, to = field.text.length) {
    const element = createElement(documentRef, tag);
    if (from) element.append(createElement(documentRef, "span", "…"));
    let cursor = from;
    for (const range of matchRanges(field, terms)) {
      const start = Math.max(from, range.start);
      const end = Math.min(to, range.end);
      if (start >= end) continue;
      if (start > cursor) element.append(createElement(documentRef, "span", field.text.slice(cursor, start)));
      element.append(createElement(documentRef, "mark", field.text.slice(start, end)));
      cursor = end;
    }
    if (cursor < to) element.append(createElement(documentRef, "span", field.text.slice(cursor, to)));
    if (to < field.text.length) element.append(createElement(documentRef, "span", "…"));
    return element;
  }

  function searchExcerpts(field, terms) {
    const excerpts = [];
    let previousEnd = 0;
    for (const match of matchRanges(field, terms, true)) {
      if (match.start < previousEnd) continue;
      let start = Math.max(previousEnd, match.start - 50, field.text.lastIndexOf("\n", match.start - 1) + 1);
      // Never split a surrogate pair at the excerpt boundary.
      if (/[\uDC00-\uDFFF]/.test(field.text[start] || "")) start++;
      let end = Math.min(field.text.length, start + 180 - (start ? 1 : 0));
      if (end < field.text.length) end--;
      const paragraphEnd = field.text.indexOf("\n", match.end);
      if (paragraphEnd !== -1) end = Math.min(end, paragraphEnd);
      if (/[\uDC00-\uDFFF]/.test(field.text[end] || "")) end--;
      excerpts.push({field, start, end});
      previousEnd = end;
      if (excerpts.length === 2) break;
    }
    return excerpts;
  }

  function createElement(documentRef, tag, text) {
    const element = documentRef.createElement(tag);
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function mountCalendar(root, reports, environment) {
    const documentRef = root.ownerDocument;
    const months = [...new Set(reports.map(report => report.date.slice(0, 7)))].sort();
    const byDate = new Map(reports.map(report => [report.date, report]));
    const selected = root.dataset.dailySelected;
    let month = root.dataset.dailyCalendar;
    if (!months.includes(month) || (selected && !byDate.has(selected))) {
      throw new Error("Invalid archive: the displayed report month is missing");
    }
    const archive = new URL(root.dataset.dailyBase, environment.location.href);
    const select = root.querySelector("[data-daily-month]");
    const previous = root.querySelector("[data-daily-prev]");
    const next = root.querySelector("[data-daily-next]");
    const days = root.querySelector("[data-daily-days]");
    const grid = root.querySelector("[data-daily-grid]");
    const status = root.querySelector("[data-daily-status]");

    select.replaceChildren(...[...months].reverse().map(value => {
      const option = createElement(documentRef, "option", monthLabel(value));
      option.value = value;
      return option;
    }));
    select.disabled = false;

    function render() {
      const rows = calendarWeeks(month).map(week => {
        const row = createElement(documentRef, "tr");
        for (const date of week) {
          const cell = createElement(documentRef, "td");
          if (date === null) {
            cell.setAttribute("aria-hidden", "true");
          } else {
            const report = byDate.get(date);
            const day = createElement(documentRef, report ? "a" : "span", String(Number(date.slice(-2))));
            if (report) {
              day.href = new URL(report.url, archive).href;
              day.dataset.dailyDate = date;
              day.setAttribute("aria-label", `${date} 업데이트: ${report.title}`);
              if (date === selected) day.setAttribute("aria-current", "page");
            } else {
              day.dataset.dailyUnavailable = date;
              day.setAttribute("aria-label", `${date} 자료 없음`);
            }
            cell.append(day);
          }
          row.append(cell);
        }
        return row;
      });
      days.replaceChildren(...rows);
      select.value = month;
      root.dataset.dailyCalendar = month;
      previous.disabled = month === months[0];
      next.disabled = month === months.at(-1);
      grid.setAttribute("aria-label", `${monthLabel(month)} 발행 달력`);
      const count = reports.filter(report => report.date.startsWith(month)).length;
      status.textContent = `${monthLabel(month)} · ${count}일 발행`;
    }

    previous.addEventListener("click", () => {
      const index = months.indexOf(month);
      if (index > 0) {
        month = months[index - 1];
        render();
      }
    });
    next.addEventListener("click", () => {
      const index = months.indexOf(month);
      if (index < months.length - 1) {
        month = months[index + 1];
        render();
      }
    });
    select.addEventListener("change", () => {
      month = select.value;
      render();
    });
    render();
  }

  function mountSearch(root, reports, environment) {
    const documentRef = root.ownerDocument;
    const index = createSearchIndex(reports);
    const archive = new URL(root.dataset.dailyBase, environment.location.href);
    const form = root.querySelector("[data-daily-form]");
    const query = root.querySelector("[data-daily-query]");
    const reset = root.querySelector('button[type="reset"]');
    const results = root.querySelector("[data-daily-results]");
    const status = root.querySelector("[data-daily-search-status]");
    const more = root.querySelector("[data-daily-more]");
    let visible = 10;
    query.disabled = false;
    reset.disabled = false;

    function render() {
      const terms = queryTerms(query.value);
      const matching = matchingEntries(index, terms);
      results.replaceChildren(...matching.slice(0, visible).map(({report, fields}) => {
        const item = createElement(documentRef, "li");
        const time = highlightedElement(documentRef, "time", fields.date, terms);
        time.setAttribute("datetime", report.date);
        const link = highlightedElement(documentRef, "a", fields.title, terms);
        link.href = new URL(report.url, archive).href;
        item.append(time, link);
        const rawOnlyTerms = terms.filter(term => !fields.excerpt.search.includes(term));
        const rawExcerpts = searchExcerpts(fields.text, rawOnlyTerms);
        const excerpts = [
          ...searchExcerpts(fields.excerpt, terms).slice(0, rawExcerpts.length ? 1 : 2),
          ...rawExcerpts,
        ].slice(0, 2);
        if (!excerpts.length || matchRanges(fields.description, terms, true).length) {
          item.append(highlightedElement(documentRef, "p", fields.description, terms));
        }
        for (const {field, start, end} of excerpts) {
          const paragraph = highlightedElement(documentRef, "p", field, terms, start, end);
          paragraph.className = "dg-daily-excerpt";
          item.append(paragraph);
        }
        return item;
      }));
      results.hidden = matching.length === 0;
      more.hidden = matching.length <= visible;
      status.textContent = !query.value.trim()
        ? "검색어를 입력하거나 달력에서 날짜를 선택하세요."
        : matching.length
          ? `${matching.length}개 결과 · ${Math.min(visible, matching.length)}개 표시`
          : "일치하는 업데이트가 없습니다. 다른 검색어나 날짜로 찾아보세요.";
    }

    form.addEventListener("submit", event => event.preventDefault());
    form.addEventListener("reset", event => {
      event.preventDefault();
      query.value = "";
      visible = 10;
      render();
    });
    query.addEventListener("input", () => {
      visible = 10;
      render();
    });
    more.addEventListener("click", () => {
      visible += 10;
      render();
    });
    render();
  }

  async function fetchArchive(url, environment) {
    const response = await environment.fetch(url);
    if (!response.ok) throw new Error(`Daily update archive request failed: ${response.status}`);
    return response.json();
  }

  async function mountDailyUpdates(documentRef, environment) {
    const requests = new Map();
    const mounts = [];
    for (const [selector, parse, mount] of [
      ["[data-daily-calendar]", parseCalendar, mountCalendar],
      ["[data-daily-search]", parseArchive, mountSearch],
    ]) {
      for (const root of documentRef.querySelectorAll(selector)) {
        if (root.dataset.dailyReady) continue;
        root.dataset.dailyReady = "loading";
        const url = new URL(root.dataset.dailySource, environment.location.href).href;
        if (!requests.has(url)) requests.set(url, fetchArchive(url, environment));
        mounts.push(requests.get(url).then(data => {
          mount(root, parse(data), environment);
          root.dataset.dailyReady = "true";
        }).catch(error => {
          const alert = root.querySelector("[data-daily-error]");
          alert.textContent = "업데이트 목록을 불러오지 못했습니다. 새로 고침하거나 상단의 사이트 전체 검색을 이용하세요. 표시된 날짜와 최근 글은 계속 열 수 있습니다.";
          alert.hidden = false;
          root.dataset.dailyReady = "error";
          environment.console.error("Daily update archive:", error);
        }));
      }
    }
    await Promise.all(mounts);
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {parseCalendar, parseArchive, calendarWeeks, createSearchIndex, searchReports, mountCalendar, mountSearch, mountDailyUpdates};
  }
  if (typeof document !== "undefined") {
    const start = () => mountDailyUpdates(document, window);
    if (typeof document$ !== "undefined") document$.subscribe(start);
    else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
  }
})();
