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

  // "/" focuses the search box, Escape closes the menu.
  document.addEventListener("keydown", function (event) {
    var tag = (event.target.tagName || "").toLowerCase();
    var typing = tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable;
    if (event.key === "/" && !typing) {
      var box = document.getElementById("site-search");
      if (box) { event.preventDefault(); box.focus(); box.select(); }
    }
    if (event.key === "Escape") { document.body.classList.remove("menu-open"); }
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
