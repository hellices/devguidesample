(function () {
  "use strict";

  const searchSelector = 'input[data-md-component="search-query"]';

  // Material reads the header search query only on keyup. IME commits, mouse
  // paste, mobile predictions and voice input change the value without a
  // keyup, so the query never reaches the search worker. Forward those changes;
  // in-progress IME input is skipped and the committed text arrives on
  // compositionend.
  function mountSearchInputBridge(documentRef, windowRef) {
    if (!documentRef || !windowRef) return false;
    const root = documentRef.documentElement;
    if (!root || root.dataset.dgSearchInputReady === "true") return false;
    root.dataset.dgSearchInputReady = "true";

    const forward = event => {
      if (event.isComposing) return;
      const target = event.target;
      if (!target || typeof target.matches !== "function" || !target.matches(searchSelector)) return;
      const KeyboardEventRef = windowRef.KeyboardEvent || windowRef.Event;
      target.dispatchEvent(new KeyboardEventRef("keyup", {bubbles: true}));
    };

    documentRef.addEventListener("input", forward, true);
    documentRef.addEventListener("compositionend", forward, true);
    return true;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {mountSearchInputBridge};
  }

  if (typeof document !== "undefined") {
    mountSearchInputBridge(document, window);
  }
})();
