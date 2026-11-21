# Portal test bench

Verifies a portal form's field map against a recorded walk of the real application, then promotes
it so every tenant is served the verified map. Operator-run; the command is
`apps/portals/management/commands/portal_bench.py`. `<form>` is the PortalForm id, `<email>` the
bench operator's email.

## Never

- Never create a sample-student account on a live portal.
- Never press Next or Submit on a live portal. Stop before Submit on the last page.

## Procedure

1. Sign in to the platform dashboard (MFA) and click the toolbar button to pair the extension to
   the operator account.
2. `uv run python manage.py portal_bench --operator <email> --queue` lists what to walk:
   unverified forms students use, and changed ones.
3. Walk the real application in the owner's own portal account, in the paired dashboard tab.
   On every page press "Record this page" (the SIGNUP page with its password rules as the portal
   states them). Stop before Submit. A login on a host other than the form's (SSO) cannot be
   recorded yet. Record BOTH a LOGIN page and a SIGNUP page (with its password rules): promotion
   refuses without either.
   The first walk is also where the side panel's behaviour in branded Chrome is confirmed: ruling
   #6 was measured only in headless Chromium.
4. Both the LOGIN and the SIGNUP page must have been recorded in step 3. Once they behaved as
   spec section 6 says, mark each (SIGNUP marks the newest page that has password rules):
   `portal_bench <form> --operator <email> --walk-ok LOGIN` and `--walk-ok SIGNUP`.
5. `portal_bench <form> --operator <email>` replays the walk offline. Exit 1 means not clean. Set
   the rules it suggests (`value_formats`, `option_synonyms`, `readback_equivalences`, set from the
   Django shell: PortalForm has no admin registration) or correct the map, and re-run until CLEAN.
   The command never writes a rule.
   The saved copies replay offline only, served under a no-script CSP (the `--wording` copies
   carry the same policy inline): a portal's own scripts never run, so
   portal-side transforms (uppercasing, reformatting a date) are taught by hand from the live
   walk, not suggested.
6. `portal_bench <form> --operator <email> --wording out.html`, then read every message in all
   four languages against each recorded page.
7. Every replay prints the map row by row (`field -> box [heading / label / context on your
   walk]`) and a mapping digest. Check each row against the real portal: a clean replay cannot
   see a box that asks for something else, because it reads back the box it typed into. Then
   `portal_bench <form> --operator <email> --promote --confirm <digest>` (refused unless the
   replay is clean and the digest is this map's). The map becomes the verified one (`verified_at`).
8. To start a portal's walk afresh: `portal_bench <form> --operator <email> --new-walk`.

## Retention

Recordings (`PageRecord`, bench HTML) are kept and never served to a tenant view (owner,
2026-10-09). A live relearn over a verified map marks the form `needs_bench`; it reappears in
`--queue`.
