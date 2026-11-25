"""Dynamic disciplinary few-shot exemplars and Question-Focus unit planning.

Implements Pillar 1 and Pillar 3 (Pass 1) from
`.context/research/2026-11-18-scilit-motivation-letter-three-pillars.md`:

1. **Zero-Network Disciplinary Routing (`resolve_rhetorical_discipline`)**:
   Routes the target programme and the student's confirmed ledger facts through
   `apps.accounts.field_taxonomy.resolve_field_taxonomy` into five
   macro-disciplinary rhetorical clusters established by ESP genre move analysis
   (Samraj & Monk 2008, `10.1016/j.esp.2007.07.001`; Chiu 2016,
   `10.1016/j.jeap.2015.11.001`; Ding 2007, `10.1016/j.esp.2006.09.004`;
   Bi 2017, `10.1186/s40554-017-0041-9`; López-Ferrero & Bach 2016,
   `10.1177/1461445616634553`).

2. **Delexicalized `Trial-Error-Explain` Move-Cadence Exemplars
   (`select_exemplars_for_letter`)**:
   Follows Cho et al. (2025, NAACL Findings, `10.18653/v1/2025.findings-naacl.326`,
   *Trial-Error-Explain In-Context Learning*), Dang et al. (2025, CHI,
   `10.1145/3706598.3713974`, *CorpusStudio*), and Shin et al. (2026, EMNLP,
   `10.18653/2026.emnlp-main.1045`, *HyperStyler*). Rather than injecting raw
   domain prose paragraphs—which cause lexical copying, foreign entity leakage,
   and cross-applicant homogenization (`check_cohort_overlap`)—each exemplar
   pairs a delexicalized negative trial, a diagnostic explanation, a positive
   slot-placeholder move pattern, and an explicit sentence-length cadence target.

3. **Pass 1 Question-Focus Discourse Structuring (`build_question_focus_plan`)**:
   Follows Wang et al. (2025, EMNLP, `10.18653/v1/2025.emnlp-main.416`,
   *Question-Focus Discourse Structuring*), Slobodkin et al. (2024, ACL,
   `10.18653/v1/2024.acl-long.182`, *Attribute First, then Generate*), and
   Gupta & Bedi (2026, ACL RAG4Reports, `10.18653/v1/2026.rag4reports-1.14`,
   *EFSG*). Before sentence drafting begins, each requested unit archetype is
   bound to a guiding warrant question, attentional foci, a sealed subset of
   committed ledger `fact_id` / `input_id` / `source_url` anchors, and its
   disciplinary move skeleton.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from apps.accounts import field_taxonomy as _ft
from apps.accounts.field_taxonomy import (
    DisciplineNode,
    FieldOrientation,
    FieldTaxonomyResolution,
    resolve_field_taxonomy,
)

from .evidence.readings import UsableReading
from .letter_schemas import Storyline
from .models import NarrativeInput, VerifiedFact


class RhetoricalDiscipline(StrEnum):
    STEM_QUANT = "STEM_QUANT"
    LIFE_BIOMED = "LIFE_BIOMED"
    SOCIAL_POLICY_ECON = "SOCIAL_POLICY_ECON"
    HUMANITIES_LAW_ARTS = "HUMANITIES_LAW_ARTS"
    PROFESSIONAL_DESIGN = "PROFESSIONAL_DESIGN"


@dataclass(frozen=True)
class DisciplinaryExemplar:
    discipline: RhetoricalDiscipline
    archetype: str
    move_sequence: str
    cadence_target: str
    negative_trial: str
    error_explanation: str
    positive_pattern: str

    def as_prompt_dict(self) -> dict[str, str]:
        return {
            "discipline": str(self.discipline),
            "archetype": self.archetype,
            "move_sequence": self.move_sequence,
            "cadence_target": self.cadence_target,
            "negative_trial_to_avoid": self.negative_trial,
            "why_negative_fails": self.error_explanation,
            "positive_structural_pattern": self.positive_pattern,
        }


@dataclass(frozen=True)
class QuestionFocusUnitPlan:
    archetype: str
    guiding_question: str
    attentional_foci: tuple[str, ...]
    committed_fact_ids: tuple[str, ...]
    committed_input_ids: tuple[str, ...]
    committed_source_urls: tuple[str, ...]
    move_sequence: str
    cadence_target: str

    def as_prompt_dict(self) -> dict[str, object]:
        return {
            "archetype": self.archetype,
            "guiding_question": self.guiding_question,
            "attentional_foci": list(self.attentional_foci),
            "committed_fact_ids": list(self.committed_fact_ids),
            "committed_input_ids": list(self.committed_input_ids),
            "committed_source_urls": list(self.committed_source_urls),
            "move_sequence": self.move_sequence,
            "cadence_target": self.cadence_target,
        }


#: Canonical DisciplineNode lookup by canonical name, derived directly from the
#: universal ISCED-F / OECD FOS Discipline Graph in `apps.accounts.field_taxonomy`.
_DISCIPLINE_NODE_BY_CANONICAL: dict[str, DisciplineNode] = {
    node.canonical: node for node in _ft._DISCIPLINE_NODES
}

#: Structural ISCED-F root-umbrella sink nodes of `_ft._DISCIPLINE_NODES`
#: (`{p for n in _DISCIPLINE_NODES for p in n.parent_fields} - set(_DISCIPLINE_NODE_BY_CANONICAL)`
#: plus `'business administration'`), mapped to the five rhetorical genre profiles.
#: Every single one of the 138 DisciplineNodes (and 3,077 multilingual synonyms
#: across 12 languages + morphological compound decomposition) reaches these root
#: umbrellas in <= 2 graph hops without any hardcoded domain keyword list.
_ISCED_ROOT_UMBRELLA_TO_DISCIPLINE: dict[str, RhetoricalDiscipline] = {
    "computing": RhetoricalDiscipline.STEM_QUANT,
    "engineering": RhetoricalDiscipline.STEM_QUANT,
    "informatics": RhetoricalDiscipline.STEM_QUANT,
    "mathematical sciences": RhetoricalDiscipline.STEM_QUANT,
    "physical sciences": RhetoricalDiscipline.STEM_QUANT,
    "bioengineering": RhetoricalDiscipline.LIFE_BIOMED,
    "health sciences": RhetoricalDiscipline.LIFE_BIOMED,
    "life sciences": RhetoricalDiscipline.LIFE_BIOMED,
    "natural sciences": RhetoricalDiscipline.LIFE_BIOMED,
    "social sciences": RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    "humanities": RhetoricalDiscipline.HUMANITIES_LAW_ARTS,
    "legal studies": RhetoricalDiscipline.HUMANITIES_LAW_ARTS,
    "arts": RhetoricalDiscipline.PROFESSIONAL_DESIGN,
    "built environment": RhetoricalDiscipline.PROFESSIONAL_DESIGN,
    "business administration": RhetoricalDiscipline.PROFESSIONAL_DESIGN,
}

#: Morphological inflection suffixes (plural/case endings across supported languages)
#: used ONLY to strip an ending and check whether the stem exists in
#: `_ft._DISCIPLINE_BY_SYNONYM` (e.g. German `Rechtswissenschaften` -> `rechtswissenschaft`).
_INFLECTIONAL_SUFFIXES: tuple[str, ...] = (
    "ical",
    "logical",
    "graphical",
    "metrics",
    "metric",
    "en",
    "n",
    "es",
    "s",
    "er",
    "e",
    "ic",
    "al",
    "ist",
    "ism",
    "lar",
    "lər",
    "ler",
    "ы",
    "и",
)

_DEGREE_CREDENTIAL_PATTERNS: tuple[tuple[str, RhetoricalDiscipline], ...] = (
    (
        r"\b(?:ll\.?m\.?|master\s+of\s+laws|ll\.?b\.?|bachelor\s+of\s+laws|j\.?d\.?|m\.?th\.?|m\.?div\.?)\b",
        RhetoricalDiscipline.HUMANITIES_LAW_ARTS,
    ),
    (
        r"\b(?:m\.?f\.?a\.?|master\s+of\s+fine\s+arts|b\.?f\.?a\.?|bachelor\s+of\s+fine\s+arts|"
        r"m\.?arch\.?|master\s+of\s+architecture|b\.?arch\.?|bachelor\s+of\s+architecture|"
        r"m\.?des\.?|b\.?des\.?|m\.?b\.?a\.?|master\s+of\s+business\s+administration|"
        r"b\.?b\.?a\.?|bachelor\s+of\s+business\s+administration|m\.?mus\.?|b\.?mus\.?)\b",
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
    ),
    (
        r"\b(?:m\.?p\.?p\.?|master\s+of\s+public\s+policy|b\.?p\.?p\.?|"
        r"m\.?p\.?a\.?|master\s+of\s+public\s+administration|"
        r"m\.?s\.?w\.?|b\.?s\.?w\.?|m\.?ed\.?|master\s+of\s+education|b\.?ed\.?|bachelor\s+of\s+education)\b",
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    ),
    (
        r"\b(?:m\.?p\.?h\.?|master\s+of\s+public\s+health|m\.?d\.?|d\.?v\.?m\.?|pharm\.?d\.?)\b",
        RhetoricalDiscipline.LIFE_BIOMED,
    ),
    (
        r"\b(?:m\.?a\.?|master\s+of\s+arts|b\.?a\.?|bachelor\s+of\s+arts)\b",
        RhetoricalDiscipline.HUMANITIES_LAW_ARTS,
    ),
)


def _lookup_node_or_inflected_stem(gram: str) -> DisciplineNode | None:
    """Resolve an n-gram to a `DisciplineNode` via `field_taxonomy._lookup_discipline_node`,
    morphological compound decomposition (`_decompose_morphological_compound`), or
    inflectional/derivational stem lookup against `_DISCIPLINE_BY_SYNONYM` and
    `_COMPOUND_PREFIXES`."""
    clean = gram.strip().casefold().replace("\u0307", "")
    if not clean:
        return None
    node = _ft._lookup_discipline_node(clean)
    if node is not None:
        return node
    comp = _ft._decompose_morphological_compound(clean)
    if comp is not None:
        return _ft._lookup_discipline_node(comp[0]) or _ft._lookup_discipline_node(comp[1])
    for suf in _INFLECTIONAL_SUFFIXES:
        if len(clean) > len(suf) + 3 and clean.endswith(suf):
            stem = clean[: -len(suf)]
            for candidate_stem in (stem, f"{stem}ics", f"{stem}y"):
                if candidate_stem in _ft._DISCIPLINE_BY_SYNONYM:
                    return _ft._DISCIPLINE_BY_SYNONYM[candidate_stem]
                if candidate_stem in _ft._COMPOUND_PREFIXES:
                    return _ft._lookup_discipline_node(_ft._COMPOUND_PREFIXES[candidate_stem])
            stem_comp = _ft._decompose_morphological_compound(stem)
            if stem_comp is not None:
                return _ft._lookup_discipline_node(stem_comp[0])
    return None


def _extract_discipline_nodes(texts: Sequence[str]) -> tuple[DisciplineNode, ...]:
    """Extract all `DisciplineNode`s referenced in `texts` (longest n-gram first)
    using the 12-language `_DISCIPLINE_BY_SYNONYM` graph and `resolve_field_taxonomy`."""
    found: list[DisciplineNode] = []
    seen: set[str] = set()

    def _add(node: DisciplineNode | None) -> None:
        if node is not None and node.canonical not in seen:
            seen.add(node.canonical)
            found.append(node)

    for raw in texts:
        normalized = (raw or "").strip().casefold().replace("\u0307", "")
        if not normalized:
            continue
        _add(_lookup_node_or_inflected_stem(normalized))
        toks = _ft._tokens(normalized)
        for n in range(min(4, len(toks)), 0, -1):
            for i in range(len(toks) - n + 1):
                _add(_lookup_node_or_inflected_stem(" ".join(toks[i : i + n])))

    if not found and texts:
        primary = next((t.strip() for t in texts if t and t.strip()), "")
        if primary:
            resolution = resolve_field_taxonomy(primary, tuple(t for t in texts[1:4] if t))
            for term in (*resolution.parent_fields, *resolution.canonical_degree_titles):
                _add(_lookup_node_or_inflected_stem(term))
    return tuple(found)


def _node_root_disciplines(node: DisciplineNode) -> tuple[RhetoricalDiscipline, ...]:
    """Walk at most 2 hops along `node.parent_fields` in `_DISCIPLINE_NODES` to
    collect its ISCED-F root rhetorical discipline(s), ranked by parent-path vote
    count and declaration priority."""
    votes: dict[RhetoricalDiscipline, int] = {}
    first_pos: dict[RhetoricalDiscipline, int] = {}
    cursor = 0
    for parent in (node.canonical, *node.parent_fields):
        direct = _ISCED_ROOT_UMBRELLA_TO_DISCIPLINE.get(parent)
        if direct is not None:
            votes[direct] = votes.get(direct, 0) + 2
            first_pos.setdefault(direct, cursor)
            cursor += 1
            continue
        parent_node = _DISCIPLINE_NODE_BY_CANONICAL.get(parent)
        if parent_node is not None:
            for gp in parent_node.parent_fields:
                gp_disc = _ISCED_ROOT_UMBRELLA_TO_DISCIPLINE.get(gp)
                if gp_disc is not None:
                    votes[gp_disc] = votes.get(gp_disc, 0) + 1
                    first_pos.setdefault(gp_disc, cursor)
                    cursor += 1
    ordered = sorted(
        votes,
        key=lambda d: (votes[d], -first_pos[d]),
        reverse=True,
    )
    return tuple(ordered)


def _infer_discipline_from_ledger_schema(
    facts: Mapping[UUID, VerifiedFact] | None,
    readings: Sequence[UsableReading],
    texts: Sequence[str] = (),
) -> RhetoricalDiscipline:
    """When no discipline node matched in `_DISCIPLINE_NODES`, infer the rhetorical
    profile from structural degree credentials (`LL.M.`, `MA`, `MFA`, `MPP`, `MPA`,
    `MBA`, `MPH`, `MSc`, `MEng`) and the student's confirmed ledger schema."""
    import re

    combined_text = " ".join(t for t in texts if t).casefold()
    if combined_text:
        for pattern, cred_disc in _DEGREE_CREDENTIAL_PATTERNS:
            if re.search(pattern, combined_text, re.IGNORECASE):
                return cred_disc
    for reading in readings:
        if reading.kind == "portfolio":
            return RhetoricalDiscipline.PROFESSIONAL_DESIGN
        if reading.kind == "code_repository":
            return RhetoricalDiscipline.STEM_QUANT
    for fact in (facts or {}).values():
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        keys = {str(k).casefold() for k in payload}
        if keys & {"archive", "corpus", "statute", "jurisdiction"}:
            return RhetoricalDiscipline.HUMANITIES_LAW_ARTS
        if keys & {"assay", "clinical_setting", "patient_cohort", "organism"}:
            return RhetoricalDiscipline.LIFE_BIOMED
        if keys & {"policy_area", "econometric_method"}:
            return RhetoricalDiscipline.SOCIAL_POLICY_ECON
    return RhetoricalDiscipline.STEM_QUANT


