(function () {
  "use strict";

  const storageKey = "dg-sidebar-collapsed";
  const desktopQuery = "(min-width: 1220px)";

  function readStoredState(storage) {
    if (!storage) return false;
    try {
      return storage.getItem(storageKey) === "true";
    } catch {
      return false;
    }
  }

  function writeStoredState(storage, collapsed) {
    if (!storage) return;
    try {
      storage.setItem(storageKey, collapsed ? "true" : "false");
    } catch {
      // Ignore storage failures (private mode / strict policies).
    }
  }

  function getStorage(windowRef) {
    try {
      return windowRef.localStorage || null;
    } catch {
      return null;
    }
  }

  function applyState(root, button, storage, collapsed) {
    root.dataset.dgSidebarCollapsed = collapsed ? "true" : "false";
    button.setAttribute("aria-expanded", collapsed ? "false" : "true");
    button.setAttribute("aria-label", "왼쪽 메뉴");
    writeStoredState(storage, collapsed);
  }

  function mountSidebarToggle(documentRef, windowRef) {
    if (!documentRef || !windowRef) return null;
    const root = documentRef.documentElement;
    if (!root || root.dataset.dgSidebarToggleReady === "true") return null;
    const headerInner = documentRef.querySelector(".md-header__inner");
    if (!headerInner) return null;

    root.dataset.dgSidebarToggleReady = "true";

    const button = documentRef.createElement("button");
    button.type = "button";
    button.className = "md-header__button md-icon dg-sidebar-toggle";
    button.setAttribute("aria-expanded", "true");
    button.setAttribute("aria-label", "왼쪽 메뉴");
    button.title = "왼쪽 메뉴 접기/펼치기";
    button.innerHTML =
      '<svg viewBox="0 0 24 24" role="presentation" focusable="false"><path d="M3 6h18v2H3V6zm0 5h18v2H3v-2zm0 5h18v2H3v-2z"/></svg>';

    const mediaQuery = typeof windowRef.matchMedia === "function"
      ? windowRef.matchMedia(desktopQuery)
      : null;
    const storage = getStorage(windowRef);

    const syncState = () => {
      const collapsed = readStoredState(storage);
      applyState(root, button, storage, collapsed);
    };

    button.addEventListener("click", () => {
      const collapsed = root.dataset.dgSidebarCollapsed === "true";
      applyState(root, button, storage, !collapsed);
    });

    if (mediaQuery) {
      const onMediaChange = event => {
        if (event.matches) syncState();
      };
      if (typeof mediaQuery.addEventListener === "function") {
        mediaQuery.addEventListener("change", onMediaChange);
      } else if (typeof mediaQuery.addListener === "function") {
        mediaQuery.addListener(onMediaChange);
      }
    }

    syncState();
    headerInner.insertBefore(button, headerInner.firstChild);
    return button;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {mountSidebarToggle, readStoredState, applyState, getStorage};
  }

  if (typeof document !== "undefined") {
    const start = () => mountSidebarToggle(document, window);
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
  }
})();
