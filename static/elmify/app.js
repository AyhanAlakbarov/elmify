// Elmify app shell. No framework: htmx (vendored) does the in-place updates,
// this file only handles the menu, the search shortcut and the few requests
// htmx must NOT make in the background (downloads, other sites, OAuth hops).
(function () {
  "use strict";

  // Requests that must be a real browser navigation, never a background swap.
  function mustNavigate(url) {
    var target;
    try { target = new URL(url, window.location.href); } catch (e) { return false; }
    if (target.origin !== window.location.origin) { return true; }
    return /^\/documents\/[0-9a-f-]{36}\//.test(target.pathname) || // file downloads
      /^\/mailbox\/connect\//.test(target.pathname) ||               // Google / Microsoft sign-in
      /^\/accounts\/logout\//.test(target.pathname);
  }

  document.addEventListener("htmx:confirm", function (event) {
    var detail = event.detail || {};
    var path = detail.path || "";
    var verb = (detail.verb || "get").toLowerCase();
    if (!mustNavigate(path)) { return; }
    event.preventDefault();
    var elt = detail.elt;
    if (verb === "get" && elt && elt.tagName === "A") {
      window.location.href = elt.href;
    } else if (elt && elt.tagName === "FORM") {
      elt.setAttribute("hx-boost", "false");
      HTMLFormElement.prototype.submit.call(elt);
    } else {
      window.location.href = path;
    }
  });

  // Keep the shell's state right after an in-place swap: the new page decides
  // which nav item is current, and the menu closes.
  // A followed link starts at the top of the new page; a posted form keeps the
  // reader where they were, so the card they just changed stays in view.
  document.addEventListener("htmx:afterSettle", function (event) {
    // Live search results land inside the open dialog: not a page change.
    if (event.detail && event.detail.target && event.detail.target.id === "palette-results") { return; }
    document.body.classList.remove("menu-open");
    var config = (event.detail && event.detail.requestConfig) || {};
    if ((config.verb || "get").toLowerCase() === "get") { window.scrollTo(0, 0); }
    var main = document.getElementById("main");
    if (main) { main.focus({ preventScroll: true }); }
  });

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest(".menu-toggle");
    if (toggle) {
      var open = document.body.classList.toggle("menu-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      return;
    }
    if (document.body.classList.contains("menu-open") && !event.target.closest(".sidebar")) {
      document.body.classList.remove("menu-open");
    }
  });

  // ---------- search: a dialog opened with Ctrl K / ⌘ K, "/" or the top-bar button ----------
  var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
  function markShortcut() {
    if (!isMac) { return; }
    document.querySelectorAll(".kbd-mod").forEach(function (el) { el.textContent = "⌘"; });
  }
  document.addEventListener("DOMContentLoaded", markShortcut);
  document.addEventListener("htmx:afterSettle", markShortcut);

  var paletteDefault = null;
  function openPalette() {
    var dialog = document.getElementById("palette");
    if (!dialog || dialog.open || typeof dialog.showModal !== "function") { return false; }
    var results = document.getElementById("palette-results");
    if (results && paletteDefault === null) { paletteDefault = results.innerHTML; }
    dialog.showModal();
    var box = document.getElementById("palette-q");
    if (box) { box.focus(); box.select(); }
    return true;
  }
  function closePalette() {
    var dialog = document.getElementById("palette");
    if (dialog && dialog.open) { dialog.close(); }
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest(".palette-open")) { openPalette(); return; }
    var dialog = document.getElementById("palette");
    // A click on the backdrop (the dialog itself, outside its content) closes it.
    if (dialog && event.target === dialog) { closePalette(); }
    // A followed result closes the dialog; the link then loads in place.
    if (dialog && dialog.open && event.target.closest("#palette-results a")) { closePalette(); }
  });

  // Empty box: show the "Go to" shortcuts again instead of an empty result.
  document.addEventListener("input", function (event) {
    if (event.target.id !== "palette-q" || event.target.value.trim()) { return; }
    var results = document.getElementById("palette-results");
    if (results && paletteDefault !== null) { results.innerHTML = paletteDefault; }
  });

  // Arrow keys move through the results; Enter on the box opens the full search page.
  document.addEventListener("keydown", function (event) {
    var dialog = document.getElementById("palette");
    if (!dialog || !dialog.open || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) { return; }
    var links = Array.prototype.slice.call(dialog.querySelectorAll("#palette-results a"));
    if (!links.length) { return; }
    event.preventDefault();
    var at = links.indexOf(document.activeElement);
    var next = event.key === "ArrowDown" ? at + 1 : at - 1;
    if (next < 0) { document.getElementById("palette-q").focus(); return; }
    links[Math.min(next, links.length - 1)].focus();
  });

  document.addEventListener("keydown", function (event) {
    var tag = (event.target.tagName || "").toLowerCase();
    var typing = tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable;
    var combo = (event.ctrlKey || event.metaKey) && (event.key === "k" || event.key === "K");
    if (combo || (event.key === "/" && !typing)) {
      if (openPalette()) { event.preventDefault(); }
    }
    if (event.key === "Escape") {
      document.body.classList.remove("menu-open");
      // In a search box the browser's first Escape only clears the text; close the dialog at once.
      var dialog = document.getElementById("palette");
      if (dialog && dialog.open) { event.preventDefault(); closePalette(); }
    }
  });

  // A refusal that is a whole page (the views' inline-error re-renders) swaps
  // in as usual. A bare-text refusal (e.g. HttpResponseBadRequest(str(err)))
  // would replace the entire app with one line, so it is shown as an alert on
  // the current page instead. A server error never swaps; say so.
  function alertOnPage(text) {
    var main = document.getElementById("main");
    if (!main) { return; }
    var old = main.querySelector(".js-request-alert");
    if (old) { old.remove(); }
    var note = document.createElement("p");
    note.className = "note note-error js-request-alert";
    note.setAttribute("role", "alert");
    note.textContent = text;
    main.insertBefore(note, main.firstChild);
    note.scrollIntoView({ block: "nearest" });
  }

  document.addEventListener("htmx:beforeSwap", function (event) {
    var xhr = event.detail && event.detail.xhr;
    if (!xhr || xhr.status < 400 || xhr.status >= 500) { return; }
    var body = xhr.responseText || "";
    if (!/<(html|main|body)[\s>]/i.test(body)) {
      event.detail.shouldSwap = false;
      alertOnPage(body.trim() || "That did not work. Check the form and try again.");
    }
  });

  document.addEventListener("htmx:responseError", function (event) {
    var xhr = event.detail && event.detail.xhr;
    if (xhr && xhr.status >= 500) { alertOnPage("Something went wrong on our side. Try again in a moment."); }
  });

  document.addEventListener("htmx:sendError", function () {
    alertOnPage("You seem to be offline. Check your connection and try again.");
  });

  // The page's entrance motion is for arriving somewhere. After a form posts
  // and the same page comes back, play nothing: the reader stays put.
  document.addEventListener("htmx:beforeRequest", function (event) {
    var verb = ((event.detail && event.detail.requestConfig && event.detail.requestConfig.verb) || "get").toLowerCase();
    document.body.classList.toggle("is-posting", verb !== "get");
  });

  // A button shows it is working while its form is posting.
  document.addEventListener("htmx:beforeRequest", function (event) {
    var elt = event.detail && event.detail.elt;
    if (elt && elt.tagName === "FORM") {
      var button = elt.querySelector('button[type="submit"], button:not([type])');
      if (button) { button.setAttribute("aria-busy", "true"); }
    }
  });
})();

// When a request ends without replacing the page (a refusal shown as an alert),
// the button must stop looking busy.
document.addEventListener("htmx:afterRequest", function (event) {
  var elt = event.detail && event.detail.elt;
  if (elt && elt.querySelectorAll) {
    elt.querySelectorAll('[aria-busy="true"]').forEach(function (b) { b.removeAttribute("aria-busy"); });
  }
});

// "Copy text": copies the element named by data-copy, and says so.
document.addEventListener("click", function (event) {
  var button = event.target.closest && event.target.closest("button[data-copy]");
  if (!button) { return; }
  var source = document.getElementById(button.dataset.copy);
  var status = button.parentElement && button.parentElement.querySelector('[role="status"]');
  if (!source || !navigator.clipboard) { return; }
  navigator.clipboard.writeText(source.innerText.trim()).then(function () {
    if (status) { status.textContent = "Copied."; }
  }, function () {
    if (status) { status.textContent = "Could not copy. Select the text instead."; }
  });
});
