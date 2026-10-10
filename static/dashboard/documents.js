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

  document.addEventListener("submit", function (event) {
    var form = event.target.closest && event.target.closest("form[data-upload]");
    if (!form) { return; }
    event.preventDefault();
    (function () {
      var file = form.querySelector('input[type="file"]').files[0];
      if (!file) { say(form, "Choose a file first."); return; }
      var kind = form.querySelector('select[name="kind"]').value;
      say(form, "Uploading…");
      post(form.dataset.upload, { kind: kind }).then(function (signed) {
        if (signed.status !== 201) {
          say(form, signed.status >= 500
            ? "Uploads are not available on this server right now. Try again later."
            : reason(signed.data, signed.status));
          return;
        }
        var data = new FormData();
        Object.keys(signed.data.fields).forEach(function (key) { data.append(key, signed.data.fields[key]); });
        data.append("file", file);
        return fetch(signed.data.url, { method: "POST", body: data }).then(function (put) {
          say(form, put.ok ? "Uploaded. We are checking the file; the page will refresh." : "The file could not be stored. Try again later.");
          if (put.ok) { setTimeout(function () { window.location.reload(); }, 4000); }
        });
      }).catch(function () { say(form, "The file could not be stored. File storage may not be set up on this server yet."); });
    })();
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("button[data-api-post]");
    if (!button) { return; }
    (function () {
      var body = button.dataset.body ? JSON.parse(button.dataset.body) : {};
      post(button.dataset.apiPost, body).then(function (result) {
        if (result.status < 300) {
          say(button, "Done.");
          setTimeout(function () { window.location.reload(); }, 1500);
        } else if (result.status >= 500) {
          say(button, "That is not available on this server right now. Try again later.");
        } else {
          say(button, reason(result.data, result.status));
        }
      }).catch(function () { say(button, "That did not work. Try again."); });
    })();
  });
})();