@dataclass(frozen=True)
class FieldOrientationProfile:
    """Synchronized multi-orientation taxonomy profile across programme search,
    research-fit discovery, and motivation-letter generation."""

    resolution: FieldTaxonomyResolution
    active_orientation: FieldOrientation | None
    contrasted_orientations: tuple[FieldOrientation, ...]
    student_orientation: FieldOrientation | None
    programme_orientation: FieldOrientation | None
    is_ai_data_orientation: bool
    is_theoretical_mechanistic_orientation: bool
    target_field: str = ""
    research_interests: tuple[str, ...] = ()


def _student_profile_field_and_interests(
    student: object | None,
) -> tuple[str, tuple[str, ...]]:
    """Read the student's latest intake `target_field` and `research_interests`
    from `StudentProfileVersion` when `student` is a persisted Membership."""
    student_id = getattr(student, "id", None)
    if not isinstance(student_id, UUID):
        return "", ()
    try:
        from apps.accounts.models import StudentProfileVersion

        latest = (
            StudentProfileVersion.objects.filter(student_id=student_id)
            .order_by("-version")
            .only("snapshot")
            .first()
        )
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "failed to query StudentProfileVersion for student %s: %s",
            student_id,
            exc,
        )
        return "", ()
    snap = getattr(latest, "snapshot", None) if latest is not None else None
    if not isinstance(snap, dict):
        return "", ()
    target = str(snap.get("target_field") or "").strip()
    raw_interests = snap.get("research_interests")
    interests: tuple[str, ...] = ()
    if isinstance(raw_interests, list | tuple):
        interests = tuple(str(x).strip() for x in raw_interests if str(x).strip())
    return target, interests


_UNIVERSAL_EPISTEMIC_ORIENTATIONS: dict[
    RhetoricalDiscipline, tuple[FieldOrientation, ...]
] = {
    RhetoricalDiscipline.HUMANITIES_LAW_ARTS: (
        FieldOrientation(
            slug="archival_textual_philological",
            label=(
                "archival, textual-critical, philological, epigraphic and primary-source "
                "historical inquiry"
            ),
            trigger_keywords=(
                "archive",
                "archival",
                "manuscript",
                "papyro",
                "epigraph",
                "paleograph",
                "historiograph",
                "chronicle",
                "corpus",
                "philolog",
                "lexicograph",
                "provenance",
                "excavation",
                "inscription",
                "antiquity",
                "medieval",
                "dynasty",
                "sinolog",
                "egyptolog",
            ),
            degree_titles=("history", "archaeology", "classics", "philology", "area studies"),
            track_keywords=("archival", "philological", "primary sources", "historiography"),
        ),
        FieldOrientation(
            slug="theoretical_critical_hermeneutic",
            label=(
                "theoretical, philosophical, normative, conceptual and critical-hermeneutic "
                "inquiry"
            ),
            trigger_keywords=(
                "philosophy",
                "philosophical",
                "normative",
                "ethics",
                "bioethics",
                "hermeneutic",
                "phenomenolog",
                "epistemolog",
                "metaphysic",
                "aesthetics",
                "critical theory",
                "theology",
                "conceptual",
                "poetics",
            ),
            degree_titles=("philosophy", "ethics", "theology", "comparative literature"),
            track_keywords=("theoretical", "normative", "philosophical", "critical"),
        ),
        FieldOrientation(
            slug="doctrinal_public_comparative_law",
            label=(
                "doctrinal, constitutional, public international, human-rights and comparative "
                "jurisprudence"
            ),
            trigger_keywords=(
                "constitutional",
                "human rights",
                "public international",
                "humanitarian law",
                "treaty",
                "jurisprudence",
                "comparative law",
                "criminal law",
                "penology",
                "judicial",
                "fundamental rights",
                "asylum",
            ),
            degree_titles=("law", "llm", "master of laws", "human rights"),
            track_keywords=("constitutional", "jurisprudence", "comparative law", "treaty"),
        ),
        FieldOrientation(
            slug="commercial_regulatory_arbitration_law",
            label=(
                "commercial, corporate, tax, arbitration, maritime/admiralty and regulatory "
                "transaction law"
            ),
            trigger_keywords=(
                "arbitration",
                "dispute resolution",
                "admiralty",
                "maritime",
                "corporate",
                "commercial",
                "tax",
                "competition",
                "antitrust",
                "mergers",
                "insolvency",
                "financial regulation",
                "intellectual property",
                "contract",
            ),
            degree_titles=("law", "llm", "international arbitration", "commercial law"),
            track_keywords=("arbitration", "regulatory", "commercial law", "dispute resolution"),
        ),
    ),
    RhetoricalDiscipline.SOCIAL_POLICY_ECON: (
        FieldOrientation(
            slug="quantitative_causal_econometric",
            label=(
                "quantitative modeling, causal inference, econometrics, psychometrics and "
                "statistical measurement"
            ),
            trigger_keywords=(
                "econometric",
                "psychometric",
                "quantitative",
                "causal",
                "panel",
                "regression",
                "item response",
                "actuarial",
                "demograph",
                "forecasting",
                "macroeconom",
                "microeconom",
                "monetary",
                "fiscal",
                "experimental",
            ),
            degree_titles=("economics", "econometrics", "demography", "quantitative"),
            track_keywords=("econometric", "causal inference", "quantitative", "statistical"),
        ),
        FieldOrientation(
            slug="qualitative_ethnographic_institutional",
            label=(
                "qualitative, ethnographic, field-based, comparative-historical and "
                "lived-experience social inquiry"
            ),
            trigger_keywords=(
                "ethnograph",
                "qualitative",
                "fieldwork",
                "anthropolog",
                "forced migration",
                "refugee",
                "displacement",
                "diaspora",
                "kinship",
                "gender",
                "participant observation",
                "interview",
                "discourse",
            ),
            degree_titles=("anthropology", "sociology", "migration studies"),
            track_keywords=("ethnographic", "qualitative", "fieldwork", "institutional"),
        ),
        FieldOrientation(
            slug="applied_policy_governance_diplomacy",
            label=(
                "applied public policy, governance design, peacebuilding, diplomacy and "
                "institutional reform"
            ),
            trigger_keywords=(
                "policy",
                "governance",
                "peacebuilding",
                "peace",
                "conflict",
                "diplomac",
                "public administration",
                "humanitarian",
                "regulation",
                "welfare",
                "development",
                "statecraft",
                "geopolit",
                "reform",
            ),
            degree_titles=("public policy", "public administration", "international relations"),
            track_keywords=("policy design", "governance", "diplomacy", "institutional reform"),
        ),
    ),
    RhetoricalDiscipline.PROFESSIONAL_DESIGN: (
        FieldOrientation(
            slug="studio_curatorial_spatial_practice",
            label=(
                "studio, architectural, curatorial, spatial, theatrical and material design "
                "practice"
            ),
            trigger_keywords=(
                "studio",
                "curatorial",
                "museolog",
                "exhibition",
                "architect",
                "urban",
                "spatial",
                "landscape",
                "scenograph",
                "dramaturg",
                "choreograph",
                "conservation",
                "contemporary art",
                "material",
                "portfolio",
            ),
            degree_titles=("architecture", "design", "fine arts", "curatorial practice"),
            track_keywords=("studio", "curatorial", "spatial design", "material practice"),
        ),
        FieldOrientation(
            slug="analytical_operations_strategic_management",
            label=(
                "operations, logistics, supply-chain analytics, strategy and organizational "
                "decision systems"
            ),
            trigger_keywords=(
                "logistics",
                "supply chain",
                "operations",
                "management",
                "strategy",
                "business",
                "marketing",
                "accounting",
                "finance",
                "procurement",
                "throughput",
                "organizational",
            ),
            degree_titles=("supply chain management", "business administration", "management"),
            track_keywords=("operations", "logistics", "supply chain", "strategic management"),
        ),
    ),
}

_NON_STEAM_EPISTEMIC_SLUGS: frozenset[str] = frozenset(
    o.slug
    for group in _UNIVERSAL_EPISTEMIC_ORIENTATIONS.values()
    for o in group
)


