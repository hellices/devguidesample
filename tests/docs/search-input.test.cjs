const test = require("node:test");
const assert = require("node:assert/strict");
const searchInput = require("../../docs/assets/javascripts/search-input.js");

const searchSelector = 'input[data-md-component="search-query"]';

function createTarget(selector) {
  const dispatched = [];
  return {
    dispatched,
    matches(candidate) {
      return candidate === selector;
    },
    dispatchEvent(event) {
      dispatched.push(event.type);
      return true;
    },
  };
}

function createFixture() {
  const listeners = {};
  const documentRef = {
    documentElement: {dataset: {}},
    addEventListener(type, callback, options) {
      listeners[type] = {callback, options};
    },
  };
  class FakeKeyboardEvent {
    constructor(type, init) {
      this.type = type;
      this.init = init;
    }
  }
  return {listeners, documentRef, windowRef: {KeyboardEvent: FakeKeyboardEvent}};
}

test("non-keyboard input on the header search box is forwarded as keyup", () => {
  const fixture = createFixture();
  searchInput.mountSearchInputBridge(fixture.documentRef, fixture.windowRef);
  const query = createTarget(searchSelector);

  fixture.listeners.input.callback({target: query});
  fixture.listeners.compositionend.callback({target: query});

  assert.deepEqual(query.dispatched, ["keyup", "keyup"]);
  assert.equal(fixture.listeners.input.options, true);
});

test("other inputs such as the explore text filter are left untouched", () => {
  const fixture = createFixture();
  searchInput.mountSearchInputBridge(fixture.documentRef, fixture.windowRef);
  const other = createTarget("input[data-explore-text]");

  fixture.listeners.input.callback({target: other});
  fixture.listeners.compositionend.callback({target: null});

  assert.deepEqual(other.dispatched, []);
});

test("the bridge mounts once per document", () => {
  const fixture = createFixture();
  assert.equal(searchInput.mountSearchInputBridge(fixture.documentRef, fixture.windowRef), true);
  assert.equal(searchInput.mountSearchInputBridge(fixture.documentRef, fixture.windowRef), false);
});
