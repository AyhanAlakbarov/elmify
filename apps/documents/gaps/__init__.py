"""The counsellor's review: what the ledger is missing, and what it cannot hold.

Modularised package holding deterministic gap detectors, question models, note
generation, answer ingestion, and gap orchestrator.
"""

from __future__ import annotations

import sys
import types

from apps.documents.constraints import ConstraintRule, PageDirective, directives_from_program
from apps.documents.cv_fixes import (
    ABBREVIATED_NAME,
    TITLE_MAX,
    abbreviated_degree,
    abbreviated_institution,
    full_title_for,
    remember_revert,
    reverted_subjects,
    subject_of,
)
from apps.documents.dates import parse_cv_date
from apps.documents.models import VerifiedFact
from apps.documents.schemas import TIMELINE_STATEMENT_MAX, TimelineEntry, open_span_end
from apps.documents.verification import (
    disowned_refs,
    has_full_name,
    payload_keys,
    unsuperseded_facts,
)
from apps.funding.models import Program
from apps.tenancy.models import Membership

from . import answers, models, notes, orchestrator
from .answers import _LIST_KEYS, answer_questions
from .detectors import academics, profile, requirements, timeline
from .detectors.academics import (
    _degree_complete,
    _most_recent_degree,
    education_completeness,
    missing_degree_detail,
    missing_grade,
    missing_medium_of_instruction,
)
from .detectors.profile import (
    _CONTACT_FIELDS,
    _NAME_PART_KEYS,
    _NAME_PART_PROMPTS,
    NAME_PART_MAX,
    abbreviated_names,
    missing_contact,
    name_parts,
)
from .detectors.requirements import (
    _active_draft_programme_questions,
    _is_research_applicant,
    _programme_directives_questions,
    _upper_secondary_from_rules,
    absent_sections,
    incomplete_entry,
    missing_award,
    missing_language_detail,
    missing_publication_detail,
    programme_required,
    upper_secondary_required,
)
from .detectors.timeline import (
    _MIN_GAP_DAYS,
    _read_date,
    _timeline_question,
    timeline_gaps,
)
from .models import (
    _GROUP_DEFAULTS,
    _GROUPS,
    _TARGET_CATEGORY,
    GapNote,
    GapQuestion,
    Kind,
    UnanswerableQuestion,
    _already_created,
    _current,
    _cv_on_file,
    _group_questions,
)
from .notes import _CERTIFICATES_NOTE, gap_notes
from .orchestrator import gap_questions

__all__ = [
    "ABBREVIATED_NAME",
    "ConstraintRule",
    "GapNote",
    "GapQuestion",
    "Kind",
    "Membership",
    "NAME_PART_MAX",
    "PageDirective",
    "Program",
    "TIMELINE_STATEMENT_MAX",
    "TITLE_MAX",
    "TimelineEntry",
    "UnanswerableQuestion",
    "VerifiedFact",
    "_CERTIFICATES_NOTE",
    "_CONTACT_FIELDS",
    "_GROUP_DEFAULTS",
    "_GROUPS",
    "_LIST_KEYS",
    "_MIN_GAP_DAYS",
    "_NAME_PART_KEYS",
    "_NAME_PART_PROMPTS",
    "_TARGET_CATEGORY",
    "_active_draft_programme_questions",
    "_already_created",
    "_current",
    "_cv_on_file",
    "_degree_complete",
    "_group_questions",
    "_is_research_applicant",
    "_most_recent_degree",
    "_programme_directives_questions",
    "_read_date",
    "_timeline_question",
    "_upper_secondary_from_rules",
    "abbreviated_degree",
    "abbreviated_institution",
    "abbreviated_names",
    "absent_sections",
    "answer_questions",
    "directives_from_program",
    "disowned_refs",
    "education_completeness",
    "full_title_for",
    "gap_notes",
    "gap_questions",
    "has_full_name",
    "incomplete_entry",
    "missing_award",
    "missing_contact",
    "missing_degree_detail",
    "missing_grade",
    "missing_language_detail",
    "missing_medium_of_instruction",
    "missing_publication_detail",
    "name_parts",
    "open_span_end",
    "parse_cv_date",
    "payload_keys",
    "programme_required",
    "remember_revert",
    "reverted_subjects",
    "subject_of",
    "timeline_gaps",
    "unsuperseded_facts",
    "upper_secondary_required",
]


class _GapsModule(types.ModuleType):
    """Module proxy that synchronizes attribute mutations (e.g. pytest monkeypatching)
    to the underlying submodules where functions read their globals."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        submodules = (
            answers,
            models,
            notes,
            orchestrator,
            academics,
            profile,
            requirements,
            timeline,
        )
        for sub in submodules:
            if hasattr(sub, name) and getattr(sub, name, None) is not value:
                try:
                    setattr(sub, name, value)
                except AttributeError:
                    pass

    def __delattr__(self, name: str) -> None:
        super().__delattr__(name)
        submodules = (
            answers,
            models,
            notes,
            orchestrator,
            academics,
            profile,
            requirements,
            timeline,
        )
        for sub in submodules:
            if hasattr(sub, name):
                try:
                    delattr(sub, name)
                except AttributeError:
                    pass


sys.modules[__name__].__class__ = _GapsModule
