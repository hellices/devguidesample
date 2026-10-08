(function () {
  "use strict";

  function validDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false;
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
  }

  function parseArchive(data) {
    if (!data || !Array.isArray(data.reports)) throw new Error("Invalid daily update archive");
    const dates = new Set();
    for (const report of data.reports) {
      if (!report || !validDate(report.date) || dates.has(report.date) ||
          report.url !== `${report.date}/` ||
          !["title", "description", "text"].every(key => typeof report[key] === "string") ||
          !report.title.trim() || !report.description.trim()) {
        throw new Error("Invalid daily update archive record");
      }
      dates.add(report.date);
    }
    return [...data.reports].sort((left, right) => right.date.localeCompare(left.date));
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

  function searchReports(reports, query) {
    const terms = normalized(query).trim().split(/\s+/).filter(Boolean);
    if (!terms.length) return [];
    return reports.filter(report => {
      const text = normalized(`${report.date} ${report.title} ${report.description} ${report.text}`);
      return terms.every(term => text.includes(term));
    });
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
      const matching = searchReports(reports, query.value);
      results.replaceChildren(...matching.slice(0, visible).map(report => {
        const item = createElement(documentRef, "li");
        const time = createElement(documentRef, "time", report.date);
        time.setAttribute("datetime", report.date);
        const link = createElement(documentRef, "a", report.title);
        link.href = new URL(report.url, archive).href;
        item.append(time, link, createElement(documentRef, "p", report.description));
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
    return parseArchive(await response.json());
  }

  async function mountDailyUpdates(documentRef, environment) {
    const requests = new Map();
    const mounts = [];
    for (const [selector, mount] of [
      ["[data-daily-calendar]", mountCalendar],
      ["[data-daily-search]", mountSearch],
    ]) {
      for (const root of documentRef.querySelectorAll(selector)) {
        if (root.dataset.dailyReady) continue;
        root.dataset.dailyReady = "loading";
        const url = new URL(root.dataset.dailySource, environment.location.href).href;
        if (!requests.has(url)) requests.set(url, fetchArchive(url, environment));
        mounts.push(requests.get(url).then(reports => {
          mount(root, reports, environment);
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
    module.exports = {parseArchive, calendarWeeks, searchReports, mountCalendar, mountSearch, mountDailyUpdates};
  }
  if (typeof document !== "undefined") {
    const start = () => mountDailyUpdates(document, window);
    if (typeof document$ !== "undefined") document$.subscribe(start);
    else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
  }
})();
