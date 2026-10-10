# The "dual-seed" proposal, checked claim by claim

An outside note argued that indexing accredited universities (WHED, DEQAR) misses the
entities that hold the money, and proposed three fixes: load ROR, reverse-seed from funder
grant-winner lists, and stop disqualifying non-university hosts. Checked against this
repository on 2026-09-19 and against a live ROR probe. Two claims are wrong for us, one
mechanism is already built, and one suggestion is more valuable than the note argues.

## The measurement that decides it

ROR's public API, no key, 10 queries, 2026-09-19. The prediction under test was mine: that
ROR indexes research-*performing* organisations and would therefore miss scholarship
charities, which is where the 2026-09-19 yield run actually found money.

| queried | top hit | ROR types | site |
|---|---|---|---|
| Max Planck Institute for Informatics | exact | `facility` | mpi-inf.mpg.de |
| Centre National de la Recherche Scientifique | exact | `funder,government` | cnrs.fr |
| Cusanuswerk | exact (1 result) | `funder,other` | cusanuswerk.de |
| Studienstiftung des deutschen Volkes | German National Academic Foundation | `funder,nonprofit` | studienstiftung.de |
| Türk Eğitim Vakfı | exact | `nonprofit` | tev.org.tr |
| Visegrad Fund | International Visegrad Fund | `funder,other` | visegradfund.org |
| DAAD | German Academic Exchange Service | `funder,nonprofit` | daad.de |
| Baden-Württemberg Stiftung | exact | `funder,other` | **bwstiftung.de** |
| Anadolu Vakfı | **Türk Eğitim Vakfı** (wrong) | `nonprofit` | tev.org.tr |
| EMBL | **EMBL Australia** (wrong) | `funder,government` | emblaustralia.org |

**The prediction was wrong.** ROR carries a `funder` type and covers the scholarship long
tail, including four hosts from the very list the yield run read. Two defects bound how it
may be used, and both are visible above:

- **The top hit is sometimes a different organisation.** Anadolu Vakfı returned Türk Eğitim
  Vakfı; EMBL returned EMBL Australia. Fuzzy `query=` returns thousands of results ranked by
  relevance, so ROR is a lookup **with verification**, never "take the first row". This is
  the same discipline the name→site resolver measurements already established.
- **ROR gives the organisation's site, which is not always the programme's.** It returns
  `bwstiftung.de` where our host list carries `bw-stipendium.de`. Holder awards are keyed on
  the registrable domain, so those two would not join. Any ROR binding must therefore be
  organisation→**domains** (plural), or the join silently misses.

## Claim by claim

| claim | verdict |
|---|---|
| Registries index only accredited degree-granting HEIs | True in general, and the split it prescribes is the axis built on this branch on 2026-09-18: `holder` (15 values incl. `INTERGOVERNMENTAL`, `EMPLOYER`, `PRIVATE_FOUNDATION`) and scope `HOLDER_OWN`, so an award serves on its holder's own page |
| Independent research institutes and national labs are missed | **True, and the sharpest point in the note.** Discovery has no route to an institute's own page. The reader would read one (`I3_STIPEND_OR_ASSISTANTSHIP`, `I4_RESEARCH_PATHWAY` exist), but nothing queues those hosts. Already owed as the "PI/lab postings" measurement in the funder spec §13 — the note confirms it independently |
| Erasmus Mundus consortia are missed because they are not universities | **False for us.** EMJM consortium sites are the primary seed (`seeds.py::EACEA_ERASMUS_MUNDUS`); 497 EACEA leads measured on this branch's base commit |
| "Follow the money" reverse-seeding is needed | **Already built**, 2026-09-18: every pointer line becomes a name for the organisation register (`PointerLead`, `DiscoveryReport.pointer_names`). One Turkish page named 31 funders that were previously discarded |
| Don't disqualify a host for not being an accredited university | **No-op.** There is no accreditation gate: zero occurrences of "accredit" in `apps/`. Nothing to remove |
| "If a national funder sends money there, it is legitimate" | **Rejected.** That is provenance from a third party. Provenance comes from the origin only; an aggregator or winner list yields names, never evidence (CLAUDE.md, web-fetching section) |

## What to take, in order

1. **Measure ROR coverage against lists we already hold, before building anything.** The
   owner's rule is that a new source gets a holds-and-generalises check first. Two lists
   exist: the 58 yield hosts (`docs/research/2026-09-18-yield-hosts.txt`) and the pointer
   names the funder path now produces. The numbers that decide it: share of hosts ROR knows,
   share where an exact-name match exists (not just a fuzzy top hit), and share where ROR's
   website matches the domain we already hold. Free, no key, one script.
2. **If it holds, ROR enters as a third register shape and as the resolver's first stop.**
   `registers.py` is built as "one frozen config per register", but DEQAR and WHED are
   per-country HTML/API sources and ROR is a global versioned dump — a different shape, and
   a small real integration cost. Its payoff is two-sided: a free global funder list
   (`types` filtered to `funder`, `facility`, `nonprofit`, `government`, `company`), and
   name→site resolution as a local lookup instead of a paid search call.
3. **A research-institute route**, seeded from ROR's `facility` entries, closing the §13
   "PI/lab postings" gap. An institute's "master's thesis project with stipend" page is
   neither a programme page nor a scholarship page, and today nothing fetches it.
4. **Call and winner archives as recurrence evidence, not as provenance.** The note's
   winner-list idea has a better use than seeding: a funder's dated call or winner archive is
   exactly the "two consecutive observed cycles" that `cycle_validity` needs for `UPCOMING`
   (funder spec §3.5.1). Same page, read for dates rather than for names.

## The gap the note's own examples expose, which we do not have

A Max Planck thesis stipend and a French CIFRE contract both pay a student who is **enrolled
somewhere else**. The award is conditional on an admission, and nothing in the model can say
so: `route` describes *selection* (`INSTITUTION_NOMINATES`, `JOINT_SELECTION`), not an
enrolment prerequisite, and a holder award carries no link to the institutions that satisfy
it. Consequences, both real:

- Such an award would be offered to a student who has no place at a qualifying institution —
  money they cannot take.
- Its cost side is wrong too: the pack treats an award as its own application with its own
  deadline (2026-09-19 decision), but this one is only worth applying to *alongside* a
  specific programme application.

Recorded in the recommendation-spine design as a known limit; closing it needs one field on a
holder award — the institutions or programmes an enrolment condition names — and it needs the
reader to record that condition, which is the same gap as §3.2 there (the reader stores the
shape of a restriction, not its content).
