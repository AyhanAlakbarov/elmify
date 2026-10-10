# Open-source landscape — evidence intake (repos and publications)

Date 2026-08-27. Companion to the CV content research. Licence, last push, stars and latest
release read from the GitHub API on 2026-08-27. Verdicts are against *this* codebase and
against the security constraints in `CLAUDE.md` (no unproxied fetch of a user-supplied host;
the fetching task holds no credentials).

Prior art not reopened here: `2026-08-22-open-source-landscape.md` already settled the OCR /
document-extraction shortlist (Docling, PaddleOCR, MinerU, marker) and dismissed resume
parsers. That note also **deferred ESCO** on the grounds that nothing needed skill
normalisation yet -- that is no longer obviously true if skills become a CV feature, so ESCO
should be revisited when the skill layer is designed, not here.

## Repo → LLM context (the "repomix" category)

| Project | Licence / activity (GitHub API, 2026-08-27) | What it is | Reusable here | Verdict |
|---|---|---|---|---|
| **repomix** `yamadashy/repomix` | MIT; v1.18.0 (2026-08-08); pushed 2026-08-26; 28.1k★ | Packs a repo into one XML/MD file; Tree-sitter compression cuts ~70% of tokens | Only if we clone | **Reference only** unless option B is chosen |
| **gitingest** `coderamp-labs/gitingest` | MIT; v0.3.1 (2025-07-31) but pushed 2026-08-26; 15.4k★ | Same category; URL-swap trick and a hosted service | Hosted variant means sending student repo URLs to a third party | **Reference only** |
| **code2prompt** `mufeedvh/code2prompt` | MIT; v4.2.0 (2025-12-11); pushed 2026-06-29; 7.6k★ | Rust, template-driven | Slowing; nothing the others lack | **Ignore** |
| **files-to-prompt** `simonw/files-to-prompt` | Apache-2.0; 0.6 (2025-02-19); pushed 2025-02-19; 2.8k★ | Minimal local packer | 18 months stale | **Ignore** |

**The category verdict matters more than any single tool: every one of these clones the
repository.** They are all implementations of option B, and none of them addresses the reason
B is expensive here -- connecting to an arbitrary host the student named. Adopting one does
not reduce the security work; it only saves the file-walking code, which is the cheap part.

If option B is ever chosen, repomix is the pick: MIT, by far the most active, and its
Tree-sitter compression is the one feature that materially changes LLM cost.

## Repo metadata without cloning (option C)

| Project | Licence / activity | What it is | Verdict |
|---|---|---|---|
| **GitHub REST API** | n/a — service | Languages, tree, commits, contributors, any file's contents, from one fixed trusted host | **Adopt** |
| **GitLab REST API** | n/a — service | Equivalent surface | **Adopt** for gitlab.com |
| **PyGithub** `PyGithub/PyGithub` | **LGPL-3.0**; v2.10.0 (2026-08-20); pushed 2026-08-27; 7.8k★ | Full object mapping over the API | **Ignore** — we need roughly six endpoints of plain JSON over HTTPS, and the existing HTTP stack already does that. Not worth a dependency, and LGPL is a licence question we do not need to answer for six GET requests. |

Self-hosted GitLab and arbitrary git hosts have no fixed-host guarantee, so they are option B
by another name. Support github.com and gitlab.com; anything else is out of scope or falls
back to asking the student.

## Publication metadata

| Project / service | Licence / activity | What it is | Verdict |
|---|---|---|---|
| **Crossref REST API** | n/a — service; free, no key | DOI → title, venue, year, volume, issue, pages, ordered authors, type, publisher | **Adopt as the primary path** |
| **OpenAlex REST API** | n/a — service; free, no key | Broader coverage: conference papers, preprints, works without a Crossref DOI | **Adopt as fallback** |
| **habanero** `sckott/habanero` | MIT; v2.9.2 (2026-06-17); pushed 2026-07-31; 251★ | Python Crossref client | **Ignore** — a thin wrapper over one GET. Direct HTTP is fewer moving parts. |
| **pyalex** `J535D165/pyalex` | MIT; v0.21 (2026-02-23); pushed 2026-07-06; 404★ | Python OpenAlex client | **Ignore**, same reason |
| **GROBID** `kermitt2/grobid` | Apache-2.0; 0.9.1 (2026-08-04); pushed 2026-08-27; 5.1k★ | ML extraction of bibliographic structure from scholarly PDFs; 68 labels; consolidates against Crossref | **Defer** — a Java service with its own model weights, only needed for a PDF with no DOI. Real, healthy, and heavy. Revisit if DOI-less manuscripts turn out to be common. |

### Measured, not assumed

One unauthenticated Crossref call on a real applicant DOI (`10.1021/acscatal.5c00348`):

    title   : Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles
    venue   : ACS Catalysis
    year    : 2025
    volume  : 15 | issue: 6 | pages: 4739-4745
    authors : Orkhan Abdullayev, Diego Garay-Ruiz, Berta Bori-Bru, Carles Bo
    type    : journal-article | publisher: American Chemical Society (ACS)

That populates `PublicationEntry` completely -- and the applicant's own CV carries
`15, XXX, 4739-4745`, an unfilled issue-number placeholder. Crossref supplies **issue 6**.
Every field is mechanically derived and re-checkable, so the whole record lands in the
auto-confirm tier: no LLM, no PDF parsing, no human confirmation.

## Worth the time

1. **Crossref, then OpenAlex.** The publication half of evidence intake is close to free and
   produces the highest-confidence facts in the system. Do it first; it needs no LLM and no
   new infrastructure.
2. **The GitHub/GitLab REST APIs directly, no client library.** Option C's whole value is that
   it talks to one fixed host. A dependency adds surface without removing any.
3. **repomix — only if option B is chosen.** MIT, healthiest in its category, and its
   Tree-sitter compression is the one thing that changes the economics. Do not adopt it as a
   way to *avoid* the security question; it does not.

Everything else: reference or ignore. The honest summary of this landscape is that the
services are worth adopting and almost none of the libraries are.
