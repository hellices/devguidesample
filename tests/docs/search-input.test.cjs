const test = require("node:test");
const assert = require("node:assert/strict");
const searchInput = require("../../docs/assets/javascripts/search-input.js");

const searchSelector = 'input[data-md-component="search-query"]';

class FakeKeyboardEvent {
  constructor(type, init) {
    this.type = type;
    this.init = init;
  }
}

function createTarget(selector) {
  const dispatched = [];
  const events = [];
  return {
    dispatched,
    events,
    matches(candidate) {
      return candidate === selector;
    },
    dispatchEvent(event) {
      // Mirror EventTarget.dispatchEvent, which rejects non-Event arguments.
      if (!(event instanceof FakeKeyboardEvent)) {
        throw new TypeError("dispatchEvent requires an Event instance");
      }
      events.push(event);
      dispatched.push(event.type);
      return true;
    },
  };
}

function createFixture() {
  const listeners = {};
  const registrations = [];
  const documentRef = {
    documentElement: {dataset: {}},
    addEventListener(type, callback, options) {
      registrations.push(type);
      listeners[type] = {callback, options};
    },
  };
  return {listeners, registrations, documentRef, windowRef: {KeyboardEvent: FakeKeyboardEvent}};
}

test("non-keyboard input on the header search box is forwarded as keyup", () => {
  const fixture = createFixture();
  searchInput.mountSearchInputBridge(fixture.documentRef, fixture.windowRef);
  const query = createTarget(searchSelector);

  fixture.listeners.input.callback({target: query});
  fixture.listeners.compositionend.callback({target: query});

  assert.deepEqual(query.dispatched, ["keyup", "keyup"]);
  for (const event of query.events) {
    assert.ok(event instanceof FakeKeyboardEvent);
    assert.deepEqual(event.init, {bubbles: true});
  }
  assert.equal(fixture.listeners.input.options, true);
});

test("in-progress IME composition is not forwarded until compositionend", () => {
  const fixture = createFixture();
  searchInput.mountSearchInputBridge(fixture.documentRef, fixture.windowRef);
  const query = createTarget(searchSelector);

  fixture.listeners.input.callback({target: query, isComposing: true});
  assert.deepEqual(query.dispatched, []);

  fixture.listeners.compositionend.callback({target: query});
  assert.deepEqual(query.dispatched, ["keyup"]);
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
  assert.deepEqual(fixture.registrations, ["input", "compositionend"]);
  assert.equal(searchInput.mountSearchInputBridge(fixture.documentRef, fixture.windowRef), false);
  assert.deepEqual(fixture.registrations, ["input", "compositionend"]);
});
