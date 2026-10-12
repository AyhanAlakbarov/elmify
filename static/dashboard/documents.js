// The documents page's one script (dashboard spec §6). It calls the existing
// JSON door (apps/documents/api.py) and reloads the page; no framework.
// Text only ever reaches the page through textContent, never as HTML.
//
// Loaded once by base.html and bound by delegation on `document`, so it keeps
// working when the documents page arrives through an in-place (htmx) swap:
// a script that bound to the forms present at load time would find none.
(function () {
  "use strict";
  if (window.__elmifyDocuments) { return; }
  window.__elmifyDocuments = true;

  function csrfToken() {
    var tokenInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return tokenInput ? tokenInput.value : "";
  }

  function say(element, text) {
    var out = element.querySelector('[role="status"]') ||
      (element.parentElement && element.parentElement.querySelector('[role="status"]'));
    if (out) { out.textContent = text; }
  }

  // The JSON door's refusal codes (apps/documents/api.py), as a student reads them.
  var REASONS = {
    identity_not_confirmed: "Upload your CV first and confirm the details we read from it. Then we can write your CV.",
    cycle_unpaid: "This needs an active application cycle on your account.",
    application_email_missing: "Add the email address you use for applications first.",
    malformed_content: "Something in your details could not be read. Check them and try again.",
    programme_not_in_pack: "That programme is not in your list.",
    unknown_programme: "That programme is not in your list.",
    rate_limited: "Too many tries. Wait a few minutes and try again.",
    invalid_kind: "Choose what kind of document this is.",
    unsupported_kind: "That kind of document cannot be uploaded here.",
    not_found: "That item no longer exists. Reload the page."
  };
  function reason(data, status) {
    var code = data && data.error;
    return REASONS[code] || ("That did not work (" + (code || status) + ").");
  }

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json()
        .catch(function () { return { error: response.status >= 500 ? "server_error" : response.status }; })
        .then(function (data) { return { status: response.status, data: data }; });
    });
  }

  // ---------- the drop zone: show the chosen file, accept a dropped one ----------
  var ACCEPTED = /\.(pdf|jpe?g|png)$/i;

  function fileType(file) {
    var name = (file && file.name) || "";
    if (/\.pdf$/i.test(name)) { return "PDF"; }
    if (/\.png$/i.test(name)) { return "PNG"; }
    if (/\.jpe?g$/i.test(name)) { return "JPG"; }
    return "FILE";
  }

  function fileSize(bytes) {
    var unit = bytes >= 1048576 ? "MB" : "KB";
    var value = bytes / (unit === "MB" ? 1048576 : 1024);
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value) + " " + unit;
  }

  function showFile(form, file) {
    var row = form.querySelector("[data-file]");
    if (!row) { return; }
    if (!file) { row.hidden = true; return; }
    row.hidden = false;
    row.querySelector("[data-file-type]").textContent = fileType(file);
    row.querySelector("[data-file-name]").textContent = file.name;
    row.querySelector("[data-file-size]").textContent = fileSize(file.size);
    var bar = row.querySelector("[data-progress]");
    if (bar) { bar.hidden = true; bar.value = 0; }
    if (!ACCEPTED.test(file.name)) {
      say(form, "This file type is not accepted. Upload a PDF, JPG or PNG.");
    } else {
      say(form, "");
    }
  }

  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches('form[data-upload] input[type="file"]')) { return; }
    showFile(input.form, input.files[0]);
  });

  function zoneOf(event) {
    return event.target.closest && event.target.closest("[data-dropzone]");
  }
  ["dragenter", "dragover"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      var zone = zoneOf(event);
      if (!zone) { return; }
      event.preventDefault();
      zone.classList.add("is-over");
    });
  });
  ["dragleave", "dragend"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      var zone = zoneOf(event);
      if (zone && !zone.contains(event.relatedTarget)) { zone.classList.remove("is-over"); }
    });
  });
  document.addEventListener("drop", function (event) {
    var zone = zoneOf(event);
    if (!zone) { return; }
    event.preventDefault();
    zone.classList.remove("is-over");
    var files = event.dataTransfer && event.dataTransfer.files;
    if (!files || !files.length) { return; }
    var input = zone.querySelector('input[type="file"]');
    try { input.files = files; } catch (e) { /* older browsers: keep our own copy */ }
    zone.__dropped = files[0];
    showFile(zone.closest("form"), files[0]);
  });

  // The storage POST goes through XMLHttpRequest because fetch reports no
  // upload progress, and the bar is the point of the drop zone.
  function store(url, data, bar) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      if (bar) {
        bar.hidden = false;
        xhr.upload.addEventListener("progress", function (event) {
          if (event.lengthComputable) { bar.value = Math.round((event.loaded / event.total) * 100); }
        });
      }
      xhr.onload = function () { resolve(xhr.status >= 200 && xhr.status < 300); };
      xhr.onerror = function () { reject(new Error("network")); };
      xhr.send(data);
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target.closest && event.target.closest("form[data-upload]");
    if (!form) { return; }
    event.preventDefault();
    var input = form.querySelector('input[type="file"]');
    var zone = form.querySelector("[data-dropzone]");
    var file = (input && input.files[0]) || (zone && zone.__dropped);
    if (!file) { say(form, "Choose a file first."); return; }
    if (!ACCEPTED.test(file.name)) { say(form, "This file type is not accepted. Upload a PDF, JPG or PNG."); return; }
    var picked = form.querySelector('input[name="kind"]:checked') || form.querySelector('select[name="kind"]');
    var kind = picked ? picked.value : "";
    var button = form.querySelector('button[type="submit"]');
    var bar = form.querySelector("[data-progress]");
    if (button) { button.setAttribute("aria-busy", "true"); }
    say(form, "Uploading…");
    function done() { if (button) { button.removeAttribute("aria-busy"); } }
    post(form.dataset.upload, { kind: kind }).then(function (signed) {
      if (signed.status !== 201) {
        done();
        say(form, signed.status >= 500
          ? "Uploads are not available on this server right now. Try again later."
          : reason(signed.data, signed.status));
        return;
      }
      var data = new FormData();
      Object.keys(signed.data.fields).forEach(function (key) { data.append(key, signed.data.fields[key]); });
      data.append("file", file);
      return store(signed.data.url, data, bar).then(function (ok) {
        done();
        say(form, ok ? "Uploaded. We are checking the file; the page refreshes in a moment." : "The file could not be stored. Try again later.");
        if (ok) { setTimeout(function () { window.location.reload(); }, 3000); }
      });
    }).catch(function () {
      done();
      say(form, "The file could not be stored. File storage may not be set up on this server yet.");
    });
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("button[data-api-post]");
    if (!button) { return; }
    var body = button.dataset.body ? JSON.parse(button.dataset.body) : {};
    button.setAttribute("aria-busy", "true");
    say(button, "Working…");
    post(button.dataset.apiPost, body).then(function (result) {
      button.removeAttribute("aria-busy");
      if (result.status < 300) {
        say(button, "Done.");
        setTimeout(function () { window.location.reload(); }, 1500);
      } else if (result.status >= 500) {
        say(button, "That is not available on this server right now. Try again later.");
      } else {
        say(button, reason(result.data, result.status));
      }
    }).catch(function () {
      button.removeAttribute("aria-busy");
      say(button, "That did not work. Try again.");
    });
  });
})();
