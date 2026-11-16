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
      /^\/documents\/uploads\/[0-9a-f-]{36}\/download/.test(target.pathname) ||
      /^\/staff\/prepared\/[0-9a-f-]{36}\/download/.test(target.pathname) ||
      /^\/student\/documents\/fill-form\//.test(target.pathname) ||  // filled form download
      /^\/student\/account\/export\//.test(target.pathname) ||       // personal data export
      /^\/privacy\/export\//.test(target.pathname) ||                // GDPR data export download
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
  function closeMenu() {
    document.body.classList.remove("menu-open");
    document.querySelectorAll(".menu-toggle").forEach(function (btn) {
      btn.setAttribute("aria-expanded", "false");
    });
  }

  document.addEventListener("htmx:afterSettle", function (event) {
    // Live search results land inside the open dialog: not a page change.
    if (event.detail && event.detail.target && event.detail.target.id === "palette-results") { return; }
    closeMenu();
    var config = (event.detail && event.detail.requestConfig) || {};
    if ((config.verb || "get").toLowerCase() === "get") {
      window.scrollTo(0, 0);
      var main = document.getElementById("main");
      if (main) { main.focus({ preventScroll: true }); }
    }
  });

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest(".menu-toggle");
    if (toggle) {
      var open = document.body.classList.toggle("menu-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      return;
    }
    if (document.body.classList.contains("menu-open") && !event.target.closest(".sidebar")) {
      closeMenu();
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
      closeMenu();
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
    var elt = event.detail && event.detail.elt;
    if (verb === "get" && elt && elt.tagName === "A") {
      var navGroup = elt.closest(".sidebar, .view-switch, .doc-tabs");
      if (navGroup) {
        navGroup.querySelectorAll('a[aria-current="page"]').forEach(function (a) {
          a.removeAttribute("aria-current");
        });
        elt.setAttribute("aria-current", "page");
      }
    }
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

// "Copy text": copies the element named by data-copy, and says so in-place without layout shift.
document.addEventListener("click", function (event) {
  var button = event.target.closest && event.target.closest("button[data-copy]");
  if (!button) { return; }
  var source = document.getElementById(button.dataset.copy);
  var status = button.parentElement && button.parentElement.querySelector('[role="status"]');
  if (!source || !navigator.clipboard) { return; }
  var originalLabel = button.getAttribute("data-copy-label") || button.textContent;
  button.setAttribute("data-copy-label", originalLabel);
  button.style.minWidth = button.offsetWidth + "px";
  var textToCopy = (typeof source.value === "string" ? source.value : source.innerText).trim();
  navigator.clipboard.writeText(textToCopy).then(function () {
    button.textContent = "Copied \u2713";
    button.setAttribute("data-copied", "true");
    if (status) { status.textContent = "Copied."; }
    clearTimeout(button._copyTimer);
    button._copyTimer = setTimeout(function () {
      button.textContent = originalLabel;
      button.removeAttribute("data-copied");
      if (status) { status.textContent = ""; }
    }, 2000);
  }, function () {
    if (status) { status.textContent = "Could not copy. Select the text instead."; }
  });
});

// Progressive disclosure for multi-part gap-interview question groups:
// follow-up questions stay hidden until the student starts answering the parent question.
function syncGapGroups() {
  document.querySelectorAll("[data-gap-group-parent]").forEach(function (parentEl) {
    var slug = parentEl.getAttribute("data-gap-group-parent");
    var parentInput = parentEl.querySelector("input");
    if (!slug || !parentInput) { return; }
    var children = document.querySelectorAll('[data-gap-group-child="' + slug + '"]');
    var hasChildText = Array.prototype.some.call(children, function (c) {
      var inp = c.querySelector("input");
      return inp && inp.value.trim().length > 0;
    });
    var show = parentInput.value.trim().length > 0 || hasChildText;
    children.forEach(function (c) { c.hidden = !show; });
  });
}
document.addEventListener("DOMContentLoaded", syncGapGroups);
document.addEventListener("htmx:afterSettle", syncGapGroups);
document.addEventListener("input", function (event) {
  if (event.target && event.target.closest && event.target.closest("[data-gap-group-parent]")) {
    syncGapGroups();
  }
});

// Client-side filter pills on the recommendation pack page (/student/recommendation/).
document.addEventListener("click", function (event) {
  var pill = event.target.closest && event.target.closest("button[data-pack-filter]");
  if (!pill) { return; }
  var bar = pill.closest(".pack-filter-bar");
  if (!bar) { return; }
  var filter = pill.getAttribute("data-pack-filter") || "all";
  bar.querySelectorAll("button[data-pack-filter]").forEach(function (b) {
    b.setAttribute("aria-pressed", b === pill ? "true" : "false");
    b.classList.toggle("is-active", b === pill);
  });
  document.querySelectorAll(".pack-section").forEach(function (sec) {
    var visibleInSec = 0;
    var visibleInGrid = 0;
    sec.querySelectorAll(".candidate").forEach(function (card) {
      var match = false;
      if (filter === "all") {
        match = true;
      } else if (filter === "picked") {
        match = card.getAttribute("data-pack-picked") === "true";
      } else if (filter.indexOf("kind:") === 0) {
        match = card.getAttribute("data-pack-kind") === filter.slice(5);
      } else if (filter.indexOf("country:") === 0) {
        match = card.getAttribute("data-pack-country") === filter.slice(8);
      } else if (filter.indexOf("tier:") === 0) {
        match = card.getAttribute("data-pack-tier") === filter.slice(5);
      }
      card.hidden = !match;
      var li = card.closest(".match-grid > li");
      if (li) {
        li.hidden = !match;
        if (match) { visibleInGrid += 1; }
      }
      if (match) { visibleInSec += 1; }
    });
    var groupLabel = sec.querySelector(".group-label");
    var matchGrid = sec.querySelector(".match-grid");
    var quietLine = sec.querySelector(".quiet-line");
    if (groupLabel) { groupLabel.hidden = visibleInGrid === 0; }
    if (matchGrid) { matchGrid.hidden = visibleInGrid === 0; }
    if (quietLine) { quietLine.hidden = filter === "kind:award"; }
    sec.hidden = visibleInSec === 0;
  });
});

// Fold open card disclosures (.card-remove, .card-more) when clicking Cancel,
// clicking outside the disclosure, or pressing Escape.
document.addEventListener("click", function (event) {
  var closeBtn = event.target.closest && event.target.closest("[data-close-details]");
  if (closeBtn) {
    var details = closeBtn.closest("details");
    if (details) { details.open = false; }
    return;
  }
  document.querySelectorAll("details.card-remove[open], details.card-more[open]").forEach(function (d) {
    if (!d.contains(event.target)) { d.open = false; }
  });
});
document.addEventListener("keydown", function (event) {
  if (event.key === "Escape") {
    document.querySelectorAll("details.card-remove[open], details.card-more[open]").forEach(function (d) {
      d.open = false;
    });
  }
});

/* Home numbers count up once when the page shows them (2026-11-16). The server
 * renders the final value, so reduced motion and no-JS readers see it at once. */
function countUp(root) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  root.querySelectorAll("[data-count]").forEach(function (el) {
    var target = parseInt(el.getAttribute("data-count"), 10);
    if (!target || el.dataset.counted) return;
    el.dataset.counted = "1";
    var start = performance.now();
    function tick(now) {
      var t = Math.min(1, (now - start) / 900);
      el.textContent = String(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) requestAnimationFrame(tick);
    }
    el.textContent = "0";
    requestAnimationFrame(tick);
  });
}
document.addEventListener("DOMContentLoaded", function () { countUp(document); });
document.addEventListener("htmx:load", function (event) { countUp(event.target); });

/* ---------- profile questions (2026-11-16) ----------
 * Each enhancer upgrades plain HTML that already works without script. */
function initProfileQuestions(root) {
  var scope = root && root.querySelectorAll ? root : document;

  /* One country: the <select> becomes a box you type into. Every country is
   * listed; typing keeps names that start with the letters first, then the rest
   * that contain them. The select stays in the form and holds the answer. */
  scope.querySelectorAll("select[data-country-search]").forEach(function (select) {
    if (select.dataset.enhanced) return;
    select.dataset.enhanced = "1";
    var options = Array.prototype.slice.call(select.options).filter(function (o) { return o.value; });
    var wrap = document.createElement("div");
    wrap.className = "combo";
    var input = document.createElement("input");
    input.type = "text";
    input.className = "combo-input";
    input.id = select.id + "_search";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("autocomplete", "off");
    input.placeholder = "Start typing a country…";
    var list = document.createElement("ul");
    list.className = "combo-list";
    list.id = select.id + "_list";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    input.setAttribute("aria-controls", list.id);
    var label = document.querySelector('label[for="' + select.id + '"]');
    if (label) label.setAttribute("for", input.id);
    var chosen = select.options[select.selectedIndex];
    if (chosen && chosen.value) input.value = chosen.text;
    select.hidden = true;
    select.removeAttribute("autofocus");
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(input);
    wrap.appendChild(list);
    wrap.appendChild(select);
    var active = -1;
    function render() {
      var q = input.value.trim().toLowerCase();
      var starts = [], contains = [];
      options.forEach(function (o) {
        var name = o.text.toLowerCase();
        if (!q || name.indexOf(q) === 0) starts.push(o);
        else if (name.indexOf(q) > 0) contains.push(o);
      });
      var shown = starts.concat(contains);
      list.innerHTML = "";
      shown.forEach(function (o, i) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        li.id = list.id + "_" + o.value;
        li.textContent = o.text;
        li.dataset.value = o.value;
        li.addEventListener("mousedown", function (e) { e.preventDefault(); pick(o); });
        list.appendChild(li);
      });
      if (!shown.length) {
        var none = document.createElement("li");
        none.className = "combo-empty";
        none.textContent = "No country matches";
        list.appendChild(none);
      }
      active = shown.length ? 0 : -1;
      mark();
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }
    function mark() {
      Array.prototype.forEach.call(list.children, function (li, i) {
        li.setAttribute("aria-selected", i === active ? "true" : "false");
        if (i === active) { input.setAttribute("aria-activedescendant", li.id); li.scrollIntoView({ block: "nearest" }); }
      });
    }
    function pick(o) {
      select.value = o.value;
      input.value = o.text;
      close();
    }
    function close() { list.hidden = true; input.setAttribute("aria-expanded", "false"); }
    input.addEventListener("click", render);
    input.addEventListener("input", function () { select.value = ""; render(); });
    input.addEventListener("blur", function () {
      close();
      var exact = options.filter(function (o) { return o.text.toLowerCase() === input.value.trim().toLowerCase(); })[0];
      if (exact) pick(exact);
    });
    input.addEventListener("keydown", function (e) {
      var items = list.querySelectorAll('li[role="option"]');
      if (e.key === "ArrowDown") { e.preventDefault(); if (list.hidden) render(); active = Math.min(items.length - 1, active + 1); mark(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); mark(); }
      else if (e.key === "Enter" && !list.hidden && items[active]) {
        e.preventDefault();
        pick(options.filter(function (o) { return o.value === items[active].dataset.value; })[0]);
      } else if (e.key === "Escape") { close(); }
    });
    if (document.activeElement === document.body || !document.activeElement) input.focus();
  });

  /* Many countries: a search box filters the continent groups. */
  scope.querySelectorAll("[data-country-picker]").forEach(function (picker) {
    if (picker.dataset.enhanced) return;
    picker.dataset.enhanced = "1";
    var filter = picker.querySelector("[data-country-filter]");
    var count = picker.querySelector("[data-country-count]");
    filter.hidden = false;
    function tally() {
      var n = picker.querySelectorAll('input[name="country_ticks"]:checked').length;
      count.textContent = n ? n + " selected" : "";
    }
    filter.addEventListener("input", function () {
      var q = filter.value.trim().toLowerCase();
      picker.querySelectorAll("[data-continent]").forEach(function (group) {
        var any = false;
        group.querySelectorAll(".country-chip").forEach(function (chip) {
          var hit = !q || chip.dataset.name.indexOf(q) !== -1;
          chip.hidden = !hit;
          any = any || hit;
        });
        group.hidden = !any;
      });
    });
    filter.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      e.preventDefault();
      var first = picker.querySelector(".country-chip:not([hidden]) input");
      if (first) { first.checked = !first.checked; tally(); filter.select(); }
    });
    picker.addEventListener("change", tally);
    tally();
  });

  /* Repeating rows: filled rows plus one empty, and "Add another". */
  scope.querySelectorAll("[data-repeat]").forEach(function (group) {
    if (group.dataset.enhanced) return;
    group.dataset.enhanced = "1";
    var rows = Array.prototype.slice.call(group.querySelectorAll("[data-repeat-row]"));
    function filled(row) {
      return Array.prototype.some.call(row.querySelectorAll("input:not([type=hidden]), select, textarea"), function (el) {
        return el.value && el.value.trim() !== "";
      });
    }
    var last = 0;
    rows.forEach(function (row, i) { if (filled(row)) last = i + 1; });
    var showUpTo = Math.max(1, last);
    rows.forEach(function (row, i) { row.hidden = i >= showUpTo; });
    if (rows.length > showUpTo) {
      var add = document.createElement("button");
      add.type = "button";
      add.className = "btn btn-quiet q-add";
      add.textContent = "+ Add another " + (group.dataset.noun || "").toLowerCase();
      add.addEventListener("click", function () {
        var next = rows.filter(function (r) { return r.hidden; })[0];
        if (next) {
          next.hidden = false;
          var field = next.querySelector("input:not([type=hidden]), select, textarea");
          if (field) field.focus();
        }
        if (!rows.some(function (r) { return r.hidden; })) add.remove();
      });
      group.appendChild(add);
    }
  });

  /* Language cards: show the test, score and date only when they apply. */
  scope.querySelectorAll("[data-lang-card]").forEach(function (card) {
    if (card.dataset.enhanced) return;
    card.dataset.enhanced = "1";
    function sync() {
      var picked = card.querySelector('input[type="radio"]:checked');
      var status = picked ? picked.value : "NONE";
      card.querySelectorAll("[data-when]").forEach(function (el) {
        el.hidden = el.dataset.when.split(" ").indexOf(status) === -1;
      });
    }
    card.addEventListener("change", sync);
    sync();
  });
}
document.addEventListener("DOMContentLoaded", function () { initProfileQuestions(document); });
document.addEventListener("htmx:load", function (event) { initProfileQuestions(event.target); });
