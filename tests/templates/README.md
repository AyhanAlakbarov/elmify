# Test-only template stubs

The real `templates/` is rebuilt page by page (student dashboard plan). Nothing
here is a design decision, and none of it ships.

These stubs exist so that view tests can keep asserting **server behaviour** —
MFA enforcement, tenant isolation, authorization, rate limiting, wizard
sequencing — through views that happen to end in a `render()`. Without them
those tests fail on `TemplateDoesNotExist` and the only executable spec of the
server's authorization rules goes red for reasons that have nothing to do with
authorization.

Rules:

* A stub renders nothing, or the least possible. If a test needs specific markup
  to pass, that test is asserting presentation and belongs with the frontend, not
  here — delete it instead of enriching the stub.
* Wired in `config/settings/test.py` only. Production settings never see this
  directory.
* When the real page for a stub lands in `templates/`, delete the stub.

## The frontend tests

`templates/` exists again (2026-10-04, student dashboard). The 12 tests that pinned the
deleted visual layer (htmx vendor file and config meta, `--brand-primary`, component
partial file names, the 5-second poll) were retired in the commit that names each one.
The 28 kept tests assert behaviour the plain pages still owe. A stub here is used only
for a template root `templates/` does not provide yet; each stub is deleted in the task
that builds the real page.
