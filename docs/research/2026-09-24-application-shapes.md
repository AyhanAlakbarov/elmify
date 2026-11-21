# Application shapes: how many programmes, how many letters, what the fee buys

**Status: 2026-09-24. Ten rows, two fetched directly, three already on file, five from a
GPT-Researcher pass and labelled as not re-fetched. Enough to settle the data model; not a
complete world survey.**

## The answer, as axes rather than a list of institutions

The institutions vary endlessly; the SHAPES do not. Three independent axes cover every
system found, and the data model needs all three because they combine freely:

| Axis | Values found | Example |
|---|---|---|
| Programmes per application | 1 \| a fixed maximum (2, 3, 4, 6) \| unlimited | Aarhus 1 (max 4 priorities); DAAD HS 2; Chevening 3; Finland 6 |
| **Letters per application** | **one shared and ranked** \| **one naming the first choice only** \| **one per programme** | DAAD HS / EPOS; Chevening; Sciences Po / KTH / Finland |
| Fee unit | per programme choice \| per application covering many \| per priority set | uni-assist EUR 75+30; Leiden EUR 100, Sciences Po EUR 150; Aarhus 4 priorities |

The middle axis is the one the engine cannot express, and it has **three** values, not two.
Both of the owner's cases are real and sourced: DAAD Helmut-Schmidt requires *the same single
letter for both courses, with the courses ranked inside it*, while Sciences Po requires *two
separate letters in one submission* for its two choices. Chevening is a third case neither of
us named: many choices, one letter, and it must address only the first.

Two consequences for the model, and they are small:

1. A letter belongs to **one or more** programmes, not exactly one.
2. A prompt needs a `letter_scope` of `PER_PROGRAMME` / `SHARED_RANKED` / `FIRST_CHOICE_ONLY`.
   Everything else -- shape, gates, reuse -- already keys off the prompt.

The fee axis affects no letter logic and is recorded only so nobody conflates it with the
letter count: uni-assist charges per programme while Sciences Po charges once for two, and
both of those are *per-programme-letter* systems, so fee and letter count do not correlate.

## Why this exists

The engine models one letter per programme, with a single link between a programme's
prompt and its paired scholarship prompt. The owner raised the case it cannot express:
systems where you pay once, choose several programmes, and write **one** letter covering
all of them -- and the neighbouring case where you choose several and must write a
**different** letter for each. Which of these exist decides whether a letter may belong
to more than one programme, which is a data-model question, so it comes before the
reuse spec.

## What the existing catalogue already says

`letter-rules.csv` names four shapes in passing, inside L-061, which was written about
something else (whether reuse is penalised):

- **KTH** -- one letter per programme.
- **DAAD EPOS** -- *one letter ranking all the courses*. The owner's case, already found.
- **Chevening** -- one application, three different courses required, essays addressing
  the **first choice only** (L-020, L-068).
- **US (Berkeley, UCLA, Rackham)** -- two documents that must not duplicate each other.

L-061 also concludes that **no admissions office or funder was found that penalises
reusing a core letter**, and that core reuse with programme-specific sections regenerated
is consistent with every published rule found. That is the evidential basis for the reuse
design; it was recorded before the shapes question was asked.

## Still unestablished

Türkiye Bursları, GKS (Korea), CSC (China), MEXT, Stipendium Hungaricum, ESKAS, Erasmus
Mundus consortia and Sweden's universityadmissions.se. Direct fetches of the Turkish,
Swedish and Chevening sites returned navigation pages only; the counts sit deeper or, as
L-020 already records for Chevening's word limits, only inside the live application form.

**None of them is likely to add a fourth value to the letters axis.** Each further system
should land in one of the three, and the value of checking them is coverage of the
`programmes_per_application` maximum, not discovery of a new shape. That is why the model
can be designed now.

## Method notes

- Record the fee unit separately from the letter count. This pass found systems where they
  diverge in both directions, so one cannot be inferred from the other.
- A hub page is not an answer. If a number exists only in the live form, record that as the
  finding, as L-020 did.
- The GPT-Researcher pass returned real primary sources (DAAD's own PDF, Sciences Po,
  Studyinfo, Aarhus, Leiden) mixed with content farms (edubirdie, bold.org, euroscholarhub,
  a Facebook post). Every row above is attributed to a primary source or marked
  `not re-fetched`; nothing from a content farm was used. The repo's open observation that
  broad research calls are the wrong unit is half-right: the pass found shapes a targeted
  fetch had missed, and it also needed its citations checked one by one.
