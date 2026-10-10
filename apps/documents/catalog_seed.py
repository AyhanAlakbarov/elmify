"""The enforceable subset of the researched CV rules.

Curated by hand, not parsed: the CSVs' enforcement column is prose in 18 of 93
rows ("binding (Scholar) / advisory (Student)"), their scope column is prose
too, and two thirds of the rules have no checkable key at all. Each row here
records one human judgement, reviewable against the CSV by rule_id.

A rule absent from this module is not enforced -- which is the property a
silently-partial CSV import would destroy.
"""

from __future__ import annotations

from typing import Any, get_args

from django.db import transaction

from apps.funding.models import update_exactly

from .constraints import _CONSTRAINT_KEYS

#: Every funder a rule is scoped to, and the CV format that funder mandates.
#: canonical_key is FundingOpportunity's unique key, so these strings are the
#: same ones SEED_RULES scopes against. "" means the funder states no format.
#
# Two traps here are not reachable today (nothing wires DocumentDraft.
# funding_opportunity to a real row yet) but will hard-fail the moment that
# lands:
#
# - "daad-epos": europass_required -> EUROPASS_API, and R-010 seeds
#   date_of_issue_required=True as BINDING. render.py's _check_date_of_issue
#   returns "variant produces no PDF to carry a date of issue" for the
#   EUROPASS_API placeholder, and date_of_issue_required is in
#   _CONTENT_ONLY_KEYS so it blocks before any network call. The local
#   preview path also renders the Europass look-alike without passing
#   date_of_issue. Net: this funder can never get a CV rendered as-is.
# - "australia-awards" (and "rhodes", "sisgp" below): funder_template ->
#   FUNDER_TEMPLATE, but render.py's _funder_dispatch() only knows "SISGP"
#   and "RHODES" by template id, and nothing derives funder_template_id from
#   a canonical key -- render_draft's funder_template_id param defaults to
#   None and no caller passes it. Any draft routed here raises
#   UnsupportedRenderVariant.
SEED_FUNDERS: tuple[tuple[str, str, str], ...] = (
    ("rhodes", "Rhodes Scholarship", "funder_template"),
    ("sisgp", "Swedish Institute Scholarships for Global Professionals", "funder_template"),
    ("australia-awards", "Australia Awards", "funder_template"),
    ("daad-epos", "DAAD EPOS", "europass_required"),
    ("daad-study-scholarships", "DAAD Study Scholarships", ""),
    ("daad-prime", "DAAD PRIME", "europass_preferred"),
    ("amir", "AMIR EMJM", "europass_required"),
    ("membiomed", "MemBioMed EMJM", "europass_required"),
    ("steps", "STEPS EMJM", "europass_required"),
    ("globed", "GLOBED EMJM", "europass_required"),
    ("i-mesc", "i-MESC EMJM", "europass_required"),
    ("mathmods", "MathMods EMJM", "europass_required"),
    ("we-team", "WE-TEAM EMJM", "europass_required"),
    ("europubhealth-plus", "Europubhealth+", "europass_preferred"),
    ("emship", "EMSHIP EMJM", "europass_preferred"),
    ("emhrpp", "EMHRPP EMJM", "any"),
    ("comem", "CoMEM EMJM", "any"),
    ("turkiye-burslari", "Turkiye Burslari", "any"),
    ("stipendium-hungaricum", "Stipendium Hungaricum", "structured_fields_only"),
    ("nawa", "NAWA Banach", "structured_fields_only"),
    ("chevening", "Chevening", ""),
    ("fulbright", "Fulbright Foreign Student Program", ""),
    ("eiffel-excellence", "Eiffel Excellence", ""),
    ("emjm-imaging", "EMJM Imaging", "any"),
    ("mundus-journalism", "Mundus Journalism", ""),
)

#: C-002's own tolerance, in months: "some universities require a CV without
#: any omissions" is read as three months, not zero (see C-002's row below for
#: why). rule_sinks.py's `no_gaps` grammar value reads this same constant, so a
#: page saying "no gaps" is never held to a tighter bar than the seeded
#: country rule it would otherwise be outranked by (fix round 1, finding 1).
GERMAN_GAP_TOLERANCE_MONTHS = 3