def _is_ai_or_data_orientation(orientation: FieldOrientation) -> bool:
    """Whether `orientation` is the AI / machine-learning / data-science /
    digital / robotics sub-track within a multi-orientation family (e.g.
    `ai_digital_chemistry` in Chemoinformatics vs `computational_quantum_chemistry`)."""
    ai_modifiers = _ft._AI_DIGITAL_MODIFIERS - {"computational"}
    slug_tokens = set(_ft._tokens(orientation.slug.replace("_", " ")))
    if slug_tokens & ai_modifiers:
        return True
    kw_tokens = set(_ft._tokens(" ".join(orientation.track_keywords[:4])))
    return bool(kw_tokens & ai_modifiers)


def _orientation_trigger_score(orientation: FieldOrientation, text: str) -> int:
    norm = (text or "").strip().casefold().replace("\u0307", "")
    if not norm:
        return 0
    trig_hits = sum(1 for kw in orientation.trigger_keywords if kw and kw.casefold() in norm)
    title_hits = sum(2 for dt in orientation.degree_titles if dt and dt.casefold() in norm)
    return trig_hits + title_hits


def _pick_matching_orientation(
    orientations: Sequence[FieldOrientation],
    evidence_text: str,
    preferred_track_keywords: Sequence[str] = (),
) -> FieldOrientation | None:
    if not orientations:
        return None
    if (evidence_text or "").strip():
        scored: list[tuple[int, int, FieldOrientation]] = []
        for idx, orient in enumerate(orientations):
            total = _orientation_trigger_score(orient, evidence_text)
            if total > 0:
                scored.append((total, -idx, orient))
        if scored:
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
            return scored[0][2]
    if preferred_track_keywords:
        pref_head = tuple(preferred_track_keywords[:2])
        for orient in orientations:
            if tuple(orient.track_keywords[:2]) == pref_head:
                return orient
    return orientations[0]


def _resolve_base_discipline_from_candidates(
    candidates: Sequence[str],
    facts: Mapping[UUID, VerifiedFact] | None,
    readings: Sequence[UsableReading],
) -> RhetoricalDiscipline:
    nodes = _extract_discipline_nodes(candidates)
    if nodes:
        scores: dict[RhetoricalDiscipline, int] = {d: 0 for d in RhetoricalDiscipline}
        for idx, node in enumerate(nodes):
            weight = 3 if idx == 0 else 1
            for d_idx, disc in enumerate(_node_root_disciplines(node)):
                scores[disc] += weight * (2 if d_idx == 0 else 1)
        best_disc, best_score = max(scores.items(), key=lambda item: item[1])
        if best_score > 0:
            return best_disc
    return _infer_discipline_from_ledger_schema(facts, readings, texts=candidates)


def resolve_field_orientation_profile(
    *,
    programme_name: str = "",
    facts: Mapping[UUID, VerifiedFact] | None = None,
    inputs: Mapping[UUID, NarrativeInput] | None = None,
    readings: Sequence[UsableReading] = (),
    storyline: Storyline | None = None,
    student: object | None = None,
    research_interests: Sequence[str] = (),
) -> FieldOrientationProfile:
    """Resolve the active `FieldOrientation` across both STEAM and non-STEAM fields
    (e.g. `ai_digital_chemistry` vs `computational_quantum_chemistry` inside
    Chemoinformatics; `archival_textual_philological` vs
    `theoretical_critical_hermeneutic` vs `doctrinal_public_comparative_law` vs
    `commercial_regulatory_arbitration_law` in Humanities/Law;
    `quantitative_causal_econometric` vs `qualitative_ethnographic_institutional`
    vs `applied_policy_governance_diplomacy` in Social Sciences/Policy) by
    synchronizing the student's intake profile, confirmed ledger facts/readings/storyline,
    target programme title, and verified `RESEARCH_FIT` provenance."""
    intake_field, intake_interests = _student_profile_field_and_interests(student)
    student_phrases: list[str] = [
        *(s.strip() for s in research_interests if s and s.strip()),
        *intake_interests,
    ]
    fact_fields: list[str] = []
    for fact in (facts or {}).values():
        if fact.category == VerifiedFact.Category.IDENTITY:
            continue
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        for key in (
            "field_of_study",
            "field",
            "degree_english",
            "degree_as_awarded",
            "thesis_title",
            "title",
            "methods",
            "description",
            "relevant_coursework",
            "bullets",
            "project",
            "group",
        ):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                if key in ("field_of_study", "field", "degree_english", "degree_as_awarded"):
                    fact_fields.append(val.strip())
                student_phrases.append(val.strip())
            elif isinstance(val, list | tuple):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        student_phrases.append(item.strip())
    for reading in readings:
        if reading.summary:
            student_phrases.append(reading.summary)
    if storyline is not None:
        for s_part in (storyline.theme, storyline.gap or "", storyline.future):
            if s_part.strip():
                student_phrases.append(s_part.strip())

    rf_phrases: list[str] = []
    saved_orientation_slug = ""
    for entry in (inputs or {}).values():
        if entry.kind == NarrativeInput.Kind.RESEARCH_FIT and isinstance(entry.provenance, dict):
            prov = entry.provenance
            if slug := str(prov.get("orientation_slug") or "").strip():
                saved_orientation_slug = slug
            for k in (
                "sentence",
                "paper_title",
                "paper_finding",
                "paper_method_or_question",
                "paper_active_topic",
            ):
                if val := str(prov.get(k) or "").strip():
                    rf_phrases.append(val)

    primary_query = (
        programme_name.strip()
        or intake_field
        or (fact_fields[0] if fact_fields else "")
        or (student_phrases[0] if student_phrases else "")
    )
    all_interest_cues = tuple(dict.fromkeys([*student_phrases, *rf_phrases]))
    resolution = resolve_field_taxonomy(primary_query, all_interest_cues[:8])
    if (
        not resolution.orientations
        and intake_field
        and intake_field.casefold() != primary_query.casefold()
    ):
        intake_res = resolve_field_taxonomy(intake_field, all_interest_cues[:8])
        if intake_res.orientations:
            resolution = intake_res

    student_text = " ".join(student_phrases)
    programme_text = " ".join([programme_name, *rf_phrases])
    combined_text = " ".join([*student_phrases, programme_name, *rf_phrases])

    orientations = resolution.orientations
    has_method_dichotomy = any(_is_ai_or_data_orientation(o) for o in orientations)
    if not orientations or not has_method_dichotomy:
        cand_texts = [p for p in (programme_name.strip(), *student_phrases) if p]
        base_disc = _resolve_base_discipline_from_candidates(cand_texts, facts, readings)
        epistemic_candidates = _UNIVERSAL_EPISTEMIC_ORIENTATIONS.get(base_disc, ())
        if epistemic_candidates and any(
            _orientation_trigger_score(o, combined_text) > 0 for o in epistemic_candidates
        ):
            orientations = epistemic_candidates

    if not orientations:
        return FieldOrientationProfile(
            resolution=resolution,
            active_orientation=None,
            contrasted_orientations=(),
            student_orientation=None,
            programme_orientation=None,
            is_ai_data_orientation=False,
            is_theoretical_mechanistic_orientation=False,
            target_field=intake_field,
            research_interests=intake_interests,
        )

    active: FieldOrientation | None = None
    if saved_orientation_slug:
        active = next(
            (o for o in orientations if o.slug == saved_orientation_slug),
            None,
        )
    if active is None:
        active = _pick_matching_orientation(
            orientations,
            combined_text,
            resolution.preferred_track_keywords,
        )
    student_orient = (
        _pick_matching_orientation(orientations, student_text)
        if student_text.strip()
        else active
    )
    programme_orient = (
        _pick_matching_orientation(orientations, programme_text)
        if programme_text.strip()
        else active
    )
    contrasted = tuple(o for o in orientations if active is None or o.slug != active.slug)
    family_has_ai_dichotomy = any(_is_ai_or_data_orientation(o) for o in orientations)
    is_ai = _is_ai_or_data_orientation(active) if active is not None else False
    return FieldOrientationProfile(
        resolution=resolution,
        active_orientation=active,
        contrasted_orientations=contrasted,
        student_orientation=student_orient,
        programme_orientation=programme_orient,
        is_ai_data_orientation=is_ai,
        is_theoretical_mechanistic_orientation=bool(
            active is not None and not is_ai and family_has_ai_dichotomy
        ),
        target_field=intake_field,
        research_interests=intake_interests,
    )


def resolve_rhetorical_discipline(
    *,
    programme_name: str = "",
    facts: Mapping[UUID, VerifiedFact] | None = None,
    inputs: Mapping[UUID, NarrativeInput] | None = None,
    readings: Sequence[UsableReading] = (),
    storyline: Storyline | None = None,
    student: object | None = None,
    research_interests: Sequence[str] = (),
    portfolio_led: bool = False,
) -> RhetoricalDiscipline:
    """Resolve the macro-disciplinary rhetorical profile deterministically via
    the 2-hop ISCED-F graph in `apps.accounts.field_taxonomy`, active
    `FieldOrientation` sub-tracks (e.g. `ai_digital_chemistry` vs
    `computational_quantum_chemistry` in Chemoinformatics), and the student's
    ledger schema, with zero hardcoded keyword lists and zero external network calls."""
    if portfolio_led:
        return RhetoricalDiscipline.PROFESSIONAL_DESIGN

    orientation_profile = resolve_field_orientation_profile(
        programme_name=programme_name,
        facts=facts,
        inputs=inputs,
        readings=readings,
        storyline=storyline,
        student=student,
        research_interests=research_interests,
    )

    candidates: list[str] = []
    if programme_name.strip():
        candidates.append(programme_name.strip())
    if orientation_profile.target_field.strip():
        candidates.append(orientation_profile.target_field.strip())
    for interest in (*research_interests, *orientation_profile.research_interests):
        if isinstance(interest, str) and interest.strip():
            candidates.append(interest.strip())
    for fact in (facts or {}).values():
        if fact.category == VerifiedFact.Category.IDENTITY:
            continue
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        for key in (
            "field_of_study",
            "field",
            "degree_english",
            "degree_as_awarded",
            "thesis_title",
            "title",
            "methods",
            "description",
            "relevant_coursework",
            "bullets",
            "project",
            "group",
        ):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                candidates.append(val.strip())
            elif isinstance(val, list | tuple):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        candidates.append(item.strip())
    for reading in readings:
        if reading.summary:
            candidates.append(reading.summary)
    if storyline is not None:
        for s_part in (storyline.theme, storyline.gap or "", storyline.future):
            if s_part.strip():
                candidates.append(s_part.strip())

    base_disc = _resolve_base_discipline_from_candidates(candidates, facts, readings)

    if orientation_profile.active_orientation is not None:
        if orientation_profile.is_ai_data_orientation:
            return RhetoricalDiscipline.STEM_QUANT
        return base_disc

    return base_disc


