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
