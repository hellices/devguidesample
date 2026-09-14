const test = require("node:test");
const assert = require("node:assert/strict");
const toggle = require("../../docs/assets/javascripts/sidebar-toggle.js");

function createFixture(stored = "false") {
  const root = {dataset: {}};
  const listeners = {};
  const buttonListeners = {};
  const inserted = [];
  const mediaListeners = [];

  const button = {
    attributes: {},
    type: "",
    className: "",
    title: "",
    innerHTML: "",
    setAttribute(name, value) {
      this.attributes[name] = value;
    },
    addEventListener(type, callback) {
      buttonListeners[type] = callback;
    },
  };

  const headerInner = {
    firstChild: null,
    insertBefore(node) {
      inserted.push(node);
    },
  };

  const localStorage = {
    value: stored,
    getItem() {
      return this.value;
    },
    setItem(_key, value) {
      this.value = value;
    },
  };

  const media = {
    matches: true,
    addEventListener(type, callback) {
      if (type === "change") mediaListeners.push(callback);
    },
    emit(matches) {
      this.matches = matches;
      for (const callback of mediaListeners) callback({matches});
    },
  };

  const documentRef = {
    documentElement: root,
    querySelector(selector) {
      return selector === ".md-header__inner" ? headerInner : null;
    },
    createElement(tag) {
      assert.equal(tag, "button");
      return button;
    },
    addEventListener(type, callback) {
      listeners[type] = callback;
    },
  };

  const windowRef = {
    localStorage,
    matchMedia() {
      return media;
    },
  };

  return {
    root,
    button,
    buttonListeners,
    inserted,
    documentRef,
    windowRef,
    localStorage,
    media,
    listeners,
  };
}

test("mountSidebarToggle inserts a button and applies stored collapsed state", () => {
  const fixture = createFixture("true");
  const mounted = toggle.mountSidebarToggle(fixture.documentRef, fixture.windowRef);
  assert.equal(mounted, fixture.button);
  assert.equal(fixture.inserted.length, 1);
  assert.equal(fixture.root.dataset.dgSidebarCollapsed, "true");
  assert.equal(fixture.button.attributes["aria-pressed"], "true");
  assert.equal(fixture.button.attributes["aria-label"], "왼쪽 메뉴 펼치기");
  assert.equal(fixture.root.dataset.dgSidebarToggleReady, "true");
});

test("button click toggles collapsed state and persists to storage", () => {
  const fixture = createFixture("false");
  toggle.mountSidebarToggle(fixture.documentRef, fixture.windowRef);
  fixture.buttonListeners.click();
  assert.equal(fixture.root.dataset.dgSidebarCollapsed, "true");
  assert.equal(fixture.localStorage.value, "true");
  fixture.buttonListeners.click();
  assert.equal(fixture.root.dataset.dgSidebarCollapsed, "false");
  assert.equal(fixture.localStorage.value, "false");
});

test("media change back to desktop re-syncs persisted state", () => {
  const fixture = createFixture("false");
  toggle.mountSidebarToggle(fixture.documentRef, fixture.windowRef);
  fixture.buttonListeners.click();
  assert.equal(fixture.localStorage.value, "true");
  fixture.root.dataset.dgSidebarCollapsed = "false";
  fixture.media.emit(true);
  assert.equal(fixture.root.dataset.dgSidebarCollapsed, "true");
});

test("mountSidebarToggle is idempotent once initialized", () => {
  const fixture = createFixture("false");
  toggle.mountSidebarToggle(fixture.documentRef, fixture.windowRef);
  const second = toggle.mountSidebarToggle(fixture.documentRef, fixture.windowRef);
  assert.equal(second, null);
  assert.equal(fixture.inserted.length, 1);
});