#: Vetted Trial-Error-Explain move-cadence exemplars per discipline and archetype.
#: Every exemplar uses only abstract slot placeholders (<...>) so no foreign entity,
#: number, or phrase can be copied into an applicant's letter.
_EXEMPLAR_CATALOG: tuple[DisciplinaryExemplar, ...] = (
    # --- STEM_QUANT ---
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.STEM_QUANT,
        archetype="ACADEMIC_PREPARATION",
        move_sequence=(
            "Move 1 (Concrete Artifact & Metric): State the system, solver, or experiment built "
            "from the verified fact and its quantitative scale -> Move 2 (Technical Bottleneck): "
            "Pinpoint the exact mathematical, algorithmic, or hardware assumption that broke -> "
            "Move 3 (Open Question): Formulate the unresolved technical question that motivates "
            "graduate study."
        ),
        cadence_target=(
            "4 sentences mixing short direct clauses and longer analytical clauses (~9w, ~26w, "
            "~19w, ~8w); active first-person verbs ('I implemented', 'I measured')."
        ),
        negative_trial=(
            "During my bachelor studies I worked on <PROJECT_TOPIC> and gained strong skills in "
            "<TOOL>. This experience sparked my deep passion for the evolving landscape of the "
            "field."
        ),
        error_explanation=(
            "Fails: repeats generic CV labels and stock AI praise ('evolving landscape', 'sparked "
            "my deep passion') without stating what was built, what metric was observed, or where "
            "the method hit a technical limit."
        ),
        positive_pattern=(
            "In <FACT_ANCHOR_COURSE_OR_PROJECT>, I built <SYSTEM_OR_MODEL> across "
            "<QUANTITATIVE_SCALE>. "
            "While the formulation converged under <BASELINE_REGIME>, accuracy degraded when "
            "<ASSUMPTION_OR_BOUNDARY_CONDITION_BROKE>, exposing a bottleneck in <MECHANISM>. "
            "Testing <FALLBACK_ADJUSTMENT> reduced the error on our benchmark but could not "
            "guarantee <THEORETICAL_OR_SYSTEM_PROPERTY>. "
            "That limit defines the technical question I want to solve next."
        ),
    ),
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.STEM_QUANT,
        archetype="WHY_PROGRAMME",
        move_sequence=(
            "Move 1 (Gap Specification): Name the methodological or analytical capability "
            "separating the applicant's prior work from their research goal -> Move 2 (Sourced "
            "Lab/Module Bridge): Connect the verified programme entity (<SOURCED_ENTITY>) and its "
            "published finding directly to the applicant's anchor bottleneck -> Move 3 (Concrete "
            "Application): State how combining both advances the question."
        ),
        cadence_target=(
            "3-4 sentences (~11w, ~27w, ~21w, ~9w); name the verified entity verbatim and quote at "
            "most one short phrase."
        ),
        negative_trial=(
            "<INSTITUTION_NAME> is a world-renowned university with cutting-edge facilities in "
            "<FIELD>. Working with <SOURCED_ENTITY> will allow me to expand my horizons and "
            "achieve my career goals."
        ),
        error_explanation=(
            "Fails: flatters the institution with brochure adjectives ('world-renowned', "
            "'cutting-edge') and fails the university find-and-replace test by never linking the "
            "applicant's specific technical bottleneck to the group's or module's actual method."
        ),
        positive_pattern=(
            "Closing the gap between my work on <APPLICANT_ANCHOR_TOPIC> and <TARGET_CAPABILITY> "
            "requires formal training in <SPECIFIC_METHOD>. "
            "At <PROGRAMME_OR_INSTITUTION>, <SOURCED_ENTITY> addresses this regime directly "
            "through <VERIFIED_PAPER_OR_MODULE_FINDING>. "
            "Connecting my background in <APPLICANT_TRANSFERABLE_SKILL> with that formulation will "
            "let me test how <TECHNICAL_INTERACTION> behaves under realistic constraints."
        ),
    ),
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.STEM_QUANT,
        archetype="RESEARCH_PLAN",
        move_sequence=(
            "Move 1 (Hypothesis & Formulation): State the concrete research problem and proposed "
            "formalism -> Move 2 (Methodology & Evaluation): Specify the experimental or "
            "mathematical validation protocol and baseline comparison -> Move 3 (Feasibility "
            "Anchor): Tie execution feasibility to a verified prior skill or codebase."
        ),
        cadence_target=(
            "3-4 sentences (~10w, ~25w, ~22w, ~9w); concrete nouns, zero vague promises."
        ),
        negative_trial=(
            "For my master's thesis, I plan to conduct groundbreaking research on <BROAD_TOPIC> "
            "using state-of-the-art methods to solve major industry challenges."
        ),
        error_explanation=(
            "Fails: names a broad field rather than a falsifiable question, uses empty "
            "intensifiers ('groundbreaking', 'state-of-the-art'), and specifies no evaluation "
            "protocol."
        ),
        positive_pattern=(
            "I propose to investigate whether <RESEARCH_QUESTION_OR_MECHANISM> can be stabilized "
            "under <CONSTRAINT>. "
            "To test this, I will formulate <PROPOSED_METHOD_OR_MODEL> and benchmark its "
            "performance against <BASELINE_APPROACH> on <OBSERVABLE_CRITERION>. "
            "My prior implementation of <VERIFIED_PRIOR_PROJECT_OR_THESIS> provides the data "
            "pipeline and numerical foundation needed to execute this study."
        ),
    ),
    # --- LIFE_BIOMED ---
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.LIFE_BIOMED,
        archetype="ACADEMIC_PREPARATION",
        move_sequence=(
            "Move 1 (Experimental/Clinical Context): State the assay, cohort, or reaction system "
            "investigated in the verified fact -> Move 2 (Observed Anomaly or Assay Limit): "
            "Describe the mechanistic ambiguity or experimental resolution limit observed -> "
            "Move 3 (Mechanistic Question): State the biological, chemical, or clinical mechanism "
            "that remained unresolved."
        ),
        cadence_target="4 sentences (~9w, ~25w, ~20w, ~8w); precise experimental verbs.",
        negative_trial=(
            "Ever since childhood I have been fascinated by life sciences and helping patients. "
            "In my laboratory courses I learned many techniques such as <TECHNIQUE>."
        ),
        error_explanation=(
            "Fails: opens with a childhood cliché (Ding 2007 N-01/N-02) and lists techniques like "
            "a syllabus instead of reasoning from an experimental observation."
        ),
        positive_pattern=(
            "In my work on <FACT_ANCHOR_LAB_OR_THESIS>, I assayed <BIOLOGICAL_OR_CHEMICAL_SYSTEM> "
            "using <VERIFIED_PROTOCOL_OR_INSTRUMENT>. "
            "Although the assay quantified <PRIMARY_OBSERVATION>, it could not separate "
            "<CONFOUNDING_PATHWAY_OR_INTERMEDIATE> from the downstream response. "
            "Where that protocol lost resolution, I had to treat <MECHANISTIC_STEP> as an "
            "unmeasured black box. "
            "Resolving that mechanism is the focus of my next step."
        ),
    ),
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.LIFE_BIOMED,
        archetype="WHY_PROGRAMME",
        move_sequence=(
            "Move 1 (Methodological Need): Identify the experimental or computational platform "
            "needed to resolve the applicant's mechanistic question -> Move 2 (Sourced "
            "Group/Module Bridge): Connect <SOURCED_ENTITY>'s recent finding or curriculum module "
            "to the applicant's assay background -> Move 3 (Translational/Research Fit): State the "
            "concrete experimental synergy."
        ),
        cadence_target="3-4 sentences (~10w, ~26w, ~20w, ~9w).",
        negative_trial=(
            "Your department's prestigious faculty and modern laboratories in <CITY> make it the "
            "ideal place for my biomedical career."
        ),
        error_explanation=(
            "Fails: cites city and prestige rather than specific experimental methods, modules, or "
            "faculty findings."
        ),
        positive_pattern=(
            "Moving from bulk observation in <APPLICANT_PRIOR_SYSTEM> to mechanistic causal "
            "inference requires training in <TARGET_EXPERIMENTAL_OR_COMPUTATIONAL_METHOD>. "
            "In this programme, <SOURCED_ENTITY> investigates <VERIFIED_FINDING_OR_TOPIC>, "
            "directly addressing the resolution limit I encountered in <APPLICANT_FACT_ANCHOR>. "
            "Combining my hands-on preparation in <VERIFIED_LAB_SKILL> with that approach will "
            "prepare me to interrogate <TARGET_PATHWAY_OR_SYSTEM> quantitatively."
        ),
    ),
    # --- SOCIAL_POLICY_ECON ---
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.SOCIAL_POLICY_ECON,
        archetype="ACADEMIC_PREPARATION",
        move_sequence=(
            "Move 1 (Empirical Dataset or Policy Case): Name the empirical dataset, institutional "
            "setting, or field study from the verified fact -> Move 2 (Identification or "
            "Structural Bottleneck): State where descriptive analysis hit an endogeneity, "
            "measurement, or institutional design limit -> Move 3 (Analytical Question): State "
            "the causal or policy question left open."
        ),
        cadence_target="4 sentences (~8w, ~24w, ~21w, ~9w); analytical active prose.",
        negative_trial=(
            "I have always been passionate about economics and social justice. My coursework and "
            "internship gave me a solid foundation in <SUBJECT>."
        ),
        error_explanation=(
            "Fails: LSE's #1 rejected opening ('I have always been passionate about economics', "
            "N-02); asserts 'a solid foundation' without naming an empirical dataset, model, or "
            "identification problem."
        ),
        positive_pattern=(
            "While analyzing <FACT_ANCHOR_DATASET_OR_PROGRAMME> during <VERIFIED_ROLE_OR_THESIS>, "
            "I evaluated <EMPIRICAL_OUTCOME_OR_METRIC>. "
            "Descriptive comparisons showed <OBSERVED_PATTERN>, but unobserved selection across "
            "<CONFOUNDING_DIMENSION> prevented causal identification with standard specification "
            "tools. "
            "Without a structural model of <INSTITUTIONAL_OR_BEHAVIORAL_MECHANISM>, our analysis "
            "could diagnose the disparity but could not predict policy counterfactuals. "
            "That identification gap drives my application."
        ),
    ),
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.SOCIAL_POLICY_ECON,
        archetype="WHY_PROGRAMME",
        move_sequence=(
            "Move 1 (Analytical Gap): Name the quantitative, econometric, or comparative policy "
            "framework the applicant lacks -> Move 2 (Sourced Curriculum/Faculty Link): Connect "
            "<SOURCED_ENTITY>'s module or published research finding to that analytical need -> "
            "Move 3 (Policy/Research Application): State how the training applies to the "
            "applicant's target empirical question."
        ),
        cadence_target="3-4 sentences (~11w, ~26w, ~19w, ~8w).",
        negative_trial=(
            "I want to study at <INSTITUTION_NAME> because of its global ranking in social "
            "sciences and diverse international student body."
        ),
        error_explanation=(
            "Fails: cites global rankings and generic campus diversity (explicitly penalized by "
            "LSE L-038 and Imperial) instead of curriculum modules or faculty research."
        ),
        positive_pattern=(
            "Evaluating <TARGET_EMPIRICAL_OR_POLICY_PROBLEM> rigorously requires advanced training "
            "in <ECONOMETRIC_OR_THEORETICAL_METHOD>. "
            "The curriculum and research led by <SOURCED_ENTITY> on "
            "<VERIFIED_TOPIC_OR_PAPER_FINDING> provide the exact micro-foundations and "
            "identification tools my prior work lacked. "
            "Mastering those methods will allow me to model <TARGET_SECTORAL_MECHANISM> with "
            "credible causal evidence."
        ),
    ),
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.SOCIAL_POLICY_ECON,
        archetype="HOME_COUNTRY_CONTRIBUTION",
        move_sequence=(
            "Move 1 (Sourced Sectoral Bottleneck at Home): State the concrete workflow or sectoral "
            "bottleneck in the home country backed by a verified figure/source -> Move 2 "
            "(Capability Bridge): Specify the exact methodological capability acquired in the "
            "programme -> Move 3 (Measurable Post-Return Outcome): Name the target "
            "sector/institution and measurable outcome (Commonwealth/DAAD need -> capability -> "
            "outcome chain)."
        ),
        cadence_target="3-4 sentences (~10w, ~25w, ~22w, ~9w); concrete institutional nouns.",
        negative_trial=(
            "After graduation I will return to my home country to contribute to sustainable "
            "development and share my knowledge with future generations."
        ),
        error_explanation=(
            "Fails: confuses vague aspirations with an actionable development plan (Commonwealth "
            "L-029; DAAD ST 32) and cites no sectoral bottleneck or target institution."
        ),
        positive_pattern=(
            "In <HOME_COUNTRY_OR_SECTOR>, <SOURCED_HOME_BOTTLENECK_AND_FIGURE> continues to "
            "constrain <OBSERVED_WORKFLOW_OR_PUBLIC_SERVICE>. "
            "My prior work in <VERIFIED_EXPERIENCE_ANCHOR> showed where local practitioners lack "
            "<SPECIFIC_ANALYTICAL_OR_TECHNICAL_CAPABILITY>. "
            "By acquiring <PROGRAMME_CAPABILITY> through this degree, I will return to work on "
            "<CONCRETE_POST_STUDY_TARGET> and implement <MEASURABLE_SECTORAL_OUTCOME>."
        ),
    ),
    # --- HUMANITIES_LAW_ARTS ---
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.HUMANITIES_LAW_ARTS,
        archetype="ACADEMIC_PREPARATION",
        move_sequence=(
            "Move 1 (Corpus, Archive, or Legal Doctrine Examined): Name the specific primary "
            "texts, archive, linguistic corpus, or legal statutes analyzed in the verified fact -> "
            "Move 2 (Interpretive or Doctrinal Tension): State where existing secondary literature "
            "or doctrinal frameworks left an anomaly unaccounted for -> Move 3 (Comparative "
            "Research Question): Pose the critical question for graduate inquiry."
        ),
        cadence_target="4 sentences (~9w, ~26w, ~21w, ~8w); precise disciplinary terminology.",
        negative_trial=(
            "Reading literature and legal texts has always inspired me. My undergraduate essays "
            "taught me critical thinking and communication skills."
        ),
        error_explanation=(
            "Fails: claims generic 'critical thinking' instead of naming the primary corpus, "
            "doctrinal conflict, or historiographical debate examined."
        ),
        positive_pattern=(
            "In my research on <FACT_ANCHOR_THESIS_OR_SEMINAR>, I examined "
            "<PRIMARY_CORPUS_OR_STATUTE> through the lens of <ANALYTICAL_FRAMEWORK>. "
            "While prevailing scholarship treats <CONVENTIONAL_INTERPRETATION> as settled, close "
            "reading of <SPECIFIC_EVIDENCE_IN_FACT> revealed a persistent tension around "
            "<CONCEPT>. "
            "Addressing that divergence requires comparative tools beyond my undergraduate "
            "training. "
            "That textual and theoretical gap anchors my proposed graduate work."
        ),
    ),
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.HUMANITIES_LAW_ARTS,
        archetype="WHY_PROGRAMME",
        move_sequence=(
            "Move 1 (Theoretical/Methodological Lens Needed): Specify the comparative, archival, "
            "or jurisprudential methodology required -> Move 2 (Sourced Seminar/Faculty Link): "
            "Connect <SOURCED_ENTITY>'s scholarship or seminar to the applicant's primary corpus "
            "-> Move 3 (Scholarly Trajectory): State how the dialogue advances the thesis project."
        ),
        cadence_target="3-4 sentences (~10w, ~26w, ~20w, ~9w).",
        negative_trial=(
            "Your faculty has a rich history and vibrant intellectual community that will foster "
            "my growth as a scholar."
        ),
        error_explanation=(
            "Fails: uses banned AI brochure vocabulary ('rich history', 'vibrant intellectual "
            "community', 'foster') with zero scholarly specificity."
        ),
        positive_pattern=(
            "Situating my work on <APPLICANT_CORPUS_OR_DOCTRINE> within a broader comparative "
            "framework requires rigorous training in <THEORETICAL_OR_JURISPRUDENTIAL_METHOD>. "
            "At <PROGRAMME_OR_INSTITUTION>, <SOURCED_ENTITY> examines <VERIFIED_SCHOLARLY_FOCUS>, "
            "offering a direct methodological counterpart to the question raised in my thesis. "
            "Engaging with that scholarship will allow me to trace how <ANALYTICAL_CONCEPT> "
            "operates across both contexts."
        ),
    ),
    # --- PROFESSIONAL_DESIGN ---
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        archetype="ACADEMIC_PREPARATION",
        move_sequence=(
            "Move 1 (Built Project, Studio Work, or Operational Case): Name the concrete project, "
            "portfolio piece, or organizational deployment from the verified fact -> Move 2 "
            "(Design/Operational Trade-off): Explain the formal, spatial, material, or operational "
            "constraint where the solution hit a trade-off -> Move 3 (Practice Question): State "
            "the design or management capability needed next."
        ),
        cadence_target=(
            "4 sentences (~8w, ~24w, ~20w, ~9w); active first-person agency ('I designed', "
            "'I led')."
        ),
        negative_trial=(
            "I am a creative and results-oriented professional with experience in <FIELD>. I "
            "worked with various teams to deliver successful projects."
        ),
        error_explanation=(
            "Fails: uses corporate résumé clichés ('results-oriented', 'various teams') instead of "
            "analyzing a specific formal, architectural, or operational trade-off."
        ),
        positive_pattern=(
            "For <FACT_ANCHOR_PROJECT_OR_ROLE>, I designed and executed <DELIVERABLE_OR_SYSTEM> "
            "under <CONCRETE_CONSTRAINT_OR_SCALE>. "
            "Balancing <REQUIREMENT_A> against <REQUIREMENT_B> exposed a structural trade-off in "
            "how <PROCESS_OR_MEDIUM> handled edge conditions. "
            "While our iteration met the immediate brief, resolving that constraint at scale "
            "requires systematic methods in <TARGET_DOMAIN_METHOD>. "
            "That challenge shapes my focus for graduate training."
        ),
    ),
    DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        archetype="WHY_PROGRAMME",
        move_sequence=(
            "Move 1 (Practice/Studio Gap): State the technical, studio, or strategic capability "
            "needed -> Move 2 (Sourced Studio/Track/Partner Link): Connect <SOURCED_ENTITY> to the "
            "applicant's portfolio or operational problem -> Move 3 (Next-Stage Practice): State "
            "the concrete post-graduation application."
        ),
        cadence_target="3-4 sentences (~10w, ~25w, ~20w, ~8w).",
        negative_trial=(
            "This programme offers a unique blend of theory and practice that aligns perfectly "
            "with my professional ambitions."
        ),
        error_explanation=(
            "Fails: generic slogan ('unique blend of theory and practice') that could apply to "
            "any degree anywhere."
        ),
        positive_pattern=(
            "Extending my work on <APPLICANT_PROJECT_OR_PORTFOLIO_ANCHOR> to complex real-world "
            "deployments requires structured training in <TARGET_STUDIO_OR_ANALYTICAL_METHOD>. "
            "This programme's focus through <SOURCED_ENTITY> on <VERIFIED_PROGRAMME_FEATURE> "
            "directly addresses the operational trade-off I encountered in "
            "<APPLICANT_FACT_ANCHOR>. "
            "Integrating those tools will equip me to lead <POST_STUDY_PRACTICE_TARGET>."
        ),
    ),
)

