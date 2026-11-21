"""Place checked GitHub and thesis/report readings onto a CV (CV evidence spec §10).

Runs after deterministic fact stamping and Stage 3 quality fixes when
`CV_REPO_BULLETS_ENABLED` is True. Only bullets with `verdict == "supported"`
ever reach the CV.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from .evidence.readings import UsableReading, reading_key
from .schemas import CVContent, ExperienceEntry, ProjectEntry, ResearchEntry

_GENERIC_WORDS = frozenset(
    {
        "university",
        "institute",
        "lab",
        "laboratory",
        "group",
        "team",
        "department",
        "center",
        "centre",
        "of",
        "the",
        "for",
        "and",
        "in",
        "at",
    }
)
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_NORM_RE = re.compile(r"\W+")
_MAX_EXPERIENCE_BULLETS = 12
_MAX_ADDED_EXPERIENCE_BULLETS = 2
_MAX_PROJECT_BULLETS = 3


def _norm(text: str) -> str:
    return _NORM_RE.sub(" ", text).strip().casefold()


def _significant_words(name: str) -> tuple[str, ...]:
    return tuple(
        w.casefold()
        for w in _WORD_RE.findall(name)
        if w.casefold() not in _GENERIC_WORDS
    )


def _meets_name_floor(name: str) -> bool:
    """Spec §10.2: at least two non-generic words, or one word of >= 8 chars."""
    words = _significant_words(name)
    return len(words) >= 2 or (len(words) == 1 and len(words[0]) >= 8)


def _whole_word_match(candidate: str, haystack: str) -> bool:
    if not _meets_name_floor(candidate):
        return False
    words = _significant_words(candidate)
    hay_words = {w.casefold() for w in _WORD_RE.findall(haystack)}
    return bool(words) and set(words).issubset(hay_words)


def match_reading_target(
    reading: UsableReading, content: CVContent
) -> tuple[str, int] | None:
    """Spec §10.2: return `("experience" | "research" | "education", index)` when
    exactly one CV entry matches `reading`, or `None` when 0 or >= 2 match."""
    targets: set[tuple[str, int]] = set()

    # 1. Organisation match (GitHub org with >= 3 commits -> ExperienceEntry)
    if (
        reading.source == "github"
        and reading.owner_type.casefold() == "organization"
        and reading.commits >= 3
    ):
        owner_login = reading.repo.split("/", 1)[0] if "/" in reading.repo else ""
        org_names = [n for n in (reading.owner_name, owner_login) if n]
        for idx, exp in enumerate(content.experience):
            hay = " ".join(p for p in (exp.employer, exp.group or "") if p)
            if any(_whole_word_match(org, hay) for org in org_names):
                targets.add(("experience", idx))

    # 2. Thesis match (reading.names == thesis_title; education + research sharing
    # one thesis_title count as a single target, represented by research).
    norm_names = {_norm(n) for n in reading.names if _norm(n)}
    research_by_thesis: dict[str, int] = {}
    for idx, res in enumerate(content.research):
        key = _norm(res.thesis_title)
        if key:
            research_by_thesis[key] = idx
            if key in norm_names:
                targets.add(("research", idx))
    for idx, edu in enumerate(content.education):
        key = _norm(edu.thesis_title or "")
        if key and key in norm_names and key not in research_by_thesis:
            targets.add(("education", idx))

    # 3. Shared name in experience (title, project, employer, group, bullets)
    # or research (thesis_title, methods, outcomes).
    qualifying_names = [n for n in reading.names if _meets_name_floor(n)]
    if qualifying_names:
        for idx, exp in enumerate(content.experience):
            exp_text = " ".join(
                part
                for part in (
                    exp.title,
                    exp.project or "",
                    exp.employer,
                    exp.group or "",
                    *exp.bullets,
                )
                if part
            )
            if any(_whole_word_match(name, exp_text) for name in qualifying_names):
                targets.add(("experience", idx))
        for idx, res in enumerate(content.research):
            res_text = " ".join(
                part
                for part in (res.thesis_title, res.methods or "", res.outcomes or "")
                if part
            )
            if any(_whole_word_match(name, res_text) for name in qualifying_names):
                targets.add(("research", idx))
        for idx, proj in enumerate(content.projects):
            proj_text = " ".join(part for part in (proj.title, *proj.bullets) if part)
            if any(_whole_word_match(name, proj_text) for name in qualifying_names):
                targets.add(("projects", idx))
    for idx, proj in enumerate(content.projects):
        if _norm(proj.title) and _norm(proj.title) in norm_names:
            targets.add(("projects", idx))

    return next(iter(targets)) if len(targets) == 1 else None


def _preferred_reading(
    target_kind: str, current: UsableReading, candidate: UsableReading
) -> UsableReading:
    """Spec §10.2: PDF wins on a research target; repo wins on an experience target."""
    if target_kind in ("research", "education"):
        if candidate.source == "pdf" and current.source != "pdf":
            return candidate
        return current
    if candidate.source == "github" and current.source != "github":
        return candidate
    return current


def _project_title(reading: UsableReading) -> str:
    if reading.names and reading.names[0].strip():
        return reading.names[0].strip()[:300]
    if "/" in reading.repo:
        return reading.repo.split("/", 1)[1].strip()[:300]
    if reading.repo.strip():
        return reading.repo.strip()[:300]
    return (reading.summary.strip() or "Project")[:300]


def apply_cv_evidence(
    content: CVContent,
    readings: Sequence[UsableReading],
    *,
    undone: frozenset[str] = frozenset(),
    include_projects: bool = True,
    switching_fields: bool = False,
) -> tuple[CVContent, tuple[dict[str, str], ...]]:
    """Place `readings` onto `content` per spec §10.2–§10.6.

    Returns `(updated_content, applied_fixes)` where each fix is
    `{"kind": "added_from_github" | "added_from_pdf", "reading": key, "target": target}`.
    """
    active = [r for r in readings if reading_key(r) not in undone]
    if not active:
        return content, ()

    matched_by_target: dict[tuple[str, int], UsableReading] = {}
    unmatched: list[UsableReading] = []
    for reading in active:
        target = match_reading_target(reading, content)
        if target is None:
            unmatched.append(reading)
            continue
        target_str = f"{target[0]}:{target[1]}"
        if f"{reading_key(reading)}@{target_str}" in undone:
            continue
        existing = matched_by_target.get(target)
        matched_by_target[target] = (
            reading
            if existing is None
            else _preferred_reading(target[0], existing, reading)
        )

    placed_names: set[str] = set()
    fixes: list[dict[str, str]] = []

    experience: list[ExperienceEntry] = list(content.experience)
    research: list[ResearchEntry] = list(content.research)
    projects: list[ProjectEntry] = list(content.projects)

    for (section, idx), reading in sorted(matched_by_target.items()):
        fix_kind = "added_from_github" if reading.source == "github" else "added_from_pdf"
        if section == "experience" and 0 <= idx < len(experience):
            entry = experience[idx]
            present = {_norm(b) for b in entry.bullets}
            added: list[str] = []
            for bullet in reading.bullets:
                if bullet.verdict != "supported":
                    continue
                norm_text = _norm(bullet.text)
                if not norm_text or norm_text in present:
                    continue
                if len(entry.bullets) + len(added) >= _MAX_EXPERIENCE_BULLETS:
                    break
                if len(added) >= _MAX_ADDED_EXPERIENCE_BULLETS:
                    break
                added.append(bullet.text[:500])
                present.add(norm_text)
            if added:
                experience[idx] = entry.model_copy(
                    update={"bullets": (*entry.bullets, *added)}
                )
                placed_names.update(_norm(n) for n in reading.names if _norm(n))
                fixes.append(
                    {
                        "kind": fix_kind,
                        "reading": reading_key(reading),
                        "target": f"experience:{idx}",
                    }
                )
        elif section == "research" and 0 <= idx < len(research):
            res_entry = research[idx]
            res_updates: dict[str, object] = {}
            if not res_entry.methods and reading.methods:
                res_updates["methods"] = reading.methods[:500]
            if not res_entry.outcomes and reading.outcomes:
                res_updates["outcomes"] = reading.outcomes[:500]
            if res_updates:
                research[idx] = res_entry.model_copy(update=res_updates)
                placed_names.update(_norm(n) for n in reading.names if _norm(n))
                fixes.append(
                    {
                        "kind": fix_kind,
                        "reading": reading_key(reading),
                        "target": f"research:{idx}",
                    }
                )
        elif section == "projects" and 0 <= idx < len(projects):
            proj_entry = projects[idx]
            present_proj = {_norm(b) for b in proj_entry.bullets}
            added_proj: list[str] = []
            for bullet in reading.bullets:
                if bullet.verdict != "supported":
                    continue
                norm_text = _norm(bullet.text)
                if not norm_text or norm_text in present_proj:
                    continue
                if len(proj_entry.bullets) + len(added_proj) >= _MAX_PROJECT_BULLETS:
                    break
                added_proj.append(bullet.text[:500])
                present_proj.add(norm_text)
            proj_updates: dict[str, object] = {}
            if added_proj:
                proj_updates["bullets"] = (*proj_entry.bullets, *added_proj)
            if not proj_entry.url and reading.url:
                proj_updates["url"] = reading.url
            if proj_entry.start_date is None and reading.first_commit:
                proj_updates["start_date"] = reading.first_commit
            if proj_entry.end_date is None and reading.last_commit:
                proj_updates["end_date"] = reading.last_commit
            if proj_updates:
                projects[idx] = proj_entry.model_copy(update=proj_updates)
                placed_names.update(_norm(n) for n in reading.names if _norm(n))
                fixes.append(
                    {
                        "kind": fix_kind,
                        "reading": reading_key(reading),
                        "target": f"projects:{idx}",
                    }
                )
        elif section == "education":
            placed_names.update(_norm(n) for n in reading.names if _norm(n))

    if include_projects:
        project_cap = (
            3
            if (switching_fields or (not research and not content.publications))
            else 2
        )
        candidate_projects: list[tuple[date, ProjectEntry, UsableReading]] = []
        for reading in unmatched:
            if f"{reading_key(reading)}@projects" in undone:
                continue
            if reading.kind not in ("project", "course_project"):
                continue
            if any(_norm(n) in placed_names for n in reading.names if _norm(n)):
                continue
            supported = [
                b.text[:500] for b in reading.bullets if b.verdict == "supported"
            ]
            if not supported:
                continue
            proj = ProjectEntry(
                title=_project_title(reading),
                url=reading.url,
                start_date=reading.first_commit,  # type: ignore[arg-type]
                end_date=reading.last_commit,  # type: ignore[arg-type]
                bullets=tuple(supported[:_MAX_PROJECT_BULLETS]),
            )
            recency = proj.end_date or proj.start_date or date.min
            candidate_projects.append((recency, proj, reading))

        candidate_projects.sort(key=lambda item: item[0], reverse=True)
        for _recency, proj, reading in candidate_projects[: max(0, project_cap - len(projects))]:
            projects.append(proj)
            fix_kind = (
                "added_from_github" if reading.source == "github" else "added_from_pdf"
            )
            fixes.append(
                {
                    "kind": fix_kind,
                    "reading": reading_key(reading),
                    "target": "projects",
                }
            )

    updated = content.model_copy(
        update={
            "experience": tuple(experience),
            "research": tuple(research),
            "projects": tuple(projects),
        }
    )
    return updated, tuple(fixes)


def annotate_readings_with_targets(
    readings: Sequence[UsableReading], content: CVContent
) -> tuple[UsableReading, ...]:
    """Attach `matched_target` (`"experience:0"`, `"research:0"`, `"projects"`, or `None`)
    to each `UsableReading` for the letter hand-off (spec §10.6)."""
    result: list[UsableReading] = []
    for reading in readings:
        target = match_reading_target(reading, content)
        if target is not None:
            label: str | None = f"{target[0]}:{target[1]}"
        elif reading.kind in ("project", "course_project") and any(
            b.verdict == "supported" for b in reading.bullets
        ):
            label = "projects"
        else:
            label = None
        result.append(replace(reading, matched_target=label))
    return tuple(result)