# Each row's rule_text / source_url / verified_for_cycle / confidence are
# copied verbatim from the docs/research/cv-rules.csv row with that ID.
# source_url is the CSV cell with its bracketed provenance tag stripped
# ("... .pdf [downloaded, read]" -> "... .pdf") when the cell starts with a
# real URL, since URLField rejects the tag. It stays "" where the CSV cell is
# prose, not a URL (R-017, R-023, R-024, R-030, R-031, R-032, R-048).
SEED_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "R-007",
        "scope_kind": "FUNDER",
        "scope_values": ["emjm-imaging"],
        "key": "max_pages",
        "value": 2,
        "enforcement": "BINDING",
        "rule_text": "EMJM Imaging: any template allowed but max 2 pages",
        "source_url": "https://www.emjm-imaging.eu/application-and-admission/questions-and-answers/",
        "verified_for_cycle": "cycle label unconfirmed",
        "confidence": "high",
    },
    {
        "rule_id": "R-008",
        "scope_kind": "FUNDER",
        "scope_values": ["mundus-journalism"],
        "key": "max_pages",
        "value": 2,
        "enforcement": "BINDING",
        "rule_text": (
            "Mundus Journalism: CV 'no more than 2 pages'. Whole application "
            "'compiled as a single PDF file' containing items 1-8 in exact order "
            "(1 Application Form, 2 Curriculum Vitae, 3 Academic documents, "
            "4 Journalistic documents, 5 Language documents, 6 Reference letters, "
            "7 Documentation of nationality, 8 Special Needs/Chronic Illnesses/"
            "Disabilities); 'The PDF file must not exceed 10 MB'. CV is item 2, "
            "immediately after the form"
        ),
        "source_url": "https://mundusjournalism.com/admissions/application-process",
        "verified_for_cycle": (
            "2027-2029 programme; applications open 1 Nov 2026, deadline 10 Jan "
            "2026 as printed"
        ),
        "confidence": "high",
    },
    {
        "rule_id": "R-012",
        "scope_kind": "FUNDER",
        "scope_values": ["daad-study-scholarships"],
        "key": "max_pages",
        "value": 3,
        "enforcement": "BINDING",
        "rule_text": (
            "DAAD Study Scholarships: Full Resume/curriculum vitae in tabular form. "
            "(max. 3 pages) - tabular, <=3 pp. NO signature/date requirement in this "
            "checklist (that is R-031 German custom / EPOS-specific)"
        ),
        "source_url": (
            "https://static.daad.de/media/daad_de/pdfs_nicht_barrierefrei/"
            "in-deutschland-studieren-forschen-lehren/applchecklist_study_scholarship.pdf"
        ),
        "verified_for_cycle": "undated (US office) - reverify",
        "confidence": "high",
    },
    {
        "rule_id": "R-057",
        "scope_kind": "FUNDER",
        "scope_values": ["i-mesc"],
        "key": "max_pages",
        "value": 2,
        "enforcement": "BINDING",
        "rule_text": "i-MESC EMJM: Europass model, max 2 pages",
        "source_url": "https://i-mesc.eu/application/student",
        "verified_for_cycle": "Class 22, 2026-28",
        "confidence": "high",
    },
    {
        "rule_id": "R-072",
        "scope_kind": "FUNDER",
        "scope_values": ["eiffel-excellence"],
        "key": "max_pages",
        "value": 2,
        "enforcement": "BINDING",
        "rule_text": (
            "Eiffel Excellence MASTER'S track: CV in French or English, 'sur deux "
            "pages maximum' - hard 2-page cap. (The doctorate track's clause reads "
            "'une ou deux pages'; do not apply the doctorate wording to master's.) "
            "Institutional nomination only - the French host HEI submits the "
            "dossier, not the applicant"
        ),
        "source_url": (
            "https://www.campusfrance.org/system/files/medias/documents/2025-09/"
            "guide_depot_candidatures_eiffel_2026.pdf"
        ),
        "verified_for_cycle": "2026 guide (Guide de depot des candidatures Eiffel 2026)",
        "confidence": "high",
    },
    {
        "rule_id": "R-080",
        "scope_kind": "FUNDER",
        "scope_values": ["rhodes"],
        "key": "max_pages",
        "value": 2,
        "enforcement": "BINDING",
        "rule_text": (
            "Rhodes template constraints: 'your CV should not exceed 2 pages and no "
            "additional pages will be read by selectors'"
        ),
        "source_url": (
            "https://www.rhodeshouse.ox.ac.uk/media2/glifdhld/pdf-cv-template-new.pdf"
        ),
        "verified_for_cycle": "current template",
        "confidence": "high",
    },
    {
        "rule_id": "R-023",
        "scope_kind": "TRACK",
        "scope_values": ["taught"],
        "key": "max_pages",
        "value": 2,
        "enforcement": "ADVISORY_STYLE",
        "rule_text": "Taught/professional master's: default length 1-2 pages",
        "source_url": "",
        "verified_for_cycle": "evergreen",
        "confidence": "medium",
    },
    {
        "rule_id": "R-024",
        "scope_kind": "TRACK",
        "scope_values": ["research"],
        "key": "max_pages",
        "value": 3,
        "enforcement": "ADVISORY_STYLE",
        "rule_text": "Research-track master's: 2-3 pages allowed unless funder caps lower",
        "source_url": "",
        "verified_for_cycle": "evergreen",
        "confidence": "medium",
    },
    {
        "rule_id": "R-048",
        "scope_kind": "FUNDER",
        "scope_values": ["mundus-journalism"],
        "key": "max_bytes",
        "value": 10485760,
        "enforcement": "BINDING",
        "rule_text": "Respect per-package size limits (e.g. Mundus Journalism <=10 MB)",
        "source_url": "",
        "verified_for_cycle": "reverify",
        "confidence": "high",
    },
    {
        "rule_id": "R-060",
        "scope_kind": "FUNDER",
        "scope_values": ["europubhealth-plus"],
        "key": "max_bytes",
        "value": 2097152,
        "enforcement": "BINDING",
        "rule_text": "Europubhealth+: Europass PREFERRED; file <=2 MB",
        # CSV cell holds two URLs (the admission-requirements page and this
        # PDF instructions doc); the PDF is the one that states the <=2 MB
        # figure, so it is the authoritative source, not the landing page.
        "source_url": (
            "https://www.europubhealth.org/wp-content/uploads/2025/10/"
            "Instruction-2026-28_final-version-PDF.pdf"
        ),
        "verified_for_cycle": "2026-28 + 2027-29",
        "confidence": "high",
    },
    {
        "rule_id": "R-015",
        "scope_kind": "FUNDER",
        "scope_values": ["chevening"],
        "key": "max_entries_per_section",
        "value": {"education": 15, "experience": 15},
        # ADVISORY_HIGH_RISK, not BINDING: the cap governs Chevening's ONLINE
        # APPLICATION FORM fields, not the CV itself -- rule_text below says
        # so ("CV not the primary assessment doc"), and Chevening's
        # SEED_FUNDERS entry has no cv_format_requirement at all. BINDING
        # would PreflightBlocked a 16-entry CV against a rule that never
        # governed the document, with no override path (record_override only
        # accepts ADVISORY_HIGH_RISK).
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "Chevening: structured employment (<=15 entries, weeks x hours "
            "auto-calc to 2,800 hrs) and education (<=15); CV not the primary "
            "assessment doc"
        ),
        "source_url": "https://www.chevening.org/resource-hub/guidance/online-application-system/",
        "verified_for_cycle": "confirmed both passes",
        "confidence": "high",
    },
    {
        "rule_id": "R-078",
        "scope_kind": "FUNDER",
        "scope_values": ["sisgp"],
        "key": "max_entries_per_section",
        "value": {"experience": 3},
        "enforcement": "BINDING",
        "rule_text": (
            "SISGP template constraints: max 3 entries under WORK EXPERIENCE (a "
            "hard per-section ENTRY cap, not a page cap); entries may be added "
            "under other categories only while total <=3 pages; "
            "reverse-chronological within every category; 'The completed CV may "
            "not exceed 3 pages. Any pages exceeding the maximum will not be "
            "considered'; export to PDF and DELETE the template's instruction "
            "page before upload; 'Do not attach any annexes to the CV. Any other "
            "annexes will be disregarded.' Per-entry fields exceed our base "
            "schema: Industry/Sector, brief description of the organisation, and "
            "headcount supervised for leadership roles"
        ),
        "source_url": "https://si.se/app/uploads/2025/11/cv-si-scholarships-2026_2027-updated-.docx",
        "verified_for_cycle": "2026/2027",
        "confidence": "high",
    },
    {
        "rule_id": "R-032",
        "scope_kind": "COUNTRY",
        "scope_values": ["US", "CA", "GB", "AU"],
        "key": "photo_allowed",
        "value": False,
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": "US/Canada/UK/Australia: no photo, DOB, marital status, or gender",
        "source_url": "",
        "verified_for_cycle": "evergreen",
        "confidence": "high",
    },
    {
        "rule_id": "R-032",
        "scope_kind": "COUNTRY",
        "scope_values": ["US", "CA", "GB", "AU"],
        "key": "date_of_birth_allowed",
        "value": False,
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": "US/Canada/UK/Australia: no photo, DOB, marital status, or gender",
        "source_url": "",
        "verified_for_cycle": "evergreen",
        "confidence": "high",
    },
    {
        "rule_id": "R-030",
        "scope_kind": "COUNTRY",
        "scope_values": ["DE"],
        "key": "photo_allowed",
        "value": True,
        "enforcement": "ADVISORY_STYLE",
        "rule_text": (
            "Germany: professional photo customary (~4.5x6 cm top right) but not "
            "legally required (AGG 2006)"
        ),
        "source_url": "",
        "verified_for_cycle": "evergreen",
        "confidence": "medium",
    },
    {
        "rule_id": "R-031",
        "scope_kind": "COUNTRY",
        "scope_values": ["DE"],
        "key": "signature_required",
        "value": True,
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "Germany: place + current date + signature on last page for "
            "formal/scholarship CVs - German CUSTOM only. No funder verified as "
            "requiring a signature ON THE CV: DAAD EPOS requires a date of issue "
            "on the CV and an original signature only on the ST42 checklist form "
            "(R-010). Default the signature line on for German-context output, but "
            "never treat it as binding without a funder's own words"
        ),
        "source_url": "",
        "verified_for_cycle": (
            "EPOS checklist read 2nd pass; signature scope resolved 3rd pass"
        ),
        "confidence": "high",
    },
    {
        "rule_id": "R-010",
        "scope_kind": "FUNDER",
        "scope_values": ["daad-epos"],
        "key": "date_of_issue_required",
        "value": True,
        "enforcement": "BINDING",
        "rule_text": (
            "DAAD EPOS: CV in Europass format, reverse-chronological, no "
            "unexplained gaps, incl. DATE OF ISSUE (all mandatory per ST42 "
            "checklist), PDF only. NO hand-signature on the CV - the original "
            "signature is required on the ST42 checklist form itself, and on work "
            "certificates/recommendation letters, not on the CV"
        ),
        "source_url": (
            "https://static.daad.de/media/daad_de/pdfs_nicht_barrierefrei/"
            "in-deutschland-studieren-forschen-lehren/epos_checkliste.pdf"
        ),
        "verified_for_cycle": (
            "checklist read directly; signature scope resolved 2026-08-21 (3rd "
            "pass, agrees)"
        ),
        "confidence": "high",
    },
    {
        "rule_id": "R-072",
        "scope_kind": "FUNDER",
        "scope_values": ["eiffel-excellence"],
        "key": "language",
        "value": ["fr", "en"],
        "enforcement": "BINDING",
        "rule_text": (
            "Eiffel Excellence MASTER'S track: CV in French or English, 'sur deux "
            "pages maximum' - hard 2-page cap. (The doctorate track's clause reads "
            "'une ou deux pages'; do not apply the doctorate wording to master's.) "
            "Institutional nomination only - the French host HEI submits the "
            "dossier, not the applicant"
        ),
        "source_url": (
            "https://www.campusfrance.org/system/files/medias/documents/2025-09/"
            "guide_depot_candidatures_eiffel_2026.pdf"
        ),
        "verified_for_cycle": "2026 guide (Guide de depot des candidatures Eiffel 2026)",
        "confidence": "high",
    },
    {
        "rule_id": "R-079",
        "scope_kind": "FUNDER",
        "scope_values": ["sisgp"],
        "key": "required_fields",
        "value": ["sex", "date_of_birth", "citizenship"],
        "enforcement": "BINDING",
        "rule_text": (
            "SISGP mandates Sex, Date of birth (YYYY-MM-DD) and Citizenship in "
            "PERSONAL INFORMATION, as fixed template fields. This OVERRIDES the "
            "R-032 no-photo/no-DOB/no-gender default, which is a US/CA/UK/AU "
            "convention and not global. Personal-data inclusion is therefore a "
            "per-destination render decision, never a global content decision"
        ),
        "source_url": "https://si.se/app/uploads/2025/11/cv-si-scholarships-2026_2027-updated-.docx",
        "verified_for_cycle": "2026/2027",
        "confidence": "high",
    },
    {
        "rule_id": "R-017",
        "scope_kind": "FUNDER",
        "scope_values": ["fulbright"],
        "key": "prohibited_content",
        "value": ["hyperlinks"],
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "Fulbright: no hyperlinks or off-site references in the CV. Rule is "
            "codified in the Fulbright SCHOLAR (faculty/postdoc) application "
            "instructions; for the Foreign Student master's track it is prudent "
            "practice, not a documented rule - reviewers are advised not to look "
            "outside the application either way"
        ),
        "source_url": "",
        "verified_for_cycle": (
            "Scholar source, 2023 edition; Student-track transfer still "
            "undocumented"
        ),
        "confidence": "medium",
    },
    # --- Completeness, the German route's one exclusionary CV rule ----------
    #
    # C-002 in docs/superpowers/research/2026-08-27-cv-content-*.md, from a
    # primary domain. The other C- rows from that research are NOT seeded:
    # several cite scribd uploads, an agency blog and a commercial prep
    # service while labelled "Published policy (Tier 1)", and they need
    # re-verification against a primary source first.
    #
    # Three months, not zero, and the threshold is the judgement in this row:
    # uni-assist's own wording is "do not leave out any period", but a CV that
    # named every fortnight between a degree ending in June and a job starting
    # in September would be noise. Anything longer is what an admissions
    # officer asks about.
    #
    # ADVISORY_HIGH_RISK, not BINDING: uni-assist says "SOME universities
    # require a CV without any omissions", and blocking every German CV over
    # a summer would be the failure R-031 was downgraded for.
    #
    # ETH Zurich's own gapless rule (C-02, ethz.ch, binding, high confidence)
    # is deliberately absent. It is one university's rule, and scoping it to
    # COUNTRY CH would apply it to every Swiss programme; the INSTITUTION
    # scope now exists to hold it, and it can be seeded the moment
    # Institution.canonical_key for ETH is in the catalog.
    {
        "rule_id": "C-002",
        "scope_kind": "COUNTRY",
        "scope_values": ["DE"],
        "key": "no_unexplained_gaps",
        "value": GERMAN_GAP_TOLERANCE_MONTHS,
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "uni-assist: 'Some universities require a CV without any omissions which "
            "is current up to the date of application. List everything you have done "
            "up until now. Start with your first school. Do not leave out any "
            "period.' TUM asks for a CV 'without chronological gaps up to the time of "
            "your application'; DAAD asks for one 'with no chronological gaps and in "
            "tabular form'. Reported for gaps longer than three months."
        ),
        "source_url": (
            "https://www.uni-assist.de/en/how-to-apply/assemble-your-documents/"
            "other-documents/"
        ),
        "verified_for_cycle": "current site, 2026",
        "confidence": "high",
    },
    # --- AI-use policy: reported to the approving human, never a gate -------
    #
    # Sourced from docs/research/letter-rules.csv, which researched these for
    # the letter and found them stated for applications generally --
    # Cambridge's names the CV outright. Kept as reference data reaching a
    # human, exactly as the letter engine decided (letter_ai_policy.py: "never
    # a generation or approval gate"), which is what ADVISORY_HIGH_RISK is
    # for here: unverifiable from the artefact, and too serious to stay quiet
    # about.
    #
    # Three universities and two funders. Two absences are deliberate:
    # australia-awards and daad-prime carry policies (L-059, L-025) but are
    # named by no other rule, and a FUNDER scope_value not yet in the catalog
    # makes seed_cv_rules raise -- add them with the rules that need them.
    {
        "rule_id": "L-041",
        "scope_kind": "INSTITUTION",
        "scope_values": ["gb:university of cambridge"],
        "key": "ai_use_policy",
        "value": "PROHIBITS",
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "Cambridge: 'AI must not be used when writing personal statements and "
            "CVs. This prohibition covers the use of AI to help your use of English.' "
            "Hallucinated personal achievements are treated as application fraud."
        ),
        "source_url": (
            "https://www.postgraduate.study.cam.ac.uk/apply/how/ai-postgraduate-applications"
        ),
        "verified_for_cycle": "current",
        "confidence": "high",
    },
    {
        "rule_id": "L-040",
        "scope_kind": "INSTITUTION",
        "scope_values": ["gb:university of oxford"],
        "key": "ai_use_policy",
        "value": "PROHIBITS",
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "Oxford: supporting documents 'must be entirely your own work'; "
            "departments may screen with plagiarism-detection software that can also "
            "detect AI usage."
        ),
        "source_url": (
            "https://www.ox.ac.uk/admissions/graduate/application-guide/"
            "applicant-policies/plagiarism"
        ),
        "verified_for_cycle": "2025-26 guide",
        "confidence": "high",
    },
    {
        "rule_id": "L-039",
        "scope_kind": "INSTITUTION",
        "scope_values": ["gb:university of edinburgh"],
        "key": "ai_use_policy",
        "value": "PROHIBITS",
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "Edinburgh: 'Copying information from elsewhere, asking someone else to "
            "write your statement or using AI apps such as ChatGPT could be "
            "considered fraud.'"
        ),
        "source_url": "https://study.ed.ac.uk/postgraduate/applying/what/personal-statement",
        "verified_for_cycle": "current",
        "confidence": "high",
    },
    {
        "rule_id": "L-021",
        "scope_kind": "FUNDER",
        "scope_values": ["chevening"],
        "key": "ai_use_policy",
        "value": "PROHIBITS",
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "Chevening: 'Relying on AI tools to write your application will lead to "
            "rejection', and Chevening 'does not endorse or work with third parties "
            "who charge for application support or advice'."
        ),
        "source_url": "https://www.chevening.org/resource-hub/guidance/application-criteria/",
        "verified_for_cycle": "2027/28",
        "confidence": "high",
    },
    {
        "rule_id": "L-024",
        "scope_kind": "FUNDER",
        "scope_values": ["rhodes"],
        "key": "ai_use_policy",
        "value": "REQUIRES_DISCLOSURE",
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "Rhodes: the applicant attests the work is their own original "
            "experiences, thinking and judgment even where AI tools supported "
            "expression; every helper must be disclosed, and for generative AI the "
            "specific tool and the prompts used."
        ),
        "source_url": (
            "https://www.rhodeshouse.ox.ac.uk/media/5e3dzr43/"
            "generative-ai-and-help-with-your-application-guidance-for-candidates-may-2026.pdf"
        ),
        "verified_for_cycle": "May 2026",
        "confidence": "high",
    },
    {
        "rule_id": "L-025",
        "scope_kind": "FUNDER",
        "scope_values": ["daad-epos", "daad-study-scholarships"],
        "key": "ai_use_policy",
        "value": "REQUIRES_DISCLOSURE",
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "DAAD: AI 'is permitted as an aid provided that certain principles are "
            "observed' -- the applicant's own qualities must remain evident, passages "
            "carry the note 'Produced with the aid of (tool used)', and a Declaration "
            "of Authenticity states the application was prepared independently."
        ),
        "source_url": (
            "https://www.daad.de/en/studying-in-germany/scholarships/"
            "information-for-scholarship-applicants/"
        ),
        "verified_for_cycle": "2026",
        "confidence": "high",
    },
)