#: Universal exemplars for cross-cutting archetypes (`LEADERSHIP_EXAMPLE`, `CAREER_PLAN_RETURN`,
#: `PERSONAL_BACKGROUND`) that apply across all disciplines when requested.
_UNIVERSAL_EXEMPLARS: dict[str, DisciplinaryExemplar] = {
    "LEADERSHIP_EXAMPLE": DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.STEM_QUANT,
        archetype="LEADERSHIP_EXAMPLE",
        move_sequence=(
            "Move 1 (Situation & Bottleneck): State the specific team, organization, or project "
            "breakdown from the most recent experience fact -> Move 2 (Personal Action in 'I'): "
            "State what 'I' personally proposed, reorganized, or built -> Move 3 (Measurable "
            "Result): State what changed as a direct consequence."
        ),
        cadence_target=(
            "4 sentences (~9w, ~23w, ~21w, ~9w); strictly first-person singular ('I', never 'we')."
        ),
        negative_trial=(
            "As a team leader at <EMPLOYER>, we worked together to overcome challenges and "
            "successfully delivered our goals on time."
        ),
        error_explanation=(
            "Fails: uses first-person plural ('we') instead of personal agency ('I', Chevening "
            "rule N-13) and lists responsibilities rather than a concrete intervention and outcome."
        ),
        positive_pattern=(
            "At <FACT_ANCHOR_EMPLOYER_OR_ORG>, <SPECIFIC_WORKFLOW_OR_COHORT_BOTTLENECK> delayed "
            "delivery across <SCALE>. "
            "I redesigned <PROCESS_OR_PROTOCOL>, negotiated adoption with <STAKEHOLDERS>, and "
            "trained the team on the revised workflow. "
            "Within <TIMEFRAME_FROM_FACT>, that change produced <VERIFIED_OUTCOME_OR_RESULT>. "
            "The experience showed me how technical decisions depend on clear institutional "
            "coordination."
        ),
    ),
    "CAREER_PLAN_RETURN": DisciplinaryExemplar(
        discipline=RhetoricalDiscipline.STEM_QUANT,
        archetype="CAREER_PLAN_RETURN",
        move_sequence=(
            "Move 1 (Immediate Post-Graduation Role & Sector): Name the concrete role, research "
            "track, or sector immediately after graduation -> Move 2 (Problem Targeted): State the "
            "specific technical or sectoral problem to be solved -> Move 3 (Degree Enablement): "
            "Tie that transition back to the capabilities gained in the programme."
        ),
        cadence_target=(
            "3-4 sentences (~9w, ~24w, ~19w, ~8w); end on a concrete fact, never vague optimism."
        ),
        negative_trial=(
            "In the future, I hope to become a leader in my field and make a positive impact on "
            "society through innovation."
        ),
        error_explanation=(
            "Fails: closes on vague optimism ('make a positive impact') with no named sector, "
            "role, or technical objective."
        ),
        positive_pattern=(
            "Upon completing this degree, I intend to pursue <CONCRETE_ROLE_OR_DOCTORAL_TRACK> "
            "focusing on <SPECIFIC_SECTORAL_OR_RESEARCH_PROBLEM>. "
            "Combining my prior foundation in <VERIFIED_FACT_ANCHOR> with the programme's training "
            "will allow me to address <TECHNICAL_OR_INSTITUTIONAL_BOTTLENECK> directly. "
            "That trajectory builds step by step on the work I have already started."
        ),
    ),
}


