# In-page guidance vs side panel for a form-filling co-pilot

Date: 2026-10-09. Question: how do products that guide a person through a form on someone else's
website present that guidance, and what works or fails? The answer feeds one decision: should the
university-portal co-pilot (Chrome MV3, fills the student's own tab, student presses Submit) draw on
the portal page, keep the side panel, or combine the two?

## Summary

- **Job-application copilots mostly put a panel or widget inside the employer's page.** Simplify
  opens "the panel from the teal Simplify tab on the right edge of the page"[^1]. JobWizard adds an
  Autofill button to the page and tags every field with its status and source[^20]. Huntr starts from
  the extension widget[^19]. All of them stop before Submit and ask the user to review[^2][^22].
  Fields they can't fill are handed back in a list inside the panel (Simplify's "Application AI
  Question" section[^7]) or with a copy-paste profile view[^9]. None that I found marks the failed
  field on the page itself.
- **The best-documented failure is the injected panel getting in the way.** Simplify's sidebar
  "overlays the next button and blocks progression" on Workday[^11]. Users also ask for a smaller
  trigger because the tab "takes up large space of the screen"[^13]. Workday-specific wrong fills
  show up too: a rejected date[^16] and a degree that was "offset by one"[^17].
- **Writing assistants (Grammarly, LanguageTool) draw underlines on top of the field, not inside
  it.** Grammarly moved its underlines out of the host's DOM because writing into the page could
  "corrupt the user’s text, crash the website’s code"[^24]. Keeping an overlay lined up has no
  browser API and can be expensive[^27][^28]. Grammarly also collapses its own button when it
  overlaps the user's text[^35].
- **Digital-adoption tools (WalkMe, Whatfix, Pendo, Userpilot) find their target element with
  selectors or element fingerprints, and they all document breakage when the page changes.** Their
  fallbacks are: re-select the element, make the step optional, use a modal instead of a tooltip, or
  raise an alert after about 10 s[^42][^50][^51][^52][^53]. Pendo states that its alerts are
  reactive and cannot predict breakage[^43].
- **Research:**
  - Feedback placed next to the field reduces memory load and errors[^54][^58].
  - Push-style tours and coach marks interrupt users and do not improve task performance[^56].
  - One 2026 study (N=94) found in-page highlighting with step-by-step guidance raised multi-step
    completion by 30 percentage points[^59]. It compared against unaided browsing, not against a
    side panel.
  - I found no study that directly compares in-page guidance with a side panel. That comparison
    stays **Unverified**.
- **Recommendation (my inference, not a cited finding): combine the two.** Keep the side panel as
  the persistent record of what was filled, what failed and whose turn it is. Add light marks on the
  portal page, drawn in an overlay outside the portal's DOM:
  - an outline and small badge on filled and failed fields;
  - one "your turn" pointer at a time;
  - never cover Next or Submit.
  When the element can't be found or would be covered, fall back to the panel only.

## Method and sources

- **How the candidate list was built.** Exa `web_search_exa` found Simplify, Teal, Huntr, Jobright,
  LazyApply, JobWizard, JobFill, TryApplyNow and Matatah. Exa `web_search_advanced_exa` with
  `includeDomains` was then run on each owner's domain: simplify.jobs, feedback.simplify.jobs,
  grammarly.com, languagetool.org, support.pendo.io, support.walkme.com, support.whatfix.com,
  docs.userpilot.com and nngroup.com. One Brave `site:reddit.com` search found user threads.
- **Fetching.** Every quote below was fetched live with scrapling `get`/`bulk_get`.
- **Sources I could not reach:**
  - reddit.com returned 403 to scrapling, so the Reddit threads are not cited.
  - chromewebstore.google.com redirected to a Google consent wall, so Chrome Web Store reviews and
    listings are not cited.
  - tryapplynow.com returned HTTP 402.
  - support.walkme.com geo-redirects to its French pages from this network, so WalkMe is cited from
    the French pages with French quotes.
  - Tavily was not used.

## 1. Job-application autofill copilots

### Where the UI lives

- **Simplify Copilot.** A panel opened from a tab docked on the right edge of the employer's
  page[^1]. Review and submit are left to the user[^2]. Simplify defends the larger popup: it "does
  help users double check fields, confirm the selected resume"[^14].
- **Huntr.** The user clicks the extension widget and chooses "Autofill Application"[^19].
- **JobWizard.** Puts an Autofill button on the page, and "Every field shows its status and
  source"[^20]. Each answer is tagged as coming from the resume or drafted by AI[^21].
- **Jobright.** Says its extension "shows exactly which fields are filled before submission"[^23].
  It frames agent-first tools as ones that "often lack transparency about what was submitted and
  why"[^23b]. The claim that Jobright's UI is a sidebar with a green Autofill button comes only from
  a third-party GitHub gist: **Unverified**.
- **Teal.** States users can review and edit before submitting[^22]. I found no first-party
  description of where Teal's autofill UI sits on the page: **Unverified**.
- **LazyApply.** An auto-submit agent: "Our agent handles the entire application process"[^25b]. I
  found no first-party description of its in-page UI: **Unverified**.

### What was filled vs what needs the user

- **Simplify:**
  - Common fields "tend to autofill most reliably"[^3].
  - Essay questions it cannot fill are listed in the panel's "Application AI Question" section[^7].
  - Generated answers are written straight into the page field for review[^8].
  - On unsupported sites, the fallback is a copy-paste Profile tab[^9].
- **Simplify Autopilot** (its auto-submit mode) refuses to guess. It "stops and marks the
  application as failed rather than sending something wrong"[^10].
- **Huntr** fails silently on unsupported pages: "this autofill section will not populate any
  information"[^19b]. It works only when the form is visible on the page[^19c].
- **What none of them do, as far as I found:** no first-party doc in this set describes on-page
  marks such as outlines or badges on failed fields. JobWizard's per-field "status and source" is the
  closest[^20]. Whether that status is drawn on the page or in its sidebar is not stated:
  **Unverified**.

### Multi-page forms, file uploads and CAPTCHAs

- **Multi-page forms.** By default the user clicks Autofill on each page[^5]. An opt-in setting
  continues automatically "until the application is submitted"[^6].
- **Moving to the next page.** Users ask for the page's Next/Submit button inside the extension,
  because they otherwise have to scroll for it[^15]. Simplify says Workday has a "next button" at
  the bottom of its popup[^12].
- **File uploads.** Simplify uploads the default resume into the resume field[^4]. A user reports
  that the bot attached the default resume rather than the tailored one. That report was found via
  Exa and not re-fetched: **Unverified**.
- **CAPTCHAs.** No vendor doc I found describes CAPTCHA handling: **Unverified**.

### Reported failures

- **The panel covers the page's own controls.** "after running autofill the Simplify sidebar
  sometimes overlays the next button and blocks progression."[^11]
- **The panel takes too much space.** The "tab takes up large space of the screen"[^13].
- **Workday rejects the filled values.**
  - A date was refused: "The autofilled date 04/2010 is not accepted by Workday."[^16]
  - The degree was misaligned: "Degree type is offset by one."[^17]
- **Filling too much.** A user had to "go and delete the non-required afterwards"[^18]. Simplify
  replied that "99% of our feature requests are for filling out more fields, not less."[^18b]
- **Reddit reports.** The same themes appear in Reddit snippets, for example "simplify is quick but
  keeps missing fields or breaking on custom forms" in r/cscareerquestions. Reddit blocked the fetch:
  **Unverified**.

## 2. In-page writing assistants (Grammarly, LanguageTool)

### Placement

- **Grammarly:**
  - Its logo sits in the lower-right corner of the focused field[^31].
  - Suggestions appear as underlines in the text, with cards on hover[^33].
  - It skips fields under 38 px tall[^32] and does not work in `<input>` fields[^34].
- **LanguageTool** uses the same model: underlines plus a corner icon. One user says the icon
  "breaks my concentration flow in a way that just having the underlines does not"[^36].

### How the overlay is drawn

- **Grammarly used to wrap text in its own nodes.** That polluted the host's DOM: "it can corrupt the
  user’s text, crash the website’s code"[^24]. Also, "websites don’t like it when somebody tries to
  change their DOM"[^25], and some editors began disabling Grammarly[^30].
- **It moved to a container at the end of the page.** "the underline elements container is the very
  last element of the document body"[^26]. Underlines are positioned from `Range.getClientRects()`.
- **Keeping the overlay aligned costs work.**
  - "there is no API or event to know when these values change"[^27].
  - Polling `getBoundingClientRect` 60 times a second "can easily consume over 90% of CPU on average
    hardware"[^28].
  - Sticky headers can cover the field: it "can also be covered by an element with position: sticky
    style"[^29].
- **Grammarly yields to the user's text.** It checks whether its button overlaps the text and
  collapses it if so[^35]. Its performance work "decreased the number of users disabling the
  extension by 9%"[^35b].

### Documented conflicts

- LanguageTool can be switched off by a page's `spellcheck="false"` attribute[^37].
- On some sites, LanguageTool deletes the misspelled word without inserting the replacement[^38].

## 3. Digital-adoption guidance overlays (WalkMe, Whatfix, Pendo, Userpilot)

### How they find the element

- **Pendo** "uses CSS selectors to attach guides to elements"[^39]. Slow selectors "can cause guide
  display issues or performance problems"[^40].
- **WalkMe:**
  - It identifies elements from several attributes, and each attribute is a way to break.
  - Position changes when the screen size differs: "si votre utilisateur a une taille d'écran
    différente"[^46].
  - Hard-coded text or jQuery selectors break on "le moindre changement"[^47].
  - On Workday, elements change by tenant configuration, role and location[^48].
- **Whatfix** "fails to recognize the right element" when several similar elements exist[^50].
- **Userpilot** "cannot target iframe content"[^52].

### What happens when the page changes

- **The step does not show.**
  - WalkMe: a step will not play if the element is not found[^45].
  - Pendo: an "Element Missing" step "couldn't display"[^41].
- **The tooltip shows in the wrong place.** Whatfix: "The Flow Tooltip appears in an incorrect
  position."[^49]
- **The flow gets stuck.** Userpilot: the step's element is removed from the DOM after a click[^52b].

### Their fallbacks

- **Make the step optional.** Whatfix: "make the step an optional step so the Flow continues"[^51].
- **Use a modal instead of an anchored tooltip.** Userpilot: "Use modal instead of tooltip for
  complex layouts"[^52c].
- **Raise an alert after a timeout.** Both Pendo and Userpilot wait 10 seconds before alerting[^42b][^53].
- **Accept that alerts are reactive.** Pendo: "Alerts are reactive and don't catch guide display
  issues before they occur."[^43]

## 4. Evidence on in-page guidance vs a separate panel

- **Feedback next to the field:**
  - NN/g: "Keeping error messages next to the fields in error minimizes working-memory load"[^54].
  - A summary at the top should not be the only indicator, because "it forces the user to search for
    the field in error"[^55].
  - Wroblewski and Etre (22 users, 6 form variants): participants were "faster, more successful,
    less error-prone, and more satisfied" with inline validation[^58]. Persistent messages did best,
    and "fading messages were also easily missed"[^58b].
  - Caveat: commenters on that article note it was a within-subjects design with a learning-effect
    risk[^58c].
- **Push vs pull guidance (NN/g).**
  - Push tours "interrupt users who are attempting to do something else at that moment"[^56].
  - Clippy failed partly because of a "hard-to-ignore character sitting in the user’s peripheral
    vision"[^56b].
  - A small overlay keeps the instructions next to the work: "it’s much easier for users to switch
    their gaze from the help window to the main area"[^57]. The downside is that "there may be
    elements that users need to access, but get hidden by the window"[^57b].
- **PageGuide (arXiv, 2026, N=94).**
  - It combines in-page highlights with a collapsible side panel and "grounds LLM answers directly in
    the HTML DOM via visual overlays"[^59].
  - Guided "completion rate increases by 30 percentage points"[^59b].
  - The baseline was unaided browsing, so this does not isolate in-page vs panel.
- **No head-to-head study found.** I found no controlled study comparing in-page marks with a side
  panel for completion, trust or error rates on a third-party form: **Unverified / open**. A 1989
  study of full-screen, split-screen and windowed help found no significant performance difference.
  That came from an Exa abstract and was not fetched: **Unverified**.
- **Chrome side-panel constraints.**
  - The side panel gives "persistent experiences that complement the user's browsing journey"[^60].
  - It closes when the user navigates to a site where it is not enabled[^60b].
  - `sidePanel.open()` needs a user gesture[^60c].

## Implications for the portal co-pilot (inference)

1. **Keep the side panel as the ledger.** It survives page navigation, has room for the list of
   failed fields and "your turn" items, and covers no part of the portal. Simplify's main complaint
   is exactly an injected panel covering the page's buttons[^11][^13].
2. **Add on-page marks drawn in your own overlay layer** (shadow root appended to `<body>`), never
   inside the portal's fields, following Grammarly[^24][^26]:
   - an outline or badge on filled and failed fields;
   - one pointer at a time for the current "your turn" step.

   This puts the error next to the field, which is where the research says it belongs[^54][^58].
3. **Design for marks that can't be placed.** Old portals with iframes, tables and sticky headers
   will break anchoring the same way they break DAP selectors[^29][^46][^52]. When an element can't
   be found or would be covered, show the item in the panel only. That is the equivalent of Whatfix's
   optional step or Userpilot's modal-instead-of-tooltip[^51][^52c].
4. **Never cover the portal's own Next or Submit, and collapse marks that overlap user content.**
   Grammarly collapses its button on overlap[^35].

## Open questions

- Is there a controlled study of in-page vs side-panel guidance for third-party form completion,
  trust or error rate? None found.
- How do Teal, Jobright and LazyApply draw their UI on the employer page? Their first-party docs
  don't say, and the Chrome Web Store and Reddit were unreachable.
- How does any job copilot handle CAPTCHAs? No vendor doc found.
- Does JobWizard show per-field status on the page or only in its sidebar?

## Sources

[^1]: https://help.simplify.jobs/articles/2415391-using-copilot-to-autofill-applications "Open the panel from the teal Simplify tab on the right edge of the page."
[^2]: https://help.simplify.jobs/articles/2415391-using-copilot-to-autofill-applications "Review the completed application, make any edits you want, and submit the application yourself."
[^3]: https://help.simplify.jobs/articles/2415391-using-copilot-to-autofill-applications "These are typically the most consistent fields across application systems, which is why they tend to autofill most reliably."
[^4]: https://help.simplify.jobs/articles/2415391-using-copilot-to-autofill-applications "Copilot can upload your default resume directly into the application's resume field."
[^5]: https://help.simplify.jobs/en/articles/8686025-manage-autofill-settings-in-the-simplify-extension "For applications with multiple pages, you must click Autofill on each page."
[^6]: https://help.simplify.jobs/en/articles/8686025-manage-autofill-settings-in-the-simplify-extension "Simplify will continue filling each page automatically until the application is submitted."
[^7]: https://help.simplify.jobs/articles/7306766-answering-essay-questions-with-copilot "questions that cannot be answered through standard autofill appear under the Application AI Question section in the Autofill tab."
[^8]: https://help.simplify.jobs/articles/7306766-answering-essay-questions-with-copilot "Generated answers appear directly in the application field so you can review and edit them before submitting."
[^9]: https://help.simplify.jobs/articles/8717287-autofill-not-supported "the extension’s Profile tab provides a simple copy and paste view of your saved details"
[^10]: https://help.simplify.jobs/articles/4455305-credits-and-failed-applications "it stops and marks the application as failed rather than sending something wrong."
[^11]: https://feedback.simplify.jobs/p/next-button-gets-blocked-by-sidebar "after running autofill the Simplify sidebar sometimes overlays the next button and blocks progression."
[^12]: https://feedback.simplify.jobs/p/next-button-gets-blocked-by-sidebar "there should be a “next button” at the bottom of our autofill popup."
[^13]: https://feedback.simplify.jobs/p/button-for-one-click-fill "tab takes up large space of the screen and I just want a one click button that fills the application out"
[^14]: https://feedback.simplify.jobs/p/button-for-one-click-fill "the popup does help users double check fields, confirm the selected resume"
[^15]: https://feedback.simplify.jobs/p/submit-next-button-in-the-extension "I have to scroll to the bottom and find the next/submit button on the job application page."
[^16]: https://feedback.simplify.jobs/p/workday-date-not-accepted "The autofilled date 04/2010 is not accepted by Workday."
[^17]: https://feedback.simplify.jobs/p/workday-education-fill "education isn't autofilling degree and field of study properly. Degree type is offset by one."
[^18]: https://feedback.simplify.jobs/p/fill-in-required-field-only "I have to go and delete the non-required afterwards"
[^18b]: https://feedback.simplify.jobs/p/fill-in-required-field-only "99% of our feature requests are for filling out more fields, not less."
[^19]: https://help.huntr.co/en/articles/9859408-the-huntr-chrome-extension "on extension widget and choose Autofill Application"
[^19b]: https://help.huntr.co/en/articles/9859408-the-huntr-chrome-extension "When a job site does not allow our extension, this autofill section will not populate any information."
[^19c]: https://help.huntr.co/en/articles/9859408-the-huntr-chrome-extension "Our Autofill function only works on pages where the application form is visible."
[^20]: https://jobwizard.ai/features/smart-autofill "Every field shows its status and source."
[^21]: https://jobwizard.ai/features/smart-autofill "each tagged so you know whether it came straight from your resume or was drafted by AI."
[^22]: https://www.tealhq.com/tools/autofill-job-applications "you always have the option to review and edit your responses before submitting."
[^23]: https://jobright.ai/blog/do-ai-job-application-tools-actually-help-why-jobright-is-built-for-results/ "shows exactly which fields are filled before submission."
[^23b]: https://jobright.ai/blog/do-ai-job-application-tools-actually-help-why-jobright-is-built-for-results/ "They scale quickly but often lack transparency about what was submitted and why."
[^25b]: https://lazyapply.com/ "Our agent handles the entire application process."
[^24]: https://www.grammarly.com/blog/engineering/making-grammarly-feel-native-on-every-website/ "it can corrupt the user’s text, crash the website’s code"
[^25]: https://www.grammarly.com/blog/engineering/making-grammarly-feel-native-on-every-website/ "websites don’t like it when somebody tries to change their DOM."
[^26]: https://www.grammarly.com/blog/engineering/making-grammarly-feel-native-on-every-website/ "Note how the underline elements container is the very last element of the document body."
[^27]: https://www.grammarly.com/blog/engineering/making-grammarly-feel-native-on-every-website/ "there is no API or event to know when these values change"
[^28]: https://www.grammarly.com/blog/engineering/making-grammarly-feel-native-on-every-website/ "it can easily consume over 90% of CPU on average hardware."
[^29]: https://www.grammarly.com/blog/engineering/making-grammarly-feel-native-on-every-website/ "It can also be covered by an element with position: sticky style."
[^30]: https://www.grammarly.com/blog/engineering/making-grammarly-feel-native-on-every-website/ "So both website and text editor developers started to look for ways to disable Grammarly"
[^31]: https://support.grammarly.com/hc/en-us/articles/115000091592-Grammarly-s-browser-extension-user-guide "When you click into a text field, you should see Grammarly’s logo in the lower-right corner."
[^32]: https://support.grammarly.com/hc/en-us/articles/115000091592-Grammarly-s-browser-extension-user-guide "Grammarly does not initialize in text areas smaller than 38 pixels in height."
[^33]: https://support.grammarly.com/hc/en-us/articles/115000091592-Grammarly-s-browser-extension-user-guide "Some of our suggestions appear as underlines directly in the text."
[^34]: https://support.grammarly.com/hc/en-us/articles/10139846131213-How-do-I-integrate-Grammarly-with-my-website-or-application "Grammarly doesn't work in input fields."
[^35]: https://www.grammarly.com/blog/engineering/reducing-text-input-lag/ "we computed whether the Grammarly button overlaps with the user’s text. If yes, we collapsed the Grammarly button."
[^35b]: https://www.grammarly.com/blog/engineering/reducing-text-input-lag/ "this work also decreased the number of users disabling the extension by 9%"
[^36]: https://forum.languagetool.org/t/hiding-languagetool-icon-in-text-areas/11888 "I find it distracting and it breaks my concentration flow in a way that just having the underlines does not."
[^37]: https://forum.languagetool.org/t/lt-extension-for-chrome-edge-doesnt-work-on-my-web-site/7772 "attribute? That might turn off LanguageTool."
[^38]: https://forum.languagetool.org/t/lt-deletes-underlined-words-on-certain-websites/8956 "LT deletes the incorrect word without replacing it. Only on certain websites."
[^39]: https://support.pendo.io/hc/en-us/articles/28618614571547-Use-CSS-rules-for-guide-targeting "Pendo uses CSS selectors to attach guides to elements on a web application page."
[^40]: https://support.pendo.io/hc/en-us/articles/28618614571547-Use-CSS-rules-for-guide-targeting "Too many slow selectors can cause guide display issues or performance problems within your application."
[^41]: https://support.pendo.io/hc/en-us/articles/4405636975643-Guide-display-alerts "The guide step couldn't display because the target element selected in Location settings for the guide step wasn't present"
[^42]: https://support.pendo.io/hc/en-us/articles/4405636975643-Guide-display-alerts "A guide might not display as expected or stop displaying entirely for a variety of reasons, such as changes to your application"
[^42b]: https://support.pendo.io/hc/en-us/articles/4405636975643-Guide-display-alerts "controls how much time should elapse before a display alert is triggered. The default time is 10 seconds."
[^43]: https://support.pendo.io/hc/en-us/articles/4405636975643-Guide-display-alerts "Alerts are reactive and don't catch guide display issues before they occur."
[^45]: https://support.walkme.com/fr/knowledge-base/walkme-ne-peut-pas-trouver-delement-sur-la-page/ "Souvent, une étape ne se lit pas ou un launcher n'apparaît pas sur la page si WalkMe ne peut pas trouver l'élément."
[^46]: https://support.walkme.com/fr/knowledge-base/walkme-ne-peut-pas-trouver-delement-sur-la-page/ "Cela peut se produire si votre utilisateur a une taille d'écran différente et si l'élément apparaît à un endroit différent."
[^47]: https://support.walkme.com/fr/knowledge-base/aide-au-depannage-de-base-pour-trouver-un-element/ "le moindre changement peut rompre la configuration en raison de sa nature codée en dur"
[^48]: https://support.walkme.com/fr/knowledge-base/workday-walkme-app-ne-trouve-pas-lelement-correct-ou-pas-delement-du-tout-problemes-de-recherche-delements/ "Les éléments peuvent également changer en fonction de la configuration des utilisateurs ou de la variation du processus par rôle ou par emplacement."
[^49]: https://support.whatfix.com/docs/flow-does-not-run-correctly "The Flow Tooltip appears in an incorrect position."
[^50]: https://support.whatfix.com/docs/flow-couldnt-detect-the-element-for-the-next-step "If there are multiple similar elements on the application, Whatfix fails to recognize the right element."
[^51]: https://support.whatfix.com/docs/flow-couldnt-detect-the-element-for-the-next-step "make the step an optional step so the Flow continues even when the element is already selected or unavailable."
[^52]: https://docs.userpilot.com/reference/errors "Userpilot cannot target iframe content"
[^52b]: https://docs.userpilot.com/reference/errors "Element removed from DOM after click"
[^52c]: https://docs.userpilot.com/reference/errors "Use modal instead of tooltip for complex layouts"
[^53]: https://docs.userpilot.com/navigation-and-interface/inbox "Userpilot waits 10 seconds by default before triggering an alert"
[^54]: https://www.nngroup.com/articles/errors-forms-design-guidelines/ "Keeping error messages next to the fields in error minimizes working-memory load"
[^55]: https://www.nngroup.com/articles/errors-forms-design-guidelines/ "it forces the user to search for the field in error"
[^56]: https://www.nngroup.com/articles/onboarding-tutorials/ "they interrupt users who are attempting to do something else at that moment"
[^56b]: https://www.nngroup.com/articles/onboarding-tutorials/ "the annoying animated, hard-to-ignore character sitting in the user’s peripheral vision"
[^57]: https://www.nngroup.com/articles/pop-up-adaptive-help/ "it’s much easier for users to switch their gaze from the help window to the main area, than it is to toggle between pages."
[^57b]: https://www.nngroup.com/articles/pop-up-adaptive-help/ "there may be elements that users need to access, but get hidden by the window."
[^58]: https://alistapart.com/article/inline-validation-in-web-forms/ "Our participants were faster, more successful, less error-prone, and more satisfied when they used the forms with inline validation."
[^58b]: https://alistapart.com/article/inline-validation-in-web-forms/ "fading messages were also easily missed"
[^58c]: https://alistapart.com/article/inline-validation-in-web-forms/ "No amount of randomisation will control this bias. It needs a between subjects design."
[^59]: https://arxiv.org/html/2604.23772v2 "grounds LLM answers directly in the HTML DOM via visual overlays"
[^59b]: https://arxiv.org/html/2604.23772v2 "completion rate increases by 30 percentage points"
[^60]: https://developer.chrome.com/docs/extensions/reference/api/sidePanel "enabling persistent experiences that complement the user's browsing journey."
[^60b]: https://developer.chrome.com/docs/extensions/reference/api/sidePanel "When the user navigates to a site where the side panel is not enabled, the side panel will close"
[^60c]: https://developer.chrome.com/docs/extensions/reference/api/sidePanel "It allows extensions to open the side panel through an extension user gesture"