def _assert_no_same_scope_conflict(rows: tuple[dict[str, Any], ...]) -> None:
    """Two rules of the same scope setting the same key is a data error.

    The resolver would have to pick one, and picking silently is how a
    funder's rule quietly stops applying.
    """
    seen: dict[tuple[str, str, str], str] = {}
    for row in rows:
        for value in row["scope_values"] or [""]:
            slot = (row["scope_kind"], value, row["key"])
            if slot in seen:
                raise ValueError(
                    f"{row['rule_id']} and {seen[slot]} both set {row['key']!r} "
                    f"for {row['scope_kind']} {value!r}"
                )
            seen[slot] = row["rule_id"]


@transaction.atomic
def seed_cv_rules() -> tuple[int, int, int]:
    """Load SEED_RULES into the catalog. Returns (created, updated, deleted)."""
    from apps.funding.models import CatalogRule, FundingOpportunity

    _assert_no_same_scope_conflict(SEED_RULES)
    # Set the format requirement on funders that already exist. This seed
    # deliberately does NOT create FundingOpportunity rows: that model requires
    # `family` and `scope_type`, and this research establishes neither. The
    # taxonomy does not even fit -- Rhodes is a private trust, so
    # GOVERNMENT_SCHOLARSHIP and MULTILATERAL are both false about it, and a
    # catalog row asserting one would be invented data in the one place this
    # system exists not to invent things. Funder rows come from the discovery
    # pipeline; this seed only annotates them.
    for canonical_key, _name, requirement in SEED_FUNDERS:
        if not requirement:
            continue
        # funding_fundingopportunity carries the same SELECT-only
        # shared_catalog_select RLS policy as funding_catalogrule, so an
        # UPDATE under the wrong DB role matches no rows and returns 0 --
        # silently. A 0 count is only a write failure when the row actually
        # exists; a funder in SEED_FUNDERS that isn't in the catalog yet is a
        # legitimate 0-match, and the `missing` check below already reports
        # that case.
        matched = FundingOpportunity.objects.filter(canonical_key=canonical_key)
        if not matched.exists():
            continue
        update_exactly(
            matched,
            error=(
                "catalog write affected no rows -- run this under "
                "DATABASE_ROLE=runtime_engine; no other role can update "
                "funding_fundingopportunity"
            ),
            cv_format_requirement=requirement,
        )
    named = {
        value
        for row in SEED_RULES
        for value in row["scope_values"]
        if row["scope_kind"] == "FUNDER"
    }
    missing = named - set(
        FundingOpportunity.objects.filter(canonical_key__in=named).values_list(
            "canonical_key", flat=True
        )
    )
    if missing:
        raise ValueError(
            f"rules scope to funders not in the catalog: {sorted(missing)} -- "
            "load them through the discovery pipeline before seeding rules"
        )
    allowed = set(get_args(_CONSTRAINT_KEYS))
    for row in SEED_RULES:
        if row["key"] not in allowed:
            raise ValueError(f"{row['rule_id']} uses unknown constraint key {row['key']!r}")

    created = updated = 0
    kept: list[Any] = []
    for row in SEED_RULES:
        # Keyed on (rule_id, key), NOT rule_id alone -- that is the table's
        # unique constraint, and the difference is not cosmetic. R-032 appears
        # twice in SEED_RULES (photo_allowed, date_of_birth_allowed) and R-072
        # twice (max_pages, language). Keyed on rule_id alone, each pair's
        # second row UPDATES the first instead of inserting: the catalog ends
        # with 18 rows where 20 are specified, photo_allowed and max_pages
        # silently gone, and the idempotency test still green.
        lookup = {"rule_id": row["rule_id"], "key": row["key"]}
        defaults = {k: v for k, v in row.items() if k not in lookup}
        existing = CatalogRule.objects.filter(**lookup).first()
        if existing is None:
            kept.append(CatalogRule.objects.create(**lookup, **defaults).pk)
            created += 1
            continue
        kept.append(existing.pk)
        if any(getattr(existing, field) != value for field, value in defaults.items()):
            # Check the row count, via update_exactly. Under the SELECT-only
            # shared_catalog_select policy an INSERT raises, but an UPDATE
            # simply matches no rows and returns 0 -- a write that looks fine
            # and silently did nothing. That is the one failure mode the
            # command's own zero-write guard cannot see, because a populated
            # table makes `_any_rules()` true.
            update_exactly(
                CatalogRule.objects.filter(pk=existing.pk),
                error=(
                    "catalog write affected no rows -- run this under "
                    "DATABASE_ROLE=runtime_engine; no other role can update "
                    "funding_catalogrule"
                ),
                **defaults,
            )
            updated += 1
    deleted, _ = CatalogRule.objects.exclude(pk__in=kept).delete()
    return created, updated, deleted
