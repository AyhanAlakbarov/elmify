# Programme lanes, money, documents and referees

A student applies for a programme and for the money that pays for it. This spec says how the
dashboard shows the two together, how it keeps a funding-dependent student from spending a fee in
vain, and how documents and reference letters are asked for once and used everywhere.

It is the consumer side of the application-route catalogue. Branch `claude/lanes-and-money-design`,
off master `70848a31`.

## 0. What governs

| Source | What it settles |
|---|---|
| `phased requirements.md` P1-6, P1-7, P1-8, P1-11, §5.3 | Funding-first ranking, the pack and its approved application budget, reject and replace, and never publishing a replacement that fails the gates. §5.3: the student pays every fee, which is shown before they commit. |
| `docs/superpowers/specs/2026-10-04-student-dashboard-design.md` (merged, PR #178) | The board, Needs you now, the cards, the trust rule for mail, the counsellor board and the tenant-copy pattern (`RecommendationCandidate` copies). This spec changes the board's structure and extends the rest. |
| `docs/superpowers/specs/2026-09-27-verified-catalog-one-reader-design.md` §3.4 (branch `claude/verified-catalog-design`, commit `42e5ea99`) | **Application routes**: `funding.ApplicationRoute`, `RouteStep`, `RouteDate` and `research.ApplicationSystem`. They are extracted and certified on the catalogue engine. Only `SERVED` routes reach a student, copied into `portals.Application.route_snapshot`. |
| Same spec, §5.2 | Award facts this spec reads:<br>• `route` (the `_Route` list in `apps/research/funding_judge.py`) and `route_order` (`before_admission` / `after_admission` / `parallel`);<br>• `date_role=results_announced` and `fee_deadline`;<br>• `pays=application_fee`, `duration` and `renewal_condition`. |
| Requirement reader, PR #185 (elmify-f3) | `funding.Program.referee_requirements`: typed reference-letter facts (`count`, `kind`, `mode`, `institutional_email_required`, `due`), each with its verbatim sentence. A field with no record was not stated. |
| Owner decisions, 2026-10-06 to 2026-10-09 (this design session) | Everything in §2–§13 marked *owner*. |
| Owner decisions, 2026-10-10 (card content) | §5.1: how to apply is never shown to the student, anywhere. The extension guides every portal step; applying needs the extension. The Application Kit is no longer the student's: it survives only as "Answers we'll submit", a read-only debugging page for the assigned counsellor, invisible (404) to everyone else and never a gate on applying. |
| `docs/superpowers/specs/2026-09-25-tailored-programme-finding-design.md` T15, §4.3, §4.4, §5.1–§5.3 | "Why it fits you", the requirements with their status, the risk label, and the borderline credit count. §5.1 shows them; it does not redefine them. |
| Verified-catalog spec §0.10, §3.1, §3.2, §5.2, §5.5 | Verified-only display; the one-tap "Does this apply to you?"; EMJM tracks and their mobility paths; the scholarship fact list; an unsure fact is never shown as a guess or as "not stated". |
| Co-pilot on-page guidance spec D2, §3 (approved 2026-10-09) | "Apply to <programme>" opens the portal page; filling starts from the extension's panel. |
| Funding-search-engine master spec §9.2, decision 39 | A nomination award names whom to write to, with a drafted email (§5.1: a Needs-you-now task). |

**Not in scope:**
- extracting routes, awards or referee facts (the three readers above own that);
- visual design and CSS (the dashboard is plain HTML until designers take over);
- the extension's own handling of START_FILL / OPEN_UPLOAD_PAGE (spec B);
- costs other than application fees (owner: "not our problem").

## 1. The rules in one screen

1. **One lane per programme.** A lane holds the programme's application card, plus a card for every award the student applies for separately.
2. **Awards with no separate application are lines, not cards.** That covers awards that are automatic, considered with admission, nominated by the university, or combined with the programme application.
3. **Separate awards the student is eligible for are added automatically** when the programme is added (*owner*). An award that hinges on a fact the profile doesn't hold asks "Does this apply to you?"; nothing else is suggested (§4.3, amended 2026-10-10).
4. **A fee is held automatically** when a funding result arrives before the fee is due, for a student whose attendance depends on funding (*owner*). "Apply now anyway" releases it, and only the student can press it.
5. **Only the student sets the application budget** (*owner*), as a plan plus an optional extra for exceptional opportunities (§7.7). A counsellor sees both but cannot change or propose them.
6. **Money is shown in the original currency, then "≈ AZN".** Totals and the budget are in AZN (*owner*).
7. **Documents are asked once and used everywhere.** Each has a "needed by" date.
8. **Reference letters are planned around each professor's agreed number of requests.** A letter for the professor's signature is generated when the professor asks for one (*owner*, option C).
9. **Scholarship scams and agents are never shown** (*owner*). A programme reachable only through an agent has no route.
10. **No family view** (*owner*).
11. **How to apply is never shown** (*owner*, 2026-10-10): no application steps or portal instructions on the card, the programme page or the kit. The extension guides the student through every portal step (§5.1).

## 2. How each award attaches to a programme

The award's `route` (§5.2) decides what the student sees.

| `route` | What the student does | On the board |
|---|---|---|
| `AUTOMATIC_ON_ADMISSION` | nothing | a line on the programme card: "Considered automatically — nothing to do" |
| `CONSIDERED_WITH_ADMISSION` | nothing extra, or a box or section in the same form | a line: "Considered with your application — nothing extra to submit". When the quote names a box or section, the extension ticks it, or points to it in its panel; the student never reads it as an instruction (rule 11). |
| `INSTITUTION_NOMINATES` | nothing, or ask the university to nominate | a line: "Nominated by the university". When the page names whom to ask, the line gives that contact and its internal deadline, and the request becomes a Needs-you-now item with a drafted email (§5.1). |
| `JOINT_SELECTION`, or the programme's route `kind = COMBINED_WITH_AWARD` | one application covers place and award | **one card**: "Programme + scholarship, one application". Its outcome has two parts (§6). |
| `STUDENT_APPLIES_SEPARATELY`, `HOME_GOVERNMENT_NOMINATES` | a separate application, often on a `SCHOLARSHIP` system | **its own card** in the programme's lane, linked with its `route_order` (§4) |
| `UNSTATED` | unknown | a line: "How to apply for this is not stated — see its official page", linking the source |

**An award covering several programmes** (Chevening's choices, DAAD EPOS, GKS) gets its **own lane**, named for the award. That lane lists its programmes as links, and each programme's lane carries one line: "Also funded by your Chevening application". The award appears once.

## 3. What the tenant side stores

The web tier reads tenant tables only, as the dashboard spec requires. The worker writes every catalogue copy.

### 3.1 Copies written by the worker

- **`portals.Application.route_snapshot`**: §3.4's copy at add time, holding steps, dates (with time zone), fees, portal URLs, each quote and each source URL. The route chosen is the one whose `audience` matches the student's nationality (§9.6). The steps feed the deadlines, the fee, the kit and the extension; they are never listed on the card or the programme page (rule 11).
- **Re-copy.** When the catalogue route changes (a new `SERVED` version), the worker re-copies the snapshot for every application that hasn't started that step. A step already started keeps its copy. The student gets one message: "KTH changed its deadline to 20 Jan". Only the worker writes; the web tier never reads the catalogue route.
- **Referee facts.** `RecommendationCandidate` gains `referee_requirements`, copied from `Program.referee_requirements` in `_publish`, as with the other candidate copies.
- **Award facts on award candidates.** `route`, `route_order`, `results_date`, `fee_amount` / `fee_currency` / `fee_deadline`, `duration` and `renewal_condition`, each with its quote. They're copied into `funding_card`.

### 3.2 New and changed fields

| Model | Field | Meaning |
|---|---|---|
| `portals.Application` | `funding_outcome` | Funding outcome of a combined application: `AWARDED`, `AWARDED_CONDITIONAL`, `RESERVE`, `NOT_AWARDED`, or blank. The place outcome stays in `outcome`. |
| | `fee_state` | `NONE` (no fee), `UNKNOWN`, `OPEN`, `HELD`, `RELEASED` (the student pressed "Apply now anyway"), `PAID`, `SKIPPED` |
| | `fee_held_until` | The last safe day (§7.3) |
| | `fee_paid_at`, `fee_paid_source` | `STUDENT` or `MAIL` (a receipt email recognised) |
| | `step_progress` | Per-step state for multi-step routes: position → `NOT_STARTED` / `STARTED` / `DONE` |
| | `acceptance_deadline`, `deposit_amount`, `deposit_currency` | Taken from the offer email or entered by the student |
| | `round_rank` | The student's rank inside a national round (§8). Blank outside rounds. |
| `portals.ApplicationLink` (new, tenant) | `from_app`, `to_app`, `order` | `order` is `WAITS_FOR` (`from_app` can't proceed until `to_app` has its outcome), `PARALLEL` or `LINKED_ONLY`. A unique pair. A composite `(tenant_id, …)` guard on both FKs, as with every tenant→tenant FK. |
| `documents.Referee` (new, tenant) | `student`, `name`, `title`, `institution`, `email`, `institutional_email`, `kind` (`ACADEMIC` / `PROFESSIONAL`), `relationship`, `agreed_requests`, `gives_generic_letter`, `status` (`ACTIVE` / `DECLINED` / `SILENT`) | One professor. Third-party personal data: minimal, and erased with the student. `kind` is what lets a programme's required kind be met; `SILENT` is a professor who stopped answering, planned around like `DECLINED`. |
| `documents.RefereeRequest` (new, tenant) | `referee`, `application`, `mode`, `state` | `mode` is the referee mode copied from the requirement. `state` is `PROPOSED`, `ASKED`, `AGREED`, `DECLINED`, `SUBMITTED`. |
| `privacy` consent | a new purpose `OUTCOME_LEARNING` | Asked once, at the student's first outcome. Without it, outcomes still drive the board but are never used for learning (§12). |

**Never stored:**
- **the money line:** computed from the cards on every view, so it can't drift;
- **the document list:** computed from the cards and uploads;
- **round groups:** computed from the snapshots' `portal_system`.

The budget stays in the profile (`application_budget: Money`), joined by the optional `budget_stretch: Money | None` (§7.7).

Every new field is classified in `apps/audit/redaction.py`.

## 4. Adding a programme

1. **Read the copied facts.** The student (or counsellor) presses Add. The worker copies the route snapshot and the award facts.
2. **Pick the route.**
   - **A `SERVED` route matches the student's audience:** the card gets the route copy, and "Apply to <programme>" opens the portal of the first step not `DONE` (§5.1).
   - **None matches:** the card shows "Open programme page", and the counsellor portal task stays as the fallback.
3. **For each award linked to the programme (§2):**
   - **A separate award the student is confirmed eligible for:** its card is **added automatically**, linked by `ApplicationLink`. A Remove link sits on the card.
   - **Eligibility depends on a fact the profile doesn't hold** (a special group, for example): a line asking "Does this apply to you?" with the funder's sentence (verified-catalog §3.1). Yes adds the card as above. Nothing else is suggested: an award is shown only when the student is eligible on verified facts (verified-catalog §0.10, amended 2026-10-10).
   - **Not a separate application:** a line on the programme card.
4. **Link order** comes from `route_order`:
   - `after_admission`: the award card `WAITS_FOR` the programme card;
   - `before_admission`: the programme card `WAITS_FOR` the award card;
   - `parallel`: `PARALLEL`, no waiting.
5. **Add the documents and referees.** Their needs join the student's document list and referee plan (§10, §11).

Task 9's refusal of a "comes with admission" award stays: it is a line, never a card.

## 5. The board

No styling, only structure.

- **Needs you now** stays on top: one list across all lanes, sorted by **start-by date** (§9.1). Focus mode (*owner*) shows the next 14 days first, with "Show all" one click away.
- **Lanes**, nearest start-by date first. Each lane has:
  - **a title** in the student's words: "KTH — MSc Computer Science (Sweden)";
  - **one status sentence**, for example "Applied — decision expected in April";
  - **one money line** (§7.5), with a renewal flag when one applies (§9.5);
  - **its cards**, each in its own state column (To start, In progress, Submitted, Confirmed, Decision). The columns stay; lanes are rows across them.
- **The Done section:** a finished lane (rejected, withdrawn, or another offer accepted) moves there with a one-line result: "Admitted · SI scholarship won · €0 left to pay".
- **The programme page:** a lane opens one page holding everything for that programme (§5.1).
- **Words** are the student's: Scholarship, Tuition waiver, Discount, Assistantship. Never "award", "HOLDER", "scope" or the route codes.
- **Programmes & funding** (the pack before anything is added) keeps the dashboard spec's grouping under the funding (§5 there): a country-wide scholarship heads "Eligible programmes in <country>". Each row there carries the same "why it fits you" and risk label as the programme page.

### 5.1 What the card and the programme page show (*owner*, 2026-10-10)

The student sees what to decide and by when. How to apply is the extension's job and is never shown on the dashboard (rule 11).

**The card** (in its lane):
- the title, the status sentence and the next deadline in both time zones (§9.2);
- the fee position line (§7.1) and any warning: country notice (§13a), renewal (§9.5);
- readiness and mail badges, as in the dashboard spec §4;
- one button, **"Apply to <programme>"** (below).

**The programme page:**
- **Why it fits you:** the plain reason, built from facts (tailored spec T15), with its weaknesses named (P1-6, P1-7) and the risk label Safe, Target or Reach (tailored §5.2). "Your best funded chance" when nothing is safe (§5.3 there).
- **Requirements, each with its status:**
  - **which requirements:** subject credits ("20 ECTS in theoretical computer science"), the grade bar beside the student's own grade in its own scale, nationality and degree stage, language and the teaching language, required documents (§10), referees (§11.1);
  - **Met.**
  - **Still to do:** a requirement the student can still meet, with its date: "Needs IELTS 6.5 by 15 Jan". No test fee is shown (§10).
  - **Nearly met:** only for a borderline credit count, shown as a range: "We counted 18–22 of the required 20". Never for a fixed fact (nationality, a degree held, a grade awarded), which is met or not.
  - Every credit status carries "Our count is our estimate, never the university's decision" (tailored §4.4).
- **Money:** the application fee (original currency, then ≈ AZN, §7.6) with its position (§7.1), and the lane money line: tuition, duration, and what's left after funding won (§7.5).
- **Deadlines**, by §9: the one that counts, both time zones, rolling and decentralised wording, "Closed for this intake". **A pre-check** (uni-assist) is its own earlier deadline: "uni-assist check: send by 15 Jan". It is a date, not an instruction.
- **Funding:** every award line (§2), and for each scholarship its deadline and details from verified-catalog §5.2: the amount (and any "up to"), what it covers and any extras, how long it pays, renewal, obligations (for example a return-home bond), and "check with the funder" when its rules are silent on combining it with other funding. A fact still unsure is never shown as a guess or as "not stated" (verified-catalog §5.5).
- **An EMJM:** each track with its full path (semester or year, university, country), its specialisation, and which universities award the degree (verified-catalog §3.2).
- **Official source · last checked <date>** for the programme and for each scholarship (dashboard spec §5).
- the country notice's full text (§13a); its documents and its awards' documents; mail about it; and its referee requests.

**Never on the card or the page:** application steps, portal instructions, or which box to tick.

**Steps stay internal.** The route's steps live in `route_snapshot` and drive the deadlines, the fee and the extension, which takes the student through them in order (uni-assist first, then the university's portal, then the scholarship's portal). No page lists them.

**"Apply to <programme>"** (guidance spec D2, §3) opens the portal page of the first step not `DONE`. Filling starts from the extension's panel ("Start filling"). **The extension is required to apply.** Without it, the button is replaced by "Install the extension to apply"; in another browser, "Open this in Chrome or Edge to apply"; on a phone, "Open this on a computer to apply". This supersedes glass-box decision 12's by-hand fallback. The counsellor is never offered it. A held fee hides it (§7.2).

**A step with no portal** (email, post, a nomination request) becomes one Needs-you-now item: "Ask the international office to nominate you by 1 Dec", with a drafted email. It's a task the extension can't do, not an instruction. The student sends it; the platform never emails a third party (funding-search-engine spec §9.2).

## 6. Outcomes

- **Place and funding are separate** on a combined card (EMJM): "admitted + scholarship", "admitted, self-funded" or "admitted, on the scholarship reserve list". `RESERVE` is a waiting state with its own reminder.
- **A conditional offer.** Each condition in `outcome_conditions` becomes a document item with its date.
- **Cascades** run in the worker, each with **one** message per event, never one per card:
  - **Place refused, or the card withdrawn:** linked award cards that waited for it close as "Not possible — no admission".
  - **A separate award refused:** programmes in `wait, then pay` on it (§7.1) close as "Not affordable without it — no fee spent". Their `fee_state` becomes `SKIPPED`.
  - **A separate award won:** programmes held on it unlock ("You won X — apply now, fee €100, deadline 20 May").
- **Exclusive awards.** When an award's page states it can't be held with another, a "Decide" item shows both awards' figures. Nothing is assumed when the page is silent.
- **Accepting an offer.** Accept and Decline are steps on an admitted card, carrying `acceptance_deadline` and `deposit_*`. "Compare your offers" appears at the second admission and lists, per offer:
  - the cost left after funding won;
  - the renewal condition, if any;
  - the acceptance deadline;
  - the deposit.

  Accepting one closes the others' lanes to Done, after the student confirms.
- **Recording outcomes:** automatic recording follows the dashboard spec's rules unchanged (provider-authenticated mail, measured bars).

## 7. Money

### 7.1 Four positions

Every paid application of a student whose `funding_dependency` is `MANDATORY` is in one of four positions:

| Position | When | The card says |
|---|---|---|
| **Safe** | no fee, or funding comes with the application (combined, automatic) | nothing special |
| **Wait, then pay** | a linked separate award's `results_date` falls before this application's `fee_deadline` | "Wait for the X result — pay the €100 fee only if you win. Last safe day: 10 May." `fee_state = HELD`. |
| **Pay first, at risk** | the fee is due before the result, or the result date isn't stated | "€85 at risk: if X isn't won, you can't afford this programme." |
| **No route** | no funding route left | never in the pack (the hard gate, unchanged) |

A student whose funding is `IMPORTANT` or `OPTIONAL` sees fees but no holds.

### 7.2 The hold (*owner*: automatic)

- `HELD` hides the card's "Apply to <programme>" button and keeps it out of Needs until the result arrives or the last safe day comes.
- **"Apply now anyway"** sets `RELEASED`. Only the student can press it, because spending is the student's decision.
- **The result arrives:** the cascade in §6 applies.

### 7.3 Last safe day

`fee_held_until` is the step's `fee_deadline` (or its `FINAL` date when no fee deadline is stated) minus 3 days, in the deadline's time zone (§9.2).

**On that day, with no result in:** Needs shows "Result not in yet — pay now or skip this programme", with both buttons. It is never silent, and never skipped automatically.

### 7.4 Fees that are unknown, shared or waivable

- **Unknown fee** (no served route, or the fee isn't stated): `fee_state = UNKNOWN`, and the card shows "Fee not known yet". The budget line lists it as "not counted", never as €0.
- **One fee for a round:** when the snapshot's `portal_system` has `one_fee_per_round`, the fee is counted **once per round** in the budget line, never per card (§8).
- **Application-fee waiver:** an award whose `pays=fee_reduction` targets the application fee shows on the card as "A fee waiver may apply". On a portal the extension guides the request; otherwise it's a Needs-you-now task with a drafted email. The fee counts only if the waiver is refused.
- **Paid:** the student marks it paid. A receipt email recognised by the mail reader marks it paid (`fee_paid_source = MAIL`); otherwise the student does. The extension never touches a payment form (§5.3, unchanged).

### 7.5 The money lines

- **Budget line**, at the top of the board:
  - "Application budget 500 AZN · Paid 190 · Committed 140 · Free 170 (≈, see note)";
  - committed means `OPEN`, `RELEASED` and at-risk fees not yet paid;
  - `HELD` fees are shown separately, as "on hold, only if you win".
- **Lane money line**, per year:
  - "Year 1: covered €X · Year 2: covered if you keep GPA ≥ 3.0 · Still needed: €0 (€Y if not renewed)";
  - only awards **won** count as covered; awards hoped for are listed as "still possible";
  - "up to" amounts count at their stated minimum, and not at all when no minimum is stated.

### 7.6 Currency (*owner*)

- Each amount: the original currency first, then "≈ 140 AZN".
- Totals and the budget: AZN only.
- The rate is the Central Bank of Azerbaijan's daily official rate (cbar.az). It appears only as a note: "Converted at the CBAR rate of 8 Oct; your bank may charge more". It's fetched once a day by the worker and stored per date.
- Currencies CBAR doesn't publish are crossed through the euro using the European Central Bank's daily reference rate (owner, 2026-10-14); a currency neither publishes is left out (`NO_EXCHANGE_RATE`).
- **Margin:** the "fits the budget" check adds a 3% margin for bank charges, so a fee that fits only at the exact rate is shown as "may not fit".
- The home currency comes from the student's country of residence. AZN is the only one at launch; the rule is per country.

### 7.7 A budget with room to stretch (*owner*, 2026-10-09)

A student may say "I plan to spend 400 AZN, but I'd find more for something really worth it". The budget has two parts:
- **`application_budget`:** the plan, as today. The pack fills paid applications up to it.
- **`budget_stretch`:** optional extra the student allows **only** for exceptional items, for example "up to 150 AZN more". A new consultation answer, stored in the profile version: "If an exceptional opportunity appears, how much more could you spend on application fees?" Blank or 0 means no stretch.

**What counts as exceptional enough to use the stretch:**
- the item passes every P1-6 gate;
- its fee fits within the plan plus the stretch, after what's paid and committed;
- **and** at least one of:
  - it's fully funded;
  - it ranks above the last paid item the plan already holds;
  - the student's funding is `MANDATORY` and it's a verified funding route the plan doesn't already cover.

**How it's shown:** a separate "Worth stretching for" item in New for you, never mixed with in-budget items. For example: "Fully funded EMJM — fee €60 ≈ 115 AZN, 75 AZN over your plan (within the extra you allowed)".
- Adding it takes the explicit confirmation of whoever adds it (the student, or their assigned counsellor), every time.
- **One confirmation page for every over-budget add (owner, 2026-10-14).** Adding any programme that does not fit the free budget, whether by add, replace or New for you, opens a page with plain numbers and one tick box naming how much more it costs. Nothing is added until the box is ticked.
- **The student's assigned counsellor may also add one,** after the same confirmation, worded with the student's name and with no "Change my budget" link.
- Stretch money is never committed automatically, and never by a hold release.

**The budget line** shows both parts: "Plan 400 AZN · Extra allowed for exceptional cases: up to 150 · Used from extra: 75".

**Without a stretch:** an exceptional item that doesn't fit is still shown once, as "Over your plan by 75 AZN", with "Change my budget" beside it. The student decides; the platform never decides for them.

### 7.8 Changing the budget (*owner*: student only)

- **"Change my application budget"** sits on the budget line and in Settings. Only the student can use it, and saving writes a new profile version.
- **Raised:** the pack re-plans. Paid applications from the pool are offered in priority order up to the new figure, as "New for you" (§7.9).
- **Stretch:** the student edits `budget_stretch` the same way (§7.7).
- **Lowered:**
  - it can't go below what's already paid, and it is refused while a paid or committed fee can't yet be converted because no rate is loaded (owner, 2026-10-14); a raise always saves;
  - below what's committed, the student chooses which unpaid applications to drop;
  - nothing is dropped automatically.
- **The counsellor's board** shows the budget read-only, with no edit or propose control.

### 7.9 New for you (*owner*)

"New for you" appears only in two cases.
- **The budget gains room:**
  - the student raises the budget;
  - a held fee is never spent;
  - an application is cancelled;
  - an application's deadline passes unused.
- **A fee-free item:** a programme, scholarship or hidden gem with no application fee, found or published later.

**What it offers:** only pool items that pass the P1-6 gates, are open, and close after today.
- A paid item must also fit the free budget.
- In funding-first mode, every fully funded, fee-free item that passes the gates is offered whatever the budget (P1-7).
- It's always one click to add, never automatic.

**A refresh never touches a started lane.** A lane with any step started or any fee paid is locked from pack refreshes. Only untouched suggestions can be replaced (P1-11).

## 8. National rounds

- Cards whose snapshot step has the same `portal_system`, with `choice_limit` or `one_fee_per_round` set and the same intake, form a **round group** (for example universityadmissions.se, autumn 2027).
- **The round group shows:**
  - the student's ranking (`round_rank`), with Move up / Move down;
  - the one shared fee;
  - "3 of 4 choices used". A 5th card is refused with "This round allows 4; replace one".
- **Ranking is explained once:** "An offer from a higher choice withdraws the lower ones" (as stated for that system).
- **The kit carries the ranking** to the extension, which fills it.

## 9. Dates

### 9.1 Start-by date

Start from the relevant deadline (§9.3) and subtract the **largest** of these lead times that applies:
- `prep_lead_days` of the first step's `ApplicationSystem` (uni-assist: 42);
- 21 days, when a referee request with mode `PORTAL_INVITE` or `REFEREE_SENDS` is still open;
- 14 days, when a needed language test isn't held yet.

The lead times overlap in practice (the student books a test while uni-assist checks documents), so they aren't added together.

Needs you now sorts by the start-by date.

### 9.2 Time zones

- A deadline ends at 23:59 in `RouteDate.timezone`. When that's empty, it ends at the earliest instant among the country's zones (§3.4).
- The card shows both: "15 Jan, 23:59 Stockholm time (02:59 Baku time, 16 Jan)".

### 9.3 Which deadline counts

- A student whose funding is `MANDATORY` works to the `FUNDING_CONSIDERATION` date when one exists, otherwise `PRIORITY`, otherwise `FINAL`.
- Others work to `PRIORITY`, otherwise `FINAL`.
- `ROLLING` shows "Apply early: places fill as applications arrive", and sorts with a start-by date of today.
- `DECENTRALISED` shows "Deadline set by each university".

### 9.4 The intake ends

A snapshot whose `FINAL` date has passed with no submission is marked "Closed for this intake". It's never reused for the next intake: the next `SERVED` route is a new suggestion.

### 9.5 Renewal flags (*owner*)

- An award with `renewal_condition` shows "Renewal condition: GPA ≥ 3.0/4 each year" on its card, its lane's money line and "Compare your offers". The quote is one click away.
- In funding-first ranking:
  - an award that renews only on a condition counts as covered, and is flagged;
  - an award with a `duration` shorter than the programme counts as a gap for the remaining years.
- Reminders before each renewal check come after enrolment, outside this spec.

### 9.6 Audience

- The route is chosen by the student's nationality (residence for `NAMED_COUNTRIES` lists that say so).
- Dual nationality: a route matching either nationality is used, the one with the lower fee first. The student can switch.
- When the profile's nationality changes, the worker re-chooses the route for applications not yet started.

## 10. Documents, asked once

- **One document list per student,** computed from every card's needs:
  - route steps;
  - programme document requirements;
  - award requirements;
  - referee requirements;
  - offer conditions.

  Each document appears **once**, with the applications that need it: "IELTS ≥ 6.5 — needed by 4 applications". The strictest value wins.
- **Variants** an application needs (certified copy, translation, apostille, addressed to the programme) are sub-items of the same document.
- **One upload serves every application** (as today).
- **Needed by:** each document's needed-by date is the earliest start-by date among the cards that need it. Example: "IELTS: needed by 2 Jan for TUM (your first deadline)". Reminders use the existing reminder ladder (`apps/portals/reminders.py`).
- **Validity:** a test score, passport or letter whose validity ends before the date it's needed is flagged: "Your IELTS expires 3 Mar; Lund needs it valid on 1 Apr". It covers:
  - stated recency rules, such as "letter written within the last 12 months";
  - typical validity, where nothing is stated: 2 years for IELTS/TOEFL.
- **When a student starts,** they see the list built from their current pack, not a generic form. Adding a programme adds only what's new.
- **The Documents page has two views:** by document (this list) and by application (today's table).
- **Costs:** only application fees are shown (*owner*). Test fees, translation and courier costs are not.

## 11. Referees and reference letters

### 11.1 What each application needs

From the copied `referee_requirements`:
- `count`, `kind`, `mode`, `institutional_email_required` and `due`, each with its sentence;
- **a conditional record** (`conditional = true`, for example "scholarship track") applies only to the route or award its condition names;
- **a field with no record** shows "Not stated — check the page", never a default.

### 11.2 The referee plan

- **The student adds professors once:** name, title, institution, email, relationship, how many portal requests they agreed to, and whether they'll give one generic letter.
- **The platform proposes an assignment** (`RefereeRequest` rows in `PROPOSED`), and the student confirms or edits it:
  - each application's `count` and `kind` are met;
  - each professor stays within `agreed_requests`, counting only `PORTAL_INVITE` and `REFEREE_SENDS` requests;
  - a generic letter is reused for every `UPLOAD_GENERIC` application at no cost to the count;
  - the strongest referee goes to funding-deciding applications and to the earliest start-by dates;
  - an institutional email is used where required, and a non-institutional one is flagged.
- **Too few referees:** "Prof. Aliyev agreed to 3; your pack needs 5 portal letters. Ask a third referee, or the 2 programmes that accept an uploaded letter can use his generic one."
- **Swap referee** reassigns a professor who declines or goes silent, and the plan is proposed again.

### 11.3 The request package

The **student** sends it. The platform never emails a third party. It contains:
- the professor's applications, deadlines and portal names, with "expect an email from these senders";
- the student's CV;
- a facts sheet: courses and grades with this professor, projects, achievements, and what each programme looks for (from the card's copied requirements, `kit_requirements`: the web tier never reads `ProgramStatement`);
- one ready-to-send message.

**Status:** a portal's "your referee has submitted" email, recognised by the mail reader, sets `SUBMITTED`. Otherwise the student marks it.

### 11.4 A letter for the professor's signature (*owner*: option C)

When the professor asks the student to write the letter, the student presses **"Draft a letter for Prof. X to sign"**. The letter engine writes the full letter. Guardrails:
- **Content** comes only from the student's confirmed facts (`generatable_facts`), as with every generated letter. Nothing checkable is invented.
- **Never where a binding rule forbids it:** a binding `letter-rules` entry, GKS's false-recommender rule, or a portal where the referee attests authorship. The button is then absent, with the rule shown.
- **The student confirms** "Prof. X asked me to draft this and will review and sign it" before the draft is shown. The confirmation is recorded.
- **Different letters from different referees.** Two professors writing for the same application get letters built on each one's own relationship facts, and the engine's similarity check refuses near-duplicates.
- **Rate limits:** the letter engine's existing limit applies. No new model path.

## 12. Privacy

- **Erasure:** `ApplicationLink`, the fee fields, `Referee`, `RefereeRequest` and the copied facts are erased with the student. Referee records are third-party data, and nothing else uses them.
- **Outcome learning** (*owner*): outcomes are stored for learning only with the `OUTCOME_LEARNING` consent. Without it, they drive the board and nothing else. The derived-data rules of `phased requirements.md` §6.1 and CLAUDE.md (a `Pseudonym` FK with `CASCADE`) apply when the learning pipeline is built. This spec adds only the consent and the label.
- **The counsellor** sees everything on the board except that they can't change the budget and can't release a held fee.

## 13. Never shown (*owner*)

- **Scholarship scams.** An award whose page demands a fee on a host that isn't proven official is excluded from the catalogue's served set and never shown.
- **Agents.** A route whose only channel is an agent has no `SERVED` route. The programme is excluded from the pack.

## 13a. Country notices (*owner*, 2026-10-09)

Some countries carry a practical warning a student should read before applying.

- **Student side only.** A notice is display text keyed on the programme's `country_code`, or the award's funder country (`ApplicationSystem.country_code` / the award copy's `country_code`). It is never catalogue data (agreed with the catalogue owner).
- **Informational only:** it never blocks Add or "Apply to <programme>".
- **Where it appears:** a one-line warning on the card, and the full text on the programme page.
- **Before it ships:** every fact is checked against official sources and shown with its check date.
- **Upkeep:** re-checked every 3 months.
- **New countries are added only by the owner,** never automatically.

**Russia (`RU`), owner-approved wording:**

Card line:
> ⚠ Studying in Russia: check payments, travel and degree recognition first — see details.

Programme page:
> **Before you apply to a programme in Russia**
> International sanctions in place since 2022 can affect you as a student:
> - **Payments.** Visa and Mastercard have suspended their operations in Russia, so cards issued outside Russia don't work there. Several major Russian banks are also cut off from SWIFT, the network banks use for international transfers. Ask your bank, before you pay any fee, how you'll pay the tuition and receive money.
> - **Travel.** Russian airlines and Russian-registered planes are banned from EU, UK and US airspace. Depending on where you live, you may need a connection through another country, so check routes from your home city.
> - **Degree recognition.** Russia's membership of the European Higher Education Area (the Bologna Process) is suspended. If you plan to work or study further in the EU, UK or US, check how your degree will be recognised there.
> - **Exchanges.** The EU has ended Erasmus+ cooperation with Russian public bodies, a group that includes Russia's state universities.
>
> *This is general information as of {check date}, not legal advice. Rules change; your counsellor can help you check what applies to you.*

## 14. Build order

Each is its own implementation plan. Plans 1–3 need §3.4's tables, which are built by the catalogue plans.
- **Until then:** plans 1–3 run on the counsellor-recorded fallback route.
- **Once routes are served:** they switch with no change to this side.

| Plan | Contents | Needs |
|---|---|---|
| 1. Links and copies | §3.1 copies (route snapshot, referee and award facts), `ApplicationLink`, auto-added awards (§4), audience choice | §3.4 tables, PR #185 |
| 2. Lanes | the lane board (§5), the card and programme page (§5.1) on plan 1a data, the extension-required states, deadline choice and time zones (§9.2–§9.4), country notices (§13a), and the funding-page text fixes: no "not stated", "(unstructured)" or "Not confirmed", country names in group labels, and removal of plan 1a's "Suggested — check you qualify" line (§4.3). The rest is 2b. | plan 1a |
| 2b. Lanes, the rest | cascades and outcomes (§6), rounds (§8), start-by lead times (§9.1), fit/risk/requirement statuses, EMJM tracks, scholarship renewal and obligations, the nomination task, Apply to the first step not DONE | plan 1b, the tailored build, plan 4 |
| 3. Money | the Safe and Pay-first positions (§7.1), unknown and paid fees and the fee state (§7.4), the budget line (§7.5), CBAR currency with the 3% margin (§7.6), the student-only budget and stretch with the new consultation answer (§7.7, §7.8), New for you (§7.9), a trusted receipt marking a fee paid. The rest is 3b. | plans 1–2 |
| 3b. Money, the rest | the fee hold, "Apply now anyway" and the last safe day (§7.2, §7.3), "Wait, then pay" (§7.1), one fee per round and the fee waiver (§7.4), the lane money line (§7.5), stretch reason 3 (§7.7), fee-free items found later (§7.9) | plan 1b, plan 2b |
| 4. Documents and referees | the document list with needed-by and validity (§10), referee facts on the candidate, the referee plan with swap, the request package, and SUBMITTED from trusted mail (§11.1–§11.3) | plan 1 |
| 4b. Documents and referees, the rest | the draft for signature (§11.4), strictest value wins, variants beyond the certified copy, route-step and award document sources, needed-by from start-by lead times, per-document reminders, typical and recency validity (§10) | the one-letter-engine design, a requirement-values reader, plan 1b, plan 2b |

## 15. How it's tested

- **Pure functions** get table tests: position, last safe day, start-by date, deadline choice, round counting, referee assignment, the document list's strictest-value merge, currency margin, stretch eligibility (each of the three qualifying reasons, and an item that fits only with the stretch).
- **Each cascade** is tested with linked cards and asserts exactly one message.
- **The RLS checks** run through `rls_enforced_orm`: every new tenant table, and every worker copy.
- **The trust rule is unchanged:** an untrusted mail never changes `fee_state`, a cascade, or a referee status.
- **Every new field** is checked against the redaction classification.
- **Acceptance:** one student with a Swedish round (2 programmes, one fee, ranked), an SI scholarship that waits for admission, a German programme behind uni-assist (start-by 42 days earlier), a Chevening lane covering 3 choices, two professors (one generic letter, one portal-invite professor at capacity) and a budget raised mid-cycle. Every Needs item, money line and cascade message is asserted.

## 16. Open items

- **Applications with no served route** keep the counsellor portal task until §3.4 serves them.
- **The application-systems seed** (`docs/research/application-systems.csv`) waits for the owner's review and its verification pass (2026-10-09).
- **Spec B** (the extension) must fill rankings, tick same-form award boxes, and work from the step "Apply to <programme>" opened (the first not `DONE`). The dashboard's `START_FILL` queueing is superseded by the guidance spec (D2, §3).
- **The risk label and "why it fits you"** come from the tailored-programme build, which isn't built yet. Until it is, the programme page shows the requirements and the funding without them.
- **Home currencies other than AZN** follow the same rule when a second market opens.
- **Deferred from plan 2 to plan 2b:** cascades, outcome and offer comparison, national rounds, start-by lead times, fit/risk/requirement statuses, EMJM tracks, renewal and obligations, the nomination task, and Apply opening the first step not `DONE` (each blocked on the data named in the table in `docs/superpowers/plans/2026-10-11-lanes-plan-2-board-card-page.md`, "Scope ruling: plan 2 now, plan 2b later").
- **Deferred from plan 3 to plan 3b:** the fee hold and its last safe day, "Wait, then pay", one fee per round, the fee waiver, the lane money line, stretch reason 3, and fee-free items found later (each blocked on the data named in the table in `docs/superpowers/plans/2026-10-13-lanes-plan-3-money.md`, "Scope ruling: plan 3 now, plan 3b later").
- **Deferred from plan 4 to plan 4b:** the draft for the professor's signature, strictest value wins, variants beyond the certified copy, route-step and award document sources, needed-by from start-by lead times, per-document reminders, and typical or recency validity (each blocked on what the table in `docs/superpowers/plans/2026-10-13-lanes-plan-4-documents-and-referees.md`, "Scope ruling: plan 4 now, plan 4b later", names).