def _adapt_why_programme_exemplar(
    base: DisciplinaryExemplar,
    *,
    programme_discipline: RhetoricalDiscipline,
    student_discipline: RhetoricalDiscipline,
    inputs: Mapping[UUID, NarrativeInput] | None,
    forbid_naming: bool,
    orientation_profile: FieldOrientationProfile | None = None,
) -> DisciplinaryExemplar:
    """Dynamically adapt the `WHY_PROGRAMME` exemplar to the student's actual
    programme research-fit topology (`forbid_naming` / no research facts,
    cross-disciplinary `method_transfer`, or live `paper_method_or_question`)."""
    research_rows = [
        entry
        for entry in (inputs or {}).values()
        if entry.kind == NarrativeInput.Kind.RESEARCH_FIT and isinstance(entry.provenance, dict)
    ]
    if forbid_naming or (inputs is not None and not research_rows):
        return DisciplinaryExemplar(
            discipline=programme_discipline,
            archetype="WHY_PROGRAMME",
            move_sequence=(
                "Move 1 (Methodological Gap from Prior Work): State the concrete analytical or "
                "technical limit exposed by the applicant's prior anchor fact -> Move 2 "
                "(Applicant-Side Capability Need): Specify the formal methods or analytical "
                "depth the applicant needs next without naming any unverified course, module, "
                "lab, or faculty member -> Move 3 (Direct Trajectory Link): Connect that "
                "capability to the applicant's post-graduation problem."
            ),
            cadence_target=(
                "3-4 sentences (~10w, ~24w, ~20w, ~9w); zero unverified programme claims."
            ),
            negative_trial=(
                "This programme offers specialized courses and world-class faculty in <FIELD> "
                "that will teach me <TOPIC>."
            ),
            error_explanation=(
                "Fails: asserts what the programme or university teaches or offers when no "
                "verified programme research fact is in the data (triggers "
                "UNSOURCED_PROGRAMME_CLAIM)."
            ),
            positive_pattern=(
                "My work on <APPLICANT_FACT_ANCHOR> exposed where my current tools in "
                "<PRIOR_METHOD> break down under <TECHNICAL_OR_EMPIRICAL_CONSTRAINT>. "
                "Advancing that question requires rigorous graduate training in "
                "<NEEDED_METHODOLOGICAL_CAPABILITY> rather than ad-hoc approximations. "
                "Developing that foundation is the necessary step toward solving "
                "<POST_GRADUATION_PROBLEM>."
            ),
        )

    prov: Mapping[str, object] = (research_rows[0].provenance or {}) if research_rows else {}
    fit_mode = str(prov.get("fit_mode") or "").strip()
    has_method_question = bool(prov.get("paper_method_or_question"))
    is_cross_disciplinary = (
        fit_mode == "method_transfer" or student_discipline != programme_discipline
    )
    target_orient = (
        (orientation_profile.programme_orientation or orientation_profile.active_orientation)
        if orientation_profile is not None
        else None
    )
    orient_prefix = f"[{target_orient.label}] " if target_orient is not None else ""
    if is_cross_disciplinary and research_rows:
        return DisciplinaryExemplar(
            discipline=programme_discipline,
            archetype="WHY_PROGRAMME",
            move_sequence=(
                f"{orient_prefix}Move 1 (Transferable Method from Source Domain): Name the "
                "quantitative, computational, or analytical tool built in <ANCHOR_FACT_ID> -> "
                "Move 2 (Cross-Disciplinary Bridge to Sourced Target Entity): Connect that "
                "transferable method to <SOURCED_ENTITY>'s problem or <PAPER_METHOD_OR_QUESTION> "
                "without claiming prior domain work in the target field -> Move 3 (Target Problem "
                "Synthesis): State the joint question enabled by combining both."
            ),
            cadence_target=base.cadence_target,
            negative_trial=base.negative_trial,
            error_explanation=base.error_explanation,
            positive_pattern=(
                "In <ANCHOR_FACT_ID>, I developed <APPLICANT_TRANSFERABLE_METHOD_OR_PIPELINE> "
                "to address <SOURCE_DOMAIN_CONSTRAINT>. "
                "At <PROGRAMME_OR_INSTITUTION>, <SOURCED_ENTITY> examines "
                "<VERIFIED_FINDING_OR_PAPER_METHOD_QUESTION>, where a homologous structural "
                "bottleneck arises. "
                "Bridging my quantitative preparation in <APPLICANT_TRANSFERABLE_SKILL> to that "
                "domain will let me investigate <JOINT_RESEARCH_OR_POLICY_QUESTION> without "
                "overstating my prior exposure to <TARGET_DOMAIN>."
            ),
        )
    if has_method_question:
        return DisciplinaryExemplar(
            discipline=programme_discipline,
            archetype="WHY_PROGRAMME",
            move_sequence=(
                f"{orient_prefix}Move 1 (Gap Specification): State the technical or analytical "
                "limit from <ANCHOR_FACT_ID> -> Move 2 (Live Paper Bottleneck & Finding Bridge): "
                "Connect that limit directly to <SOURCED_ENTITY>'s open question "
                "(<PAPER_METHOD_OR_QUESTION>) and published finding (<PAPER_FINDING>) -> "
                "Move 3 (Next Research Step): Formulate the concrete investigation."
            ),
            cadence_target=base.cadence_target,
            negative_trial=base.negative_trial,
            error_explanation=base.error_explanation,
            positive_pattern=base.positive_pattern,
        )
    return base


def _specialize_exemplar_for_orientation(
    base: DisciplinaryExemplar,
    profile: FieldOrientationProfile,
    *,
    has_research_fit: bool,
) -> DisciplinaryExemplar:
    """When `profile.active_orientation` is present (e.g. `ai_digital_chemistry`
    vs `computational_quantum_chemistry` inside Chemoinformatics, or any other
    multi-orientation family in `field_taxonomy`), specialize `ACADEMIC_PREPARATION`,
    `WHY_PROGRAMME`, and `RESEARCH_PLAN` so the letter's move structure and
    contrastive warnings reflect the exact sub-track."""
    has_orientation_pivot = (
        profile.student_orientation is not None
        and profile.programme_orientation is not None
        and profile.student_orientation.slug != profile.programme_orientation.slug
    )
    active = (
        profile.student_orientation
        if has_orientation_pivot
        and base.archetype == "ACADEMIC_PREPARATION"
        and profile.student_orientation is not None
        else (
            profile.programme_orientation
            if has_orientation_pivot
            and base.archetype in {"WHY_PROGRAMME", "RESEARCH_PLAN"}
            and profile.programme_orientation is not None
            else profile.active_orientation
        )
    )
    if active is None:
        return base
    contrasted_label = (
        profile.contrasted_orientations[0].label
        if profile.contrasted_orientations
        else "adjacent sub-tracks"
    )
    if active.slug in _NON_STEAM_EPISTEMIC_SLUGS:
        if base.archetype in {"ACADEMIC_PREPARATION", "WHY_PROGRAMME", "RESEARCH_PLAN"}:
            pivot_clause = (
                f" Bridge explicitly from prior preparation in "
                f"'{profile.student_orientation.label}' into the target track "
                f"'{profile.programme_orientation.label}'."
                if has_orientation_pivot
                and profile.student_orientation is not None
                and profile.programme_orientation is not None
                else ""
            )
            return DisciplinaryExemplar(
                discipline=base.discipline,
                archetype=base.archetype,
                move_sequence=f"[{active.label}] {base.move_sequence}",
                cadence_target=base.cadence_target,
                negative_trial=base.negative_trial,
                error_explanation=(
                    f"{base.error_explanation} Anchor the argument in '{active.label}' "
                    f"({', '.join(active.track_keywords[:4])}) rather than conflating it with "
                    f"'{contrasted_label}'.{pivot_clause}"
                ),
                positive_pattern=base.positive_pattern,
            )
        return base
    is_unit_ai = _is_ai_or_data_orientation(active)
    if not (
        is_unit_ai
        or profile.is_ai_data_orientation
        or profile.is_theoretical_mechanistic_orientation
    ):
        return base
    domain_label = (
        profile.resolution.parent_fields[0]
        if profile.resolution.parent_fields
        else profile.resolution.raw_field or "the domain"
    )

    if is_unit_ai:
        if base.archetype == "ACADEMIC_PREPARATION":
            return DisciplinaryExemplar(
                discipline=RhetoricalDiscipline.STEM_QUANT,
                archetype="ACADEMIC_PREPARATION",
                move_sequence=(
                    f"Move 1 (Representation & Model Artifact in {active.label}): State the "
                    "representation, dataset, descriptor pipeline, or learning architecture "
                    "built in the verified fact and its scale -> Move 2 (Generalization or "
                    "Inductive-Bias Bottleneck): Pinpoint where out-of-distribution shifts, "
                    "sparse domain labels, or physical/structural validity constraints caused "
                    "the model to break -> Move 3 (Algorithmic-Domain Question): Formulate the "
                    "open question at the intersection of machine learning and "
                    f"{domain_label}."
                ),
                cadence_target=base.cadence_target,
                negative_trial=base.negative_trial,
                error_explanation=(
                    f"{base.error_explanation} In addition, keep the framing anchored in "
                    f"'{active.label}' (data representation, learning, and predictive/generative "
                    f"modeling) rather than conflating it with '{contrasted_label}'."
                ),
                positive_pattern=(
                    "In <FACT_ANCHOR_COURSE_OR_PROJECT>, I trained <MODEL_OR_REPRESENTATION> "
                    "across <QUANTITATIVE_DATASET_SCALE>. "
                    "While predictions generalized on <IN_DISTRIBUTION_BENCHMARK>, performance "
                    "degraded when <OOD_SCAFFOLD_OR_SPARSE_LABEL_CONDITION_BROKE>, exposing a "
                    "limit in how the representation encoded <DOMAIN_VALIDITY_CONSTRAINT>. "
                    "Adding <BASELINE_REGULARIZATION_OR_DESCRIPTOR> improved fit but could not "
                    "guarantee <INVARIANCE_OR_PHYSICAL_CONSISTENCY>. "
                    "Closing that representation gap drives my graduate direction."
                ),
            )
        if base.archetype == "WHY_PROGRAMME" and has_research_fit:
            return DisciplinaryExemplar(
                discipline=RhetoricalDiscipline.STEM_QUANT,
                archetype="WHY_PROGRAMME",
                move_sequence=(
                    f"Move 1 (AI/Data-Driven Methodological Gap in {active.label}): Specify the "
                    "representation-learning, generative, or statistical-inference capability "
                    "needed next -> Move 2 (Sourced Lab/Module Bridge): Connect "
                    "<SOURCED_ENTITY>'s published finding or open question directly to the "
                    "applicant's representation/generalization bottleneck (without conflating "
                    f"this track with '{contrasted_label}') -> Move 3 (Concrete Synthesis): "
                    "State how combining both advances the problem."
                ),
                cadence_target=base.cadence_target,
                negative_trial=base.negative_trial,
                error_explanation=(
                    f"{base.error_explanation} Keep the methodological link focused on "
                    f"'{active.label}' rather than '{contrasted_label}'."
                ),
                positive_pattern=base.positive_pattern,
            )
        if base.archetype == "RESEARCH_PLAN":
            return DisciplinaryExemplar(
                discipline=RhetoricalDiscipline.STEM_QUANT,
                archetype="RESEARCH_PLAN",
                move_sequence=(
                    f"Move 1 (Domain-Constrained ML/Data Hypothesis in {active.label}): Pose the "
                    "predictive, generative, or representation-learning question under domain "
                    "constraints -> Move 2 (Benchmark & Generalization Protocol): Specify the "
                    "architecture, out-of-distribution evaluation split, and uncertainty or "
                    "validity metric -> Move 3 (Execution Feasibility): Anchor feasibility in "
                    "the applicant's verified codebase or prior quantitative pipeline."
                ),
                cadence_target=base.cadence_target,
                negative_trial=base.negative_trial,
                error_explanation=(
                    f"{base.error_explanation} Frame the methodology around '{active.label}' "
                    f"rather than '{contrasted_label}'."
                ),
                positive_pattern=base.positive_pattern,
            )
        return base

    # First-principles / theoretical / quantum / mechanistic simulation orientation
    # (e.g. `computational_quantum_chemistry`, `systems_structural_biology`,
    # `quantitative_mathematical_finance`, `computational_corpus_linguistics`):
    if base.archetype == "ACADEMIC_PREPARATION":
        return DisciplinaryExemplar(
            discipline=base.discipline,
            archetype="ACADEMIC_PREPARATION",
            move_sequence=(
                f"Move 1 (First-Principles / Mechanistic System in {active.label}): State the "
                "theoretical formulation, quantum/electronic-structure calculation, dynamical "
                "simulation, or structural model executed in the verified fact -> Move 2 "
                "(Approximation, Correlation, or Sampling Bottleneck): Pinpoint where the level "
                "of theory, Hamiltonian/force-field approximation, or sampling timescale hit an "
                "accuracy or scaling limit -> Move 3 (Theoretical/Mechanistic Question): State "
                "the physical, chemical, or mechanistic question left open."
            ),
            cadence_target=base.cadence_target,
            negative_trial=base.negative_trial,
            error_explanation=(
                f"{base.error_explanation} In addition, keep the framing anchored in "
                f"'{active.label}' (first-principles theory, mechanistic simulation, and "
                f"physical observables) rather than conflating it with black-box "
                f"'{contrasted_label}'."
            ),
            positive_pattern=(
                "In <FACT_ANCHOR_THESIS_OR_SIMULATION>, I modeled <PHYSICAL_OR_MOLECULAR_SYSTEM> "
                "using <VERIFIED_THEORETICAL_OR_SIMULATION_METHOD>. "
                "While the approximation captured <EQUILIBRIUM_OR_BASELINE_OBSERVABLE>, accuracy "
                "broke down when <CORRELATION_TIMESCALE_OR_COUPLED_REGIME_DOMINATED>, exposing "
                "the limit of <BASELINE_THEORY_OR_POTENTIAL>. "
                "Refining the calculation within our compute budget could not resolve "
                "<FREE_ENERGY_OR_ELECTRONIC_MECHANISM>. "
                "Overcoming that theoretical bottleneck motivates my graduate study."
            ),
        )
    if base.archetype == "WHY_PROGRAMME" and has_research_fit:
        return DisciplinaryExemplar(
            discipline=base.discipline,
            archetype="WHY_PROGRAMME",
            move_sequence=(
                f"Move 1 (Theoretical/Simulation Gap in {active.label}): Specify the "
                "first-principles, multiscale, or mechanistic methodology needed to resolve "
                "the applicant's open question -> Move 2 (Sourced Group/Module Bridge): Connect "
                "<SOURCED_ENTITY>'s theoretical or computational finding directly to the "
                "applicant's approximation/sampling bottleneck (distinguishing this track from "
                f"'{contrasted_label}') -> Move 3 (Mechanistic Synergy): State the concrete "
                "theoretical or experimental observable to be investigated."
            ),
            cadence_target=base.cadence_target,
            negative_trial=base.negative_trial,
            error_explanation=(
                f"{base.error_explanation} Keep the methodological link focused on "
                f"'{active.label}' rather than '{contrasted_label}'."
            ),
            positive_pattern=base.positive_pattern,
        )
    if base.archetype == "RESEARCH_PLAN":
        return DisciplinaryExemplar(
            discipline=base.discipline,
            archetype="RESEARCH_PLAN",
            move_sequence=(
                f"Move 1 (Mechanistic/Theoretical Hypothesis in {active.label}): State the "
                "physical, quantum, or structural mechanism to be resolved -> Move 2 "
                "(Multiscale/Theoretical Protocol & Observable Validation): Specify the level "
                "of theory, sampling method, and experimental or thermodynamic observable for "
                "validation -> Move 3 (Feasibility Anchor): Tie execution feasibility to the "
                "applicant's verified prior simulation or theoretical work."
            ),
            cadence_target=base.cadence_target,
            negative_trial=base.negative_trial,
            error_explanation=(
                f"{base.error_explanation} Frame the methodology around '{active.label}' "
                f"rather than '{contrasted_label}'."
            ),
            positive_pattern=base.positive_pattern,
        )
    return base


