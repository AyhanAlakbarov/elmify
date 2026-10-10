// The documents page's one script (dashboard spec §6). It calls the existing
// JSON door (apps/documents/api.py) and reloads the page; no framework.
// Text only ever reaches the page through textContent, never as HTML.
(function () {
  "use strict";
  var tokenInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
  var csrf = tokenInput ? tokenInput.value : "";

  function say(element, text) {
    var out = element.querySelector('[role="status"]') ||
      (element.parentElement && element.parentElement.querySelector('[role="status"]'));
    if (out) { out.textContent = text; }
  }

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().then(function (data) { return { status: response.status, data: data }; });
    });
  }

  document.querySelectorAll("form[data-upload]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var file = form.querySelector('input[type="file"]').files[0];
      if (!file) { say(form, "Choose a file first."); return; }
      var kind = form.querySelector('select[name="kind"]').value;
      say(form, "Uploading…");
      post(form.dataset.upload, { kind: kind }).then(function (signed) {
        if (signed.status !== 201) { say(form, "Upload refused: " + (signed.data.error || signed.status)); return; }
        var data = new FormData();
        Object.keys(signed.data.fields).forEach(function (key) { data.append(key, signed.data.fields[key]); });
        data.append("file", file);
        return fetch(signed.data.url, { method: "POST", body: data }).then(function (put) {
          say(form, put.ok ? "Uploaded. We are checking the file; the page will refresh." : "Upload failed. Try again.");
          if (put.ok) { setTimeout(function () { window.location.reload(); }, 4000); }
        });
      }).catch(function () { say(form, "Upload failed. Try again."); });
    });
  });

  document.querySelectorAll("button[data-api-post]").forEach(function (button) {
    button.addEventListener("click", function () {
      var body = button.dataset.body ? JSON.parse(button.dataset.body) : {};
      post(button.dataset.apiPost, body).then(function (result) {
        if (result.status < 300) {
          say(button, "Done.");
          setTimeout(function () { window.location.reload(); }, 1500);
        } else {
          say(button, "Refused: " + (result.data.error || result.status));
        }
      }).catch(function () { say(button, "That did not work. Try again."); });
    });
  });
})();
