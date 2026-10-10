# Design: the CEFR self-assessment grid

Status: design, not yet implemented. Scope: `LanguageEntry` gains the five CEFR sub-skills Europass mandates, the ledger carries them, and the EUROPASS variant renders the real grid instead of a single-level column. Extends `docs/superpowers/specs/2026-08-21-phase2-cv-engine-design.md`.

This is the first of two specs. The second — rendering an official Europass CV through europa.eu's API — depends on this one and is not designed here.

## Out of scope here

- **The Europass API render.** Its own spec. It cannot proceed without the fields defined below, which is why this one goes first.
- **The editing surface** where a student refines their own sub-levels after seeing the rendered CV. That surface is the *reason* the fields are per-sub-skill rather than derived at render time, but the screen itself is a separate piece of work.
- **`date_of_birth`, `sex`, `citizenship`, date-of-issue, page caps.** Other Europass-specific gaps, unrelated to language.
- **Every non-EUROPASS variant.** STANDARD, GERMAN_TABULAR, SISGP and Rhodes keep showing the single `cefr_level` they show today. Nothing about their output changes.

## The problem

Europass mandates five self-assessed CEFR levels per language — **Listening, Reading, Spoken interaction, Spoken production, Writing** — plus a mother-tongue list. `LanguageEntry` (`apps/documents/schemas.py:71`) carries one:

```python
class LanguageEntry(BaseModel):
    language: str
    cefr_level: str | None
    test_name: str | None
    test_score: str | None
```

`cv_europass.html` renders that as a four-column table — Language, CEFR level, Test, Score. It is a table, not the grid, and no template change fixes it: **the schema cannot represent a Europass language grid.** R-053 specifies "editor sections + CEFR grid" for the EUROPASS variant; the grid half was never built.

This matters most for the funders that make Europass binding — R-056 GLOBED ("resumes in other formats won't be accepted"), R-003 AMIR, R-058 MathMods, R-005 STEPS, R-057 i-MESC — and language is the section a European reviewer looks at hardest.

## Where the values come from

**No document states them.** A transcript is silent on spoken interaction. An IELTS certificate gives one overall band. The five sub-skills are self-assessment; that is what the Europass grid is for.

So the rule is: **one stated level fills the whole grid, and the ledger records only what was stated.**

A student whose uploaded CV says "English C1" gets C1 in all five columns. B1 gets B1 in all five. The alternative — writing five confirmed LANGUAGE facts from one statement — would put four claims in the ledger the student never made, and a counselor reviewing provenance would see five statements where there was one. This engine's entire claim is that it does not invent; filling a grid is not the place to start.

The fallback therefore lives in **rendering**, not in the ledger:

- `LanguageEntry` gains five optional sub-skill fields, all defaulting to `None`.
- Ingestion and generation need no code change. Neither reads the field list directly:
  `fact_payload` filters through `_PAYLOAD_KEYS`, and the model fills whatever
  `LanguageEntry` declares. So a student whose uploaded CV already carries a grid
  has those five values extracted and stored; a student whose CV states one level
  gets one level stored and the fallback does the rest.
- At render time, a sub-skill that is `None` falls back to `cefr_level`.
- When the student later refines "reading C1, speaking B2" through the editing surface, those values populate and the fallback simply stops applying for them.

No migration when that surface ships, no second sourcing decision, and no re-derivation of anything.

## Data model

```python
class LanguageEntry(BaseModel):
    language: str = Field(min_length=1, max_length=100)
    cefr_level: str | None = Field(default=None, max_length=10)
    test_name: str | None = Field(default=None, max_length=100)
    test_score: str | None = Field(default=None, max_length=50)
    #: Europass self-assessment. None means "not separately assessed" and
    #: falls back to cefr_level at render; it does not mean "no skill".
    listening: str | None = Field(default=None, max_length=10)
    reading: str | None = Field(default=None, max_length=10)
    spoken_interaction: str | None = Field(default=None, max_length=10)
    spoken_production: str | None = Field(default=None, max_length=10)
    writing: str | None = Field(default=None, max_length=10)
```

**The fallback is a property on the entry**, not template logic:

```python
@property
def self_assessment(self) -> tuple[tuple[str, str | None], ...]:
    """The five Europass sub-skills, each falling back to cefr_level."""
```

Returning label/level pairs in Europass's own order keeps the template a loop and puts the rule somewhere testable. A Django template can read a property with no arguments, so no filter or context processor is needed.

**Ledger payload.** `_PAYLOAD_KEYS` gains the five keys for `languages`, alongside the pattern already used for education's grade fields:

```python
+ (("listening", "reading", "spoken_interaction", "spoken_production", "writing")
   if spec.field == "languages" else ())
```

## Verification semantics

The five sub-skills are **carried for provenance and never compared** — they do not join the LANGUAGE spec's `detail` tuple, which stays `("cefr_level", "test_name", "test_score")`.

Two reasons, and the second is the load-bearing one.

**Nothing can contradict them.** `cefr_level` is comparable because a fact can be backed by a certificate — `test_name`/`test_score` exist for exactly that. A self-assessed spoken-production level has no document behind it, so a fact can neither confirm nor contradict it. This is the same reasoning that kept `degree_english` out of `detail`: a value with no independent source is not a claim that can disagree.

**Comparing them would turn an intentional edit into a blocking verdict.** The whole point of the fields is that a student revises them after seeing the rendered CV. If they sat in `detail`, a student correcting reading from C1 to B2 would produce CONFLICTING, `is_blocked` would fire, and the draft would refuse to approve — punishing the user for using the feature. Corrections to the ledger belong in a superseding fact, not in a verdict.

## Rendering

Only `cv_europass.html` changes. Its four-column table becomes the Europass grid: a row per language, a column per sub-skill, driven by `entry.self_assessment`. `test_name` and `test_score` stay — a certificate is worth showing and Europass has room for it — but they move out of the grid proper, since they describe the language rather than one sub-skill.

Mother tongue is **not** modelled here. Europass separates `nativeLanguages` from `otherLanguages`, and `LanguageEntry` has no native flag. Adding one is a schema and sourcing question of its own; it belongs to the Europass API spec, where the distinction actually has to be sent over the wire. The template renders one grid until then.

## Testing

| Test | What it holds |
|---|---|
| `self_assessment` falls back to `cefr_level` for every `None` sub-skill | The rule: one stated level fills the grid |
| An explicitly set sub-skill overrides the fallback | The reason the fields exist |
| A `cefr_level` of `None` with no sub-skills yields five `None`s, not a crash | Language with no stated level is legal today |
| `fact_payload` on a LANGUAGE entry carries all five keys | Same class of bug as the `_PAYLOAD_KEYS` drop fixed in `4a68575` — a key absent here never reaches the model |
| A differing sub-skill does **not** produce CONFLICTING — *pins a decision* | Fails if anyone moves the sub-skills into `detail`. That change looks reasonable and would block every student edit |
| The EUROPASS render shows five sub-skill columns, and STANDARD does not | The blast radius stays inside one variant |

The fifth is the one that rots silently: it passes today for the wrong reason, so it must be verified against a deliberately wrong implementation — put a sub-skill in `detail`, watch it fail, revert — the way `test_a_differing_gloss_does_not_conflict` was checked.

## Consequence worth stating

Most students will have a Europass CV showing the same level in all five columns. That is a defensible self-assessment — it is their own stated level, applied uniformly, and it is what a student filling the grid in a hurry would do. It stops being uniform as soon as the editing surface ships.