def select_exemplars_for_letter(
    *,
    programme_name: str = "",
    facts: Mapping[UUID, VerifiedFact] | None = None,
    inputs: Mapping[UUID, NarrativeInput] | None = None,
    readings: Sequence[UsableReading] = (),
    storyline: Storyline | None = None,
    student: object | None = None,
    research_interests: Sequence[str] = (),
    archetypes: Sequence[str] = (),
    portfolio_led: bool = False,
    forbid_naming: bool = False,
    limit: int = 3,
) -> tuple[DisciplinaryExemplar, ...]:
    """Return 2-3 vetted delexicalized Trial-Error-Explain exemplars dynamically
    routed across the student's background discipline, the target programme's
    discipline, the resolved `FieldOrientation` sub-track (e.g. `ai_digital_chemistry`
    vs `computational_quantum_chemistry` in Chemoinformatics), and the live
    research-fit topology."""
    orientation_profile = resolve_field_orientation_profile(
        programme_name=programme_name,
        facts=facts,
        inputs=inputs,
        readings=readings,
        storyline=storyline,
        student=student,
        research_interests=research_interests,
    )
    programme_discipline = resolve_rhetorical_discipline(
        programme_name=programme_name,
        facts=facts,
        inputs=inputs,
        readings=readings,
        storyline=storyline,
        student=student,
        research_interests=research_interests,
        portfolio_led=portfolio_led,
    )
    has_student_evidence = bool(
        readings
        or any(
            f.category != VerifiedFact.Category.IDENTITY for f in (facts or {}).values()
        )
    )
    student_discipline = (
        resolve_rhetorical_discipline(
            programme_name="",
            facts=facts,
            inputs=inputs,
            readings=readings,
            storyline=storyline,
            student=student,
            research_interests=research_interests,
            portfolio_led=portfolio_led,
        )
        if has_student_evidence
        else programme_discipline
    )
    has_research_fit = not forbid_naming and (
        inputs is None
        or any(
            entry.kind == NarrativeInput.Kind.RESEARCH_FIT
            and isinstance(entry.provenance, dict)
            for entry in inputs.values()
        )
    )
    by_key: dict[tuple[RhetoricalDiscipline, str], DisciplinaryExemplar] = {
        (ex.discipline, ex.archetype): ex for ex in _EXEMPLAR_CATALOG
    }
    stem_fallback: dict[str, DisciplinaryExemplar] = {
        ex.archetype: ex
        for ex in _EXEMPLAR_CATALOG
        if ex.discipline == RhetoricalDiscipline.STEM_QUANT
    }

    selected: list[DisciplinaryExemplar] = []
    seen_archetypes: set[str] = set()
    target_archetypes = tuple(archetypes) or ("ACADEMIC_PREPARATION", "WHY_PROGRAMME")

    for arch in target_archetypes:
        if arch in seen_archetypes:
            continue
        unit_disc = (
            student_discipline if arch == "ACADEMIC_PREPARATION" else programme_discipline
        )
        match = (
            by_key.get((unit_disc, arch))
            or _UNIVERSAL_EXEMPLARS.get(arch)
            or stem_fallback.get(arch)
        )
        if match is not None:
            match = _specialize_exemplar_for_orientation(
                match,
                orientation_profile,
                has_research_fit=has_research_fit,
            )
            if arch == "WHY_PROGRAMME":
                match = _adapt_why_programme_exemplar(
                    match,
                    programme_discipline=programme_discipline,
                    student_discipline=student_discipline,
                    inputs=inputs,
                    forbid_naming=forbid_naming,
                    orientation_profile=orientation_profile,
                )
            selected.append(match)
            seen_archetypes.add(arch)
            if len(selected) >= limit:
                return tuple(selected)

    for fallback_arch in ("ACADEMIC_PREPARATION", "WHY_PROGRAMME", "RESEARCH_PLAN"):
        if fallback_arch in seen_archetypes:
            continue
        unit_disc = (
            student_discipline
            if fallback_arch == "ACADEMIC_PREPARATION"
            else programme_discipline
        )
        match = by_key.get((unit_disc, fallback_arch)) or stem_fallback.get(fallback_arch)
        if match is not None:
            match = _specialize_exemplar_for_orientation(
                match,
                orientation_profile,
                has_research_fit=has_research_fit,
            )
            if fallback_arch == "WHY_PROGRAMME":
                match = _adapt_why_programme_exemplar(
                    match,
                    programme_discipline=programme_discipline,
                    student_discipline=student_discipline,
                    inputs=inputs,
                    forbid_naming=forbid_naming,
                    orientation_profile=orientation_profile,
                )
            selected.append(match)
            seen_archetypes.add(fallback_arch)
            if len(selected) >= limit:
                break

    return tuple(selected[:limit])


_GUIDING_QUESTIONS_BY_ARCHETYPE: dict[str, str] = {
    "OPENING": (
        "Who is the applicant today, what specific programme or award are they applying for, "
        "and what concrete technical or analytical question drives this application?"
    ),
    "ACADEMIC_PREPARATION": (
        "What concrete coursework, thesis, project, or quantitative outcome in the committed "
        "facts proves the applicant's preparation, and what specific methodological limit or "
        "open question did that work expose?"
    ),
    "WHY_PROGRAMME": (
        "What specific intellectual or methodological gap separates the applicant's prior work "
        "from their target goal, and how does the committed programme research fact (or the "
        "applicant's own technical need when no programme fact is given) bridge that gap?"
    ),
    "RESEARCH_PLAN": (
        "What concrete research question and methodology does the applicant propose to pursue, "
        "and which committed prior fact proves they can execute it?"
    ),
    "WHY_COUNTRY": (
        "Why does this country's academic, technical, or sectoral research ecosystem fit the "
        "applicant's specific problem and post-study plan without generic tourist praise?"
    ),
    "CAREER_PLAN_RETURN": (
        "What concrete next professional or research step will the applicant take after "
        "graduation, in which sector, and how does this programme enable it?"
    ),
    "HOME_COUNTRY_CONTRIBUTION": (
        "What observable sectoral or workflow bottleneck at home (backed by any committed "
        "home-country or development-impact source) will the applicant address using the "
        "specific capability gained in this programme?"
    ),
    "LEADERSHIP_EXAMPLE": (
        "In what concrete recent situation did the applicant personally take initiative ('I', "
        "never 'we'), what action did they take, and what measurable outcome changed?"
    ),
    "RELATIONSHIP_COMMUNITY": (
        "How did the applicant personally build or mobilize a professional, academic, or "
        "community relationship ('I', never 'we') and what concrete result did it produce?"
    ),
    "PERSONAL_BACKGROUND": (
        "What factual academic, professional, or accounted-for timeline transition in the "
        "ledger explains the applicant's trajectory without childhood clichés?"
    ),
    "LANGUAGE_PLAN": (
        "What is the applicant's verified current proficiency in the host or instruction "
        "language, and what concrete steps will they take to reach the target level?"
    ),
    "CLOSING": (
        "How do the applicant's verified preparation and concrete post-graduation objective "
        "tie together as a direct closing commitment without introducing new unverified claims?"
    ),
}

