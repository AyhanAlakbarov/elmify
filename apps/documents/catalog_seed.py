"""The researched CV, CV-style, and motivation-letter rule catalog seed.

Combines the hand-curated core rules (`_CURATED_SEED_RULES`) with a
deterministic compiler (`compile_csv_seed_rules`) that loads every remaining
verified rule carrying a primary `https://` URL from:
- `docs/research/cv-rules.csv`
- `docs/research/cv-style-rules.csv`
- `docs/research/letter-rules.csv`
paired with `docs/research/rule-grammar-map.csv`.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, get_args

from django.db import transaction

from .constraints import _CONSTRAINT_KEYS, _MULTI_KEYS, QUOTE_MAX_CHARS

_RESEARCH_DIR = Path(__file__).resolve().parents[2] / "docs" / "research"
_URL_RE = re.compile(r"https://[^\s;\]\"]+")

#: Every funder a rule is scoped to, and the CV format that funder mandates.
#: canonical_key is FundingOpportunity's unique key, so these strings are the
#: same ones SEED_RULES scopes against. "" means the funder states no format.
#
# Note on EUROPASS_API + date_of_issue_required and FUNDER_TEMPLATE dispatch:
# - "daad-epos": europass_required -> EUROPASS_API, and R-010 seeds
#   date_of_issue_required=True as BINDING. The local preview path
#   (allow_network=False) passes date_of_issue so cv_europass.html satisfies
#   R-010; the live europa.eu API (allow_network=True) has no date-of-issue
#   field, so _blocked_by_content_only_rules stops PII egress when a BINDING
#   date_of_issue_required is active.
# - "rhodes", "sisgp", and "australia-awards": render_draft derives
#   funder_template_id ("RHODES", "SISGP", "AUSTRALIA_AWARDS") from
#   draft.funding_opportunity.canonical_key via _funder_template_id_for_draft.
#   "australia-awards" stays "" in SEED_FUNDERS because country programmes
#   vary between OASIS portal fields and the country-localised DFAT .docx
#   template (R-065); funder_templates/australia_awards.py supports both PDF
#   rendering and Word FORMTEXT .docx form-filling (R-083).
SEED_FUNDERS: tuple[tuple[str, str, str], ...] = (
    ("rhodes", "Rhodes Scholarship", "funder_template"),
    ("sisgp", "Swedish Institute Scholarships for Global Professionals", "funder_template"),
    ("australia-awards", "Australia Awards", ""),
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
    ("nawa-pmfc", "NAWA Poland My First Choice", "structured_fields_only"),
    ("chevening", "Chevening", ""),
    ("fulbright", "Fulbright Foreign Student Program", ""),
    ("eiffel-excellence", "Eiffel Excellence", ""),
    ("emjm-imaging", "EMJM Imaging", "any"),
    ("mundus-journalism", "Mundus Journalism", ""),
    ("erasmus-mundus", "Erasmus Mundus Joint Masters", ""),
    ("swiss-eskas", "Swiss Government Excellence Scholarships (ESKAS)", ""),
    ("gates-cambridge", "Gates Cambridge Scholarship", ""),
    ("vlir-uos", "VLIR-UOS ICP Connect", ""),
    ("csc", "Chinese Government Scholarship (CSC)", ""),
    ("mext", "Japanese Government (MEXT) Scholarship", ""),
    ("gks", "Global Korea Scholarship (GKS)", ""),
    ("commonwealth", "Commonwealth Master's Scholarships", ""),
    ("maeci", "Italian Government (MAECI) Scholarship", ""),
    ("russia-open-doors", "Russia Open Doors Olympiad", ""),
    ("europass", "Europass Framework", ""),
    ("campus-france", "Campus France Etudes en France", ""),
    ("gradcas", "Liaison GradCAS / SOPHAS", ""),
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
_CURATED_SEED_RULES: tuple[dict[str, Any], ...] = (
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
        "rule_id": "R-078",
        "scope_kind": "FUNDER",
        "scope_values": ["sisgp"],
        "key": "max_pages",
        "value": 3,
        "enforcement": "BINDING",
        "rule_text": (
            "SISGP template constraints: 'The completed CV may not exceed 3 pages. "
            "Any pages exceeding the maximum will not be considered'"
        ),
        "source_url": "https://si.se/app/uploads/2025/11/cv-si-scholarships-2026_2027-updated-.docx",
        "verified_for_cycle": "2026/2027",
        "confidence": "high",
    },
    {
        "rule_id": "R-082",
        "scope_kind": "INSTITUTION",
        "scope_values": ["gb:university of cambridge"],
        "key": "max_bytes",
        "value": 2097152,
        "enforcement": "BINDING",
        "rule_text": (
            "University of Cambridge postgraduate admissions (including Gates "
            "Cambridge): all supporting documents must be 'under 2MB'"
        ),
        "source_url": "https://www.postgraduate.study.cam.ac.uk/apply/how/supporting-documents",
        "verified_for_cycle": "current site",
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
    {
        "rule_id": "S-047",
        "scope_kind": "INSTITUTION",
        "scope_values": ["ch:eth zurich", "de:technical university of munich"],
        "key": "no_unexplained_gaps",
        "value": GERMAN_GAP_TOLERANCE_MONTHS,
        "enforcement": "BINDING",
        "rule_text": (
            "ETH Zurich: 'Leave no time gaps: also list periods when you did not "
            "attend school, study or work (e.g. longer periods of travel or time "
            "off).' TUM style guide: the tabular CV 'must not contain any gaps "
            "longer than 3 months' after leaving school."
        ),
        "source_url": (
            "https://ethz.ch/applications/teaching/en/applications/eapply/msc/mscsummary.html"
        ),
        "verified_for_cycle": "2026",
        "confidence": "high",
    },
    {
        "rule_id": "S-047",
        "scope_kind": "INSTITUTION",
        "scope_values": ["ch:eth zurich"],
        "key": "cv_scope",
        "value": "complete",
        "enforcement": "BINDING",
        "rule_text": (
            "ETH Zurich: 'Please upload an up-to-date, chronological curriculum "
            "vitae in table form, leaving nothing out. Begin with your upper "
            "secondary school graduation and include all details right up to the "
            "time of application.'"
        ),
        "source_url": (
            "https://ethz.ch/applications/teaching/en/applications/eapply/msc/mscsummary.html"
        ),
        "verified_for_cycle": "2026",
        "confidence": "high",
    },
    {
        "rule_id": "S-047",
        "scope_kind": "INSTITUTION",
        "scope_values": ["ch:eth zurich"],
        "key": "cv_start",
        "value": {"start": "upper_secondary"},
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "ETH Zurich: 'Begin with your upper secondary school graduation and "
            "include all details right up to the time of application, with exact "
            "entries regarding your education (schools attended, studies etc.).'"
        ),
        "source_url": (
            "https://ethz.ch/applications/teaching/en/applications/eapply/msc/mscsummary.html"
        ),
        "verified_for_cycle": "2026",
        "confidence": "high",
    },
    {
        "rule_id": "S-047",
        "scope_kind": "INSTITUTION",
        "scope_values": ["de:technical university of munich"],
        "key": "font",
        "value": "Times New Roman or Arial, 12 point",
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": (
            "TUM application style guide: PDF, A4, 'Times New Roman or Arial', "
            "'12 point', margins '2 centimeters', line spacing '1.5-fold', "
            "'chronological and tabular'."
        ),
        "source_url": (
            "https://www.tum.de/en/studies/application/application-info-portal/"
            "document-requirements/tum-style-guide"
        ),
        "verified_for_cycle": "2026",
        "confidence": "high",
    },
    {
        "rule_id": "S-047",
        "scope_kind": "INSTITUTION",
        "scope_values": ["de:technical university of munich"],
        "key": "date_of_birth_allowed",
        "value": True,
        "enforcement": "ADVISORY_STYLE",
        "rule_text": (
            "TUM application style guide: personal details on the tabular CV "
            "include first name, surname and date of birth."
        ),
        "source_url": (
            "https://www.tum.de/en/studies/application/application-info-portal/"
            "document-requirements/tum-style-guide"
        ),
        "verified_for_cycle": "2026",
        "confidence": "high",
    },
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

#: Scope mapping for the remaining researched CSV rows (keyed by CSV `Scope` text
#: or explicit `rule_id` when a prose scope names a specific institution/funder).
_CSV_SCOPE_BY_RULE_ID: dict[str, tuple[str, list[str]]] = {
    "R-003": ("FUNDER", ["amir"]),
    "R-004": ("FUNDER", ["membiomed"]),
    "R-005": ("FUNDER", ["steps"]),
    "R-006": ("FUNDER", ["emhrpp"]),
    "R-009": ("FUNDER", ["erasmus-mundus"]),
    "R-011": ("FUNDER", ["daad-prime"]),
    "R-013": ("FUNDER", ["daad-epos", "daad-study-scholarships", "daad-prime"]),
    "R-014": ("FUNDER", ["swiss-eskas"]),
    "R-018": ("FUNDER", ["gates-cambridge"]),
    "R-019": ("FUNDER", ["gradcas"]),
    "R-020": ("COUNTRY", ["DE"]),
    "R-022": ("COUNTRY", ["GB"]),
    "R-033": ("FUNDER", ["europass"]),
    "R-047": ("FUNDER", ["daad-epos", "daad-study-scholarships", "daad-prime"]),
    "R-053": ("FUNDER", ["europass"]),
    "R-056": ("FUNDER", ["globed"]),
    "R-058": ("FUNDER", ["mathmods"]),
    "R-059": ("FUNDER", ["we-team"]),
    "R-061": ("FUNDER", ["europubhealth-plus"]),
    "R-062": ("FUNDER", ["emship"]),
    "R-063": ("FUNDER", ["comem"]),
    "R-064": ("FUNDER", ["sisgp"]),
    "R-065": ("FUNDER", ["australia-awards"]),
    "R-066": ("FUNDER", ["rhodes"]),
    "R-067": ("FUNDER", ["campus-france"]),
    "R-068": ("COUNTRY", ["SE"]),
    "R-069": ("COUNTRY", ["DE"]),
    "R-070": ("FUNDER", ["daad-epos", "i-mesc"]),
    "R-073": ("FUNDER", ["stipendium-hungaricum"]),
    "R-075": ("FUNDER", ["turkiye-burslari"]),
    "R-076": ("FUNDER", ["nawa", "nawa-pmfc"]),
    "R-077": ("FUNDER", ["vlir-uos"]),
    "R-083": ("FUNDER", ["australia-awards", "rhodes", "sisgp"]),
    "R-084": ("FUNDER", ["europass"]),
    "R-085": ("TRACK", ["taught", "research"]),
    "R-087": ("INSTITUTION", ["gb:university of cambridge"]),
    "R-088": ("INSTITUTION", ["gb:university of cambridge"]),
    "R-089": ("FUNDER", ["gates-cambridge"]),
    "R-090": ("INSTITUTION", ["gb:university of oxford"]),
    "R-091": ("FUNDER", ["chevening"]),
    "S-007": ("COUNTRY", ["US", "CA", "GB", "AU", "FR", "NL", "SE", "IT", "ES", "FI", "NO", "DK"]),
    "S-008": ("COUNTRY", ["DE", "AT", "CH"]),
    "S-013": ("TRACK", ["research"]),
    "S-017": ("COUNTRY", ["FR"]),
    "S-018": ("COUNTRY", ["NL", "SE", "NO", "DK", "FI"]),
    "S-019": ("COUNTRY", ["JP"]),
    "S-020": ("COUNTRY", ["TR", "AZ"]),
    "S-021": ("COUNTRY", ["GB", "IE"]),
    "S-030": ("TRACK", ["research"]),
    "S-039": ("TRACK", ["taught", "research"]),
    "S-043": ("COUNTRY", ["GB"]),
    "S-044": ("COUNTRY", ["GB"]),
    "S-048": ("COUNTRY", ["US"]),
    "L-001": ("COUNTRY", ["AU"]),
    "L-002": ("COUNTRY", ["AU"]),
    "L-003": ("COUNTRY", ["AU"]),
    "L-004": ("COUNTRY", ["AU"]),
    "L-005": ("COUNTRY", ["AU"]),
    "L-006": ("COUNTRY", ["AU"]),
    "L-007": ("COUNTRY", ["AU"]),
    "L-008": ("FUNDER", ["csc"]),
    "L-009": ("FUNDER", ["csc"]),
    "L-010": ("FUNDER", ["csc"]),
    "L-011": ("FUNDER", ["mext"]),
    "L-012": ("FUNDER", ["mext"]),
    "L-013": ("FUNDER", ["mext"]),
    "L-014": ("FUNDER", ["mext"]),
    "L-015": ("FUNDER", ["gks"]),
    "L-016": ("FUNDER", ["gks"]),
    "L-017": ("FUNDER", ["gks"]),
    "L-018": ("FUNDER", ["gks"]),
    "L-019": ("FUNDER", ["australia-awards"]),
    "L-020": ("FUNDER", ["chevening"]),
    "L-022": ("FUNDER", ["gates-cambridge"]),
    "L-023": ("FUNDER", ["rhodes"]),
    "L-026": ("FUNDER", ["daad-study-scholarships"]),
    "L-027": ("FUNDER", ["daad-epos"]),
    "L-028": ("FUNDER", ["daad-epos", "daad-study-scholarships", "daad-prime"]),
    "L-029": ("FUNDER", ["commonwealth"]),
    "L-030": ("FUNDER", ["fulbright"]),
    "L-031": ("FUNDER", ["stipendium-hungaricum"]),
    "L-032": ("FUNDER", ["turkiye-burslari"]),
    "L-033": ("FUNDER", ["swiss-eskas"]),
    "L-034": ("FUNDER", ["eiffel-excellence"]),
    "L-035": ("FUNDER", ["campus-france"]),
    "L-036": ("FUNDER", ["maeci"]),
    "L-037": ("FUNDER", ["erasmus-mundus"]),
    "L-038": ("INSTITUTION", ["gb:university college london"]),
    "L-042": ("INSTITUTION", ["gb:university of cambridge"]),
    "L-043": ("INSTITUTION", ["gb:university of cambridge"]),
    "L-044": (
        "INSTITUTION",
        [
            "gb:imperial college london",
            "gb:london school of economics",
            "gb:university of manchester",
        ],
    ),
    "L-045": ("INSTITUTION", ["us:university of california, berkeley"]),
    "L-046": ("INSTITUTION", ["us:university of california, los angeles"]),
    "L-047": ("INSTITUTION", ["us:university of michigan"]),
    "L-048": ("INSTITUTION", ["ca:university of toronto"]),
    "L-049": ("COUNTRY", ["DE", "AT", "CH"]),
    "L-050": ("INSTITUTION", ["de:technical university of munich"]),
    "L-051": (
        "INSTITUTION",
        [
            "de:lmu munich",
            "nl:university of groningen",
            "fi:university of helsinki",
            "no:university of oslo",
            "dk:aarhus university",
        ],
    ),
    "L-052": ("INSTITUTION", ["fi:aalto university"]),
    "L-053": ("INSTITUTION", ["se:kth royal institute of technology"]),
    "L-054": ("COUNTRY", ["SE", "NO", "DK", "FI", "NL"]),
    "L-055": ("INSTITUTION", ["nl:leiden university"]),
    "L-056": (
        "INSTITUTION",
        [
            "nl:delft university of technology",
            "nl:university of amsterdam",
            "nl:utrecht university",
            "nl:university of groningen",
        ],
    ),
    "L-057": ("COUNTRY", ["DE"]),
    "L-058": ("COUNTRY", ["CA"]),
    "L-059": ("FUNDER", ["australia-awards"]),
    "L-060": ("COUNTRY", ["GB"]),
    "L-066": ("FUNDER", ["russia-open-doors"]),
    "L-068": ("FUNDER", ["chevening"]),
    "L-069": ("INSTITUTION", ["us:cornell university"]),
    "L-070": ("INSTITUTION", ["gb:university of cambridge"]),
    "L-071": ("COUNTRY", ["AU"]),
    "L-072": ("TRACK", ["taught", "research"]),
}

#: Structured (key, value, enforcement) overrides for CSV rules that express a
#: direct typed constraint on a non-conflicting scope slot.
_STRUCTURED_CSV_SPEC_BY_RULE_ID: dict[str, tuple[tuple[str, Any, str], ...]] = {
    "R-004": (("required_fields", ["date_of_birth"], "BINDING"),),
    "R-011": (("no_unexplained_gaps", GERMAN_GAP_TOLERANCE_MONTHS, "BINDING"),),
    "R-014": (("cv_scope", "complete", "BINDING"),),
    "R-033": (("photo_allowed", True, "ADVISORY_STYLE"),),
    "R-067": (("max_bytes", 2097152, "ADVISORY_HIGH_RISK"),),
    "R-089": (("ai_use_policy", "PROHIBITS", "ADVISORY_HIGH_RISK"),),
    "S-017": (("max_pages", 2, "ADVISORY_STYLE"),),
    "S-018": (("max_pages", 2, "ADVISORY_STYLE"),),
    "S-022": (("min_final_page_fill", 0.2, "ADVISORY_STYLE"),),
    "L-002": (("max_words", 150, "ADVISORY_STYLE"),),
    "L-003": (("language", ["en"], "ADVISORY_STYLE"),),
    "L-008": (
        ("min_words", 800, "ADVISORY_STYLE"),
        ("language", ["zh", "en"], "BINDING"),
    ),
    "L-012": (
        ("max_pages", 2, "BINDING"),
        ("language", ["ja", "en"], "BINDING"),
    ),
    "L-013": (("ai_use_policy", "PROHIBITS", "ADVISORY_HIGH_RISK"),),
    "L-016": (("max_chars_incl_spaces", 17000, "ADVISORY_STYLE"),),
    "L-019": (("max_chars_incl_spaces", 2000, "ADVISORY_STYLE"),),
    "L-020": (
        ("max_words", 500, "ADVISORY_STYLE"),
        ("min_words", 100, "ADVISORY_STYLE"),
    ),
    "L-022": (("max_chars_incl_spaces", 3000, "ADVISORY_STYLE"),),
    "L-023": (("max_words", 1000, "ADVISORY_STYLE"),),
    "L-029": (("max_words", 500, "ADVISORY_STYLE"),),
    "L-031": (
        ("font", "Times New Roman, 12 point", "ADVISORY_HIGH_RISK"),
        ("language", ["en", "hu"], "BINDING"),
    ),
    "L-032": (
        ("max_chars_incl_spaces", 3000, "ADVISORY_STYLE"),
        ("language", ["tr", "ar", "en", "fr", "ru", "bs", "fa", "es"], "BINDING"),
    ),
    "L-033": (
        ("max_pages", 2, "BINDING"),
        ("language", ["en", "fr", "de", "it"], "BINDING"),
    ),
    "L-035": (("max_chars_incl_spaces", 2500, "ADVISORY_STYLE"),),
    "L-036": (("max_words", 500, "ADVISORY_STYLE"),),
    "L-037": (("max_words", 600, "ADVISORY_STYLE"),),
    "L-038": (
        ("max_chars_incl_spaces", 3000, "ADVISORY_STYLE"),
        ("max_pages", 2, "BINDING"),
    ),
    "L-044": (("max_words", 1500, "ADVISORY_STYLE"),),
    "L-046": (("max_words", 500, "ADVISORY_STYLE"),),
    "L-047": (("max_words", 1000, "ADVISORY_STYLE"),),
    "L-048": (("max_words", 750, "ADVISORY_STYLE"),),
    "L-053": (
        ("max_words", 500, "ADVISORY_STYLE"),
        ("language", ["en"], "BINDING"),
    ),
    "L-055": (("max_words", 500, "ADVISORY_STYLE"),),
    "L-056": (("max_words", 500, "ADVISORY_STYLE"),),
    "L-059": (("ai_use_policy", "PROHIBITS", "ADVISORY_HIGH_RISK"),),
    "L-066": (("language", ["ru", "en"], "ADVISORY_HIGH_RISK"),),
    "L-068": (("language", ["en"], "BINDING"),),
    "L-069": (("max_pages", 2, "ADVISORY_STYLE"),),
}


def _clip_rule_text(raw_text: str) -> str:
    """Normalize whitespace and clip CSV rule text to `QUOTE_MAX_CHARS`."""
    return " ".join((raw_text or "").split())[:QUOTE_MAX_CHARS]


def _extract_source_url(raw_cell: str) -> str:
    """Return the first `https://` URL from a CSV provenance cell, or `""`."""
    matches: list[str] = _URL_RE.findall(raw_cell or "")
    if not matches:
        return ""
    return matches[0].rstrip(".,;)]")


def _normalize_confidence(raw_confidence: str) -> str:
    """Normalize CSV confidence text into `high`, `medium`, or `low`."""
    lowered = (raw_confidence or "").strip().lower()
    if lowered.startswith("high"):
        return "high"
    if lowered.startswith("low"):
        return "low"
    return "medium"


def _resolve_csv_scope(rule_id: str, raw_scope: str) -> tuple[str, list[str]]:
    if rule_id in _CSV_SCOPE_BY_RULE_ID:
        kind, values = _CSV_SCOPE_BY_RULE_ID[rule_id]
        return kind, list(values)
    lowered = (raw_scope or "").strip().lower()
    if lowered.startswith("universal") or "job-application ats" in lowered:
        return "UNIVERSAL", []
    raise ValueError(f"Unmapped CSV scope {raw_scope!r} for rule {rule_id}")


def _load_grammar_map(research_dir: Path) -> dict[str, list[tuple[str, str, str, str]]]:
    mapping: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    map_path = research_dir / "rule-grammar-map.csv"
    if not map_path.exists():
        return mapping
    with map_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            mapping[row["rule_id"].strip()].append(
                (
                    row["document"].strip(),
                    row["operation"].strip(),
                    row["value"].strip(),
                    row["bound"].strip(),
                )
            )
    return mapping


def compile_csv_seed_rules(research_dir: Path = _RESEARCH_DIR) -> tuple[dict[str, Any], ...]:
    """Compile verified `https://` rules from the three research CSVs."""
    curated_ids = {row["rule_id"] for row in _CURATED_SEED_RULES}
    grammar_map = _load_grammar_map(research_dir)
    compiled: list[dict[str, Any]] = []

    catalog_files = (
        ("cv-rules.csv", "cv"),
        ("cv-style-rules.csv", "cv"),
        ("letter-rules.csv", "motivation_letter"),
    )
    for filename, default_doc in catalog_files:
        csv_path = research_dir / filename
        if not csv_path.exists():
            continue
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                rule_id = row["ID"].strip()
                if not rule_id or rule_id in curated_ids:
                    continue
                source_url = _extract_source_url(row.get("Source URL [provenance]", ""))
                if not source_url:
                    continue

                scope_kind, scope_values = _resolve_csv_scope(
                    rule_id, row.get("Scope", "")
                )
                rule_text = _clip_rule_text(row.get("Rule", ""))
                verified_for_cycle = (row.get("Verified for cycle", "") or "").strip()[:200]
                confidence = _normalize_confidence(row.get("Confidence", ""))
                binding_col = (row.get("Binding or advisory", "") or "").strip().lower()

                if rule_id in _STRUCTURED_CSV_SPEC_BY_RULE_ID:
                    specs = _STRUCTURED_CSV_SPEC_BY_RULE_ID[rule_id]
                else:
                    g_entries = grammar_map.get(rule_id) or [(default_doc, "other", "", "")]
                    doc, op, _val, _bound = g_entries[0]
                    doc_label = doc if doc in ("cv", "motivation_letter") else default_doc
                    op_label = op or "other"
                    if scope_kind in ("FUNDER", "INSTITUTION") and binding_col.startswith(
                        "binding"
                    ):
                        enforcement = "ADVISORY_HIGH_RISK"
                    else:
                        enforcement = "ADVISORY_STYLE"
                    specs = (("unapplied", f"{doc_label}:{op_label}", enforcement),)

                for key, value, enforcement in specs:
                    compiled.append(
                        {
                            "rule_id": rule_id,
                            "scope_kind": scope_kind,
                            "scope_values": list(scope_values),
                            "key": key,
                            "value": value,
                            "enforcement": enforcement,
                            "rule_text": rule_text,
                            "source_url": source_url,
                            "verified_for_cycle": verified_for_cycle,
                            "confidence": confidence,
                        }
                    )

    return tuple(compiled)


SEED_RULES: tuple[dict[str, Any], ...] = (
    *_CURATED_SEED_RULES,
    *compile_csv_seed_rules(),
)


def _assert_no_same_scope_conflict(rows: tuple[dict[str, Any], ...]) -> None:
    """Two rules of the same scope setting the same key is a data error.

    The resolver would have to pick one, and picking silently is how a
    funder's rule quietly stops applying. Multi-quote keys (`unapplied`,
    `undecided`) are never deduplicated by key in `requirement_list.merge`.
    """
    seen: dict[tuple[str, str, str], str] = {}
    for row in rows:
        if row["key"] in _MULTI_KEYS:
            continue
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
    from apps.funding.models import CatalogRule, FundingOpportunity, update_exactly

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


seed_catalog_constraints = seed_cv_rules
