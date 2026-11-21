// Interactive presets for student profile consultation wizard.
// Handles country, language, interest, test, intake, and amount presets without inline handlers.
(function () {
  "use strict";

  function handleMultiTicks(cb, caseInsensitive) {
    var el = document.getElementById("id_value");
    if (!el) return;
    var parts = el.value
      .split(",")
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
    if (cb.checked) {
      if (parts.indexOf(cb.value) === -1) {
        parts.push(cb.value);
      }
    } else {
      parts = parts.filter(function (p) {
        if (caseInsensitive === "upper") {
          return p.toUpperCase() !== cb.value.toUpperCase();
        }
        return p.toLowerCase() !== cb.value.toLowerCase();
      });
    }
    el.value = parts.join(", ");
  }

  function handleLanguageQuickPreset(value) {
    if (value === "NONE") {
      for (var i = 0; i < 12; i++) {
        var el = document.getElementById("id_value_" + i);
        if (el) el.value = "";
      }
      return;
    }
    var l = document.getElementById("id_value_0");
    var s = document.getElementById("id_value_1");
    var t = document.getElementById("id_value_2");
    var d = document.getElementById("id_value_3");
    if (d && !d.value) {
      d.value = new Date().toISOString().slice(0, 10);
    }
    if (value === "IELTS") {
      if (l) l.value = "English";
      if (t) t.value = "TEST";
      if (s) {
        if (!s.value || s.value.indexOf("IELTS") === -1) s.value = "IELTS 7.0";
        s.focus();
      }
    } else if (value === "TOEFL") {
      if (l) l.value = "English";
      if (t) t.value = "TEST";
      if (s) {
        if (!s.value || s.value.indexOf("TOEFL") === -1) s.value = "TOEFL 100";
        s.focus();
      }
    } else if (value === "DUOLINGO") {
      if (l) l.value = "English";
      if (t) t.value = "TEST";
      if (s) {
        if (!s.value || s.value.indexOf("Duolingo") === -1) s.value = "Duolingo 125";
        s.focus();
      }
    } else if (value === "TESTDAF") {
      if (l) l.value = "German";
      if (t) t.value = "TEST";
      if (s) {
        if (!s.value || s.value.indexOf("TestDaF") === -1) s.value = "TestDaF TDN 4";
        s.focus();
      }
    }
  }

  function handleIntakePreset(value) {
    var el = document.getElementById("id_value");
    if (el) {
      el.value = value;
    }
  }

  function handleAmountPreset(value) {
    var el = document.getElementById("id_value_0") || document.getElementById("id_value_amount");
    if (el) {
      el.value = value === "NONE" ? "" : value;
    }
  }

  document.addEventListener("change", function (event) {
    var target = event.target;
    if (!target) return;
    if (target.name === "country_ticks") {
      handleMultiTicks(target, "upper");
    } else if (
      target.name === "language_ticks" ||
      target.name === "interest_ticks" ||
      target.name === "duration_tick" ||
      target.name === "priority_ticks"
    ) {
      handleMultiTicks(target, "lower");
    } else if (target.name === "language_quick_preset") {
      handleLanguageQuickPreset(target.value);
    } else if (target.name === "intake_preset") {
      handleIntakePreset(target.value);
    } else if (target.name === "amount_preset") {
      handleAmountPreset(target.value);
    }
  });

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target) return;
    if (target.name === "language_quick_preset") {
      handleLanguageQuickPreset(target.value);
    } else if (target.name === "intake_preset") {
      handleIntakePreset(target.value);
    } else if (target.name === "amount_preset") {
      handleAmountPreset(target.value);
    }
  });
})();