_ARCHETYPE_FACT_CATEGORIES: dict[str, tuple[str, ...]] = {
    "OPENING": (
        VerifiedFact.Category.EDUCATION,
        VerifiedFact.Category.RESEARCH,
        VerifiedFact.Category.EXPERIENCE,
    ),
    "ACADEMIC_PREPARATION": (
        VerifiedFact.Category.EDUCATION,
        VerifiedFact.Category.RESEARCH,
        VerifiedFact.Category.PUBLICATION,
        VerifiedFact.Category.SKILL,
        VerifiedFact.Category.AWARD,
    ),
    "WHY_PROGRAMME": (
        VerifiedFact.Category.RESEARCH,
        VerifiedFact.Category.PUBLICATION,
        VerifiedFact.Category.EDUCATION,
        VerifiedFact.Category.SKILL,
    ),
    "RESEARCH_PLAN": (
        VerifiedFact.Category.RESEARCH,
        VerifiedFact.Category.PUBLICATION,
        VerifiedFact.Category.EDUCATION,
        VerifiedFact.Category.SKILL,
    ),
    "WHY_COUNTRY": (
        VerifiedFact.Category.EXPERIENCE,
        VerifiedFact.Category.RESEARCH,
        VerifiedFact.Category.EDUCATION,
    ),
    "CAREER_PLAN_RETURN": (
        VerifiedFact.Category.EXPERIENCE,
        VerifiedFact.Category.RESEARCH,
        VerifiedFact.Category.EDUCATION,
    ),
    "HOME_COUNTRY_CONTRIBUTION": (
        VerifiedFact.Category.EXPERIENCE,
        VerifiedFact.Category.RESEARCH,
        VerifiedFact.Category.EDUCATION,
    ),
    "LEADERSHIP_EXAMPLE": (
        VerifiedFact.Category.EXPERIENCE,
        VerifiedFact.Category.AWARD,
        VerifiedFact.Category.RESEARCH,
    ),
    "RELATIONSHIP_COMMUNITY": (
        VerifiedFact.Category.EXPERIENCE,
        VerifiedFact.Category.RESEARCH,
    ),
    "PERSONAL_BACKGROUND": (
        VerifiedFact.Category.TIMELINE,
        VerifiedFact.Category.EDUCATION,
        VerifiedFact.Category.EXPERIENCE,
    ),
    "LANGUAGE_PLAN": (
        VerifiedFact.Category.LANGUAGE,
        VerifiedFact.Category.EDUCATION,
    ),
    "CLOSING": (
        VerifiedFact.Category.EDUCATION,
        VerifiedFact.Category.RESEARCH,
        VerifiedFact.Category.EXPERIENCE,
    ),
}

_ARCHETYPE_INPUT_KINDS: dict[str, tuple[str, ...]] = {
    "WHY_PROGRAMME": (
        NarrativeInput.Kind.RESEARCH_FIT,
        NarrativeInput.Kind.RESEARCH_PLAN,
    ),
    "RESEARCH_PLAN": (
        NarrativeInput.Kind.RESEARCH_PLAN,
        NarrativeInput.Kind.RESEARCH_FIT,
    ),
    "HOME_COUNTRY_CONTRIBUTION": (
        NarrativeInput.Kind.HOME_COUNTRY_CIRCUMSTANCES,
        NarrativeInput.Kind.DEVELOPMENT_IMPACT,
    ),
    "CAREER_PLAN_RETURN": (
        NarrativeInput.Kind.DEVELOPMENT_IMPACT,
        NarrativeInput.Kind.HOME_COUNTRY_CIRCUMSTANCES,
        NarrativeInput.Kind.RESEARCH_PLAN,
    ),
    "PERSONAL_BACKGROUND": (
        NarrativeInput.Kind.PERSONAL_BACKGROUND,
    ),
    "LANGUAGE_PLAN": (
        NarrativeInput.Kind.LANGUAGE_PLAN,
    ),
}


def build_question_focus_plan(
    *,
    archetypes: Sequence[str],
    facts: Mapping[UUID, VerifiedFact],
    inputs: Mapping[UUID, NarrativeInput],
    storyline: Storyline | None = None,
    programme_name: str = "",
    readings: Sequence[UsableReading] = (),
    student: object | None = None,
    research_interests: Sequence[str] = (),
    portfolio_led: bool = False,
    forbid_naming: bool = False,
) -> tuple[QuestionFocusUnitPlan, ...]:
    """Pass 1: Build a deterministic Question-Focus Discourse Plan (Wang et al. 2025;
    Slobodkin et al. 2024; Gupta & Bedi 2026) binding each unit archetype to its
    guiding warrant question, attentional foci, committed evidence IDs, and
    disciplinary move-cadence targets."""
    if not archetypes:
        return ()

    orientation_profile = resolve_field_orientation_profile(
        programme_name=programme_name,
        facts=facts,
        inputs=inputs,
        readings=readings,
        storyline=storyline,
        student=student,
        research_interests=research_interests,
    )
    exemplars = select_exemplars_for_letter(
        programme_name=programme_name,
        facts=facts,
        inputs=inputs,
        readings=readings,
        storyline=storyline,
        student=student,
        research_interests=research_interests,
        archetypes=archetypes,
        portfolio_led=portfolio_led,
        forbid_naming=forbid_naming,
        limit=max(3, len(archetypes)),
    )
    exemplar_by_arch = {ex.archetype: ex for ex in exemplars}
    default_exemplar = exemplars[0] if exemplars else _EXEMPLAR_CATALOG[0]

    anchor_order = list(storyline.anchors) if storyline is not None else []
    non_identity_facts = {
        fid: f
        for fid, f in facts.items()
        if f.category != VerifiedFact.Category.IDENTITY
    }

    plans: list[QuestionFocusUnitPlan] = []
    for arch in archetypes:
        preferred_cats = _ARCHETYPE_FACT_CATEGORIES.get(arch, ())
        committed_fids: list[str] = []
        # 1. Storyline anchors matching this archetype's preferred categories first
        for aid in anchor_order:
            fact = non_identity_facts.get(aid)
            if fact is not None and (not preferred_cats or fact.category in preferred_cats):
                committed_fids.append(str(aid))
        # 2. Other confirmed facts in preferred categories
        for cat in preferred_cats:
            for fid, fact in non_identity_facts.items():
                if fact.category == cat and str(fid) not in committed_fids:
                    committed_fids.append(str(fid))
        # 3. Fallback to storyline anchors or any non-identity fact so a body unit never starves
        if not committed_fids:
            for aid in anchor_order:
                if aid in non_identity_facts:
                    committed_fids.append(str(aid))
            for fid in non_identity_facts:
                if str(fid) not in committed_fids:
                    committed_fids.append(str(fid))

        preferred_input_kinds = _ARCHETYPE_INPUT_KINDS.get(arch, ())
        committed_iids: list[str] = []
        committed_urls: list[str] = []
        for iid, entry in inputs.items():
            if forbid_naming and entry.kind == NarrativeInput.Kind.RESEARCH_FIT:
                continue
            if preferred_input_kinds and entry.kind not in preferred_input_kinds:
                continue
            committed_iids.append(str(iid))
            if isinstance(entry.provenance, dict):
                for url_key in ("source_url", "paper_url"):
                    u = entry.provenance.get(url_key)
                    if isinstance(u, str) and u and u not in committed_urls:
                        committed_urls.append(u)

        ex = exemplar_by_arch.get(arch, default_exemplar)
        foci: list[str] = [f"discipline_register:{ex.discipline}"]
        if orientation_profile.active_orientation is not None:
            active_o = orientation_profile.active_orientation
            foci.append(f"active_orientation:{active_o.slug} ({active_o.label})")
            if active_o.track_keywords:
                foci.append(f"orientation_track_keywords:{','.join(active_o.track_keywords[:6])}")
            if orientation_profile.contrasted_orientations:
                contrasted_o = orientation_profile.contrasted_orientations[0]
                foci.append(
                    "contrasted_subtrack_not_to_conflate:"
                    f"{contrasted_o.slug} ({contrasted_o.label})"
                )
            if (
                orientation_profile.student_orientation is not None
                and orientation_profile.programme_orientation is not None
                and orientation_profile.student_orientation.slug
                != orientation_profile.programme_orientation.slug
            ):
                stu_slug = orientation_profile.student_orientation.slug
                prog_slug = orientation_profile.programme_orientation.slug
                foci.append(f"intra_family_orientation_bridge:{stu_slug}->{prog_slug}")
                if arch == "ACADEMIC_PREPARATION":
                    foci.append(f"anchor_prior_work_in_student_subtrack:{stu_slug}")
                    foci.append(f"expose_limit_motivating_bridge_to:{prog_slug}")
                elif arch in {"WHY_PROGRAMME", "RESEARCH_PLAN"}:
                    foci.append(
                        f"bridge_from_student_subtrack:{stu_slug}_to_programme_subtrack:{prog_slug}"
                    )
        committed_schema_keys: list[str] = []
        for fid_str in committed_fids[:6]:
            for fid_uuid, fact_obj in non_identity_facts.items():
                if str(fid_uuid) == fid_str and isinstance(fact_obj.payload, dict):
                    for k, v in fact_obj.payload.items():
                        if v not in (None, "", [], {}) and str(k) not in committed_schema_keys:
                            committed_schema_keys.append(str(k))
        if committed_schema_keys:
            foci.append(f"committed_fact_fields:{','.join(committed_schema_keys[:8])}")
        for iid_str in committed_iids[:4]:
            for iid_uuid, entry_obj in inputs.items():
                if str(iid_uuid) == iid_str and isinstance(entry_obj.provenance, dict):
                    if fit_mode := str(entry_obj.provenance.get("fit_mode") or "").strip():
                        foci.append(f"fit_mode:{fit_mode}")
                    if entry_obj.provenance.get("paper_method_or_question"):
                        foci.append("connect_to_paper_method_or_question")
        if storyline is not None and storyline.theme:
            foci.append(f"unifying_theme:{storyline.theme[:120]}")
        if storyline is not None and storyline.gap and arch in {"WHY_PROGRAMME", "RESEARCH_PLAN"}:
            foci.append(f"training_gap:{storyline.gap[:120]}")
        if committed_fids:
            foci.append("cite_committed_fact_id_on_every_factual_sentence")
        if committed_urls:
            foci.append("cite_committed_input_id_and_source_url_on_programme_or_context_sentence")

        plans.append(
            QuestionFocusUnitPlan(
                archetype=arch,
                guiding_question=_GUIDING_QUESTIONS_BY_ARCHETYPE.get(
                    arch,
                    f"How do the applicant's verified facts and inputs satisfy {arch}?",
                ),
                attentional_foci=tuple(foci),
                committed_fact_ids=tuple(committed_fids[:6]),
                committed_input_ids=tuple(committed_iids[:4]),
                committed_source_urls=tuple(committed_urls[:4]),
                move_sequence=ex.move_sequence,
                cadence_target=ex.cadence_target,
            )
        )
    return tuple(plans)


def exemplars_payload(exemplars: Sequence[DisciplinaryExemplar]) -> str | None:
    """Serialize vetted delexicalized exemplars to JSON for the user-role data block."""
    if not exemplars:
        return None
    import json

    return json.dumps(
        [
            {
                "discipline": str(ex.discipline),
                "archetype": ex.archetype,
                "move_sequence": ex.move_sequence,
                "cadence_target": ex.cadence_target,
                "negative_trial": ex.negative_trial,
                "error_explanation": ex.error_explanation,
                "positive_pattern": ex.positive_pattern,
            }
            for ex in exemplars
        ],
        sort_keys=True,
    )


def unit_plans_payload(plans: Sequence[QuestionFocusUnitPlan]) -> str | None:
    """Serialize Pass-1 Question-Focus unit discourse plans to JSON."""
    if not plans:
        return None
    import json

    return json.dumps(
        [
            {
                "archetype": plan.archetype,
                "guiding_question": plan.guiding_question,
                "attentional_foci": list(plan.attentional_foci),
                "committed_fact_ids": list(plan.committed_fact_ids),
                "committed_input_ids": list(plan.committed_input_ids),
                "committed_source_urls": list(plan.committed_source_urls),
                "move_sequence": plan.move_sequence,
                "cadence_target": plan.cadence_target,
            }
            for plan in plans
        ],
        sort_keys=True,
    )
