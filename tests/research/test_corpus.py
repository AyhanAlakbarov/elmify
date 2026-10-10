"""The labelled CV-requirement corpus: loader, validator and scorer.

Spec: docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from apps.research.corpus import (
    PROGRAMME_COLUMNS,
    RULE_COLUMNS,
    Corpus,
    CorpusError,
    Programme,
    ProgrammeReport,
    Rule,
    contaminated_hosts,
    format_table,
    host,
    load_corpus,
    normalize_url,
    normalize_value,
    score,
    text_digest,
)

PROGRAMME_HEADER = ",".join(PROGRAMME_COLUMNS)
RULE_HEADER = ",".join(RULE_COLUMNS)

GOOD_PROGRAMME = (
    "p1,Example University,,https://example.edu,2026/27,found,deep;careers_decoy,dev"
)
GOOD_RULE = (
    "p1,https://example.edu/apply,"
    + "a" * 64
    + ',"CV: max 2 pages.",max_pages,2,BINDING,accepted,claude,hand,'
)


def _write(
    tmp_path: pathlib.Path, programmes: str, rules: str
) -> tuple[pathlib.Path, pathlib.Path]:
    p = tmp_path / "programmes.csv"
    r = tmp_path / "rules.csv"
    p.write_text(textwrap.dedent(programmes).strip() + "\n", encoding="utf-8")
    r.write_text(textwrap.dedent(rules).strip() + "\n", encoding="utf-8")
    return p, r


def test_a_well_formed_corpus_loads_with_typed_rows(tmp_path) -> None:
    p, r = _write(tmp_path, f"{PROGRAMME_HEADER}\n{GOOD_PROGRAMME}", f"{RULE_HEADER}\n{GOOD_RULE}")

    corpus = load_corpus(p, r, contaminated=frozenset())

    (programme,) = corpus.programmes
    assert programme.id == "p1"
    assert programme.strata == frozenset({"deep", "careers_decoy"})
    assert programme.split == "dev"
    (rule,) = corpus.rules
    assert rule.requirement == ("max_pages", "2")
    assert rule.enforcement == "BINDING"
    assert corpus.in_split("dev") == (programme,)
    assert corpus.rules_for("p1", "accepted") == (rule,)
    assert corpus.rules_for("p1", "rejected") == ()


def test_every_problem_is_reported_in_one_error(tmp_path) -> None:
    programmes = f"""
        {PROGRAMME_HEADER}
        p1,U,,http://example.edu,,maybe,deep;bogus,test
        p1,U,,https://example.edu,2026/27,found,,dev
    """
    rules = f"""
        {RULE_HEADER}
        ghost,https://example.edu/a,zz,,invented_key,2,SOFT,pending,me,guess,
    """
    p, r = _write(tmp_path, programmes, rules)

    with pytest.raises(CorpusError) as exc:
        load_corpus(p, r, contaminated=frozenset())

    message = str(exc.value)
    for fragment in (
        "seed_url must be https",
        "admissions_cycle is empty",
        "expected_outcome 'maybe'",
        "unknown strata ['bogus']",
        "split 'test'",
        "duplicate id",
        "unknown programme_id",
        "source_sha256 is not 64 hex",
        "sentence is empty",
        "requirement_key 'invented_key' is not in the engine's vocabulary",
        "enforcement 'SOFT'",
        "status 'pending'",
        "adjudicated_by 'me'",
        "pool_source 'guess'",
    ):
        assert fragment in message, fragment


def test_a_wrong_header_is_a_corpus_error(tmp_path) -> None:
    p, r = _write(tmp_path, "id,name\np1,x", f"{RULE_HEADER}")
    with pytest.raises(CorpusError, match="columns are"):
        load_corpus(p, r, contaminated=frozenset())


def test_unapplied_is_the_key_for_what_the_vocabulary_cannot_carry(tmp_path) -> None:
    rule = GOOD_RULE.replace("max_pages,2,BINDING", "unapplied,cv,ADVISORY_HIGH_RISK")
    p, r = _write(tmp_path, f"{PROGRAMME_HEADER}\n{GOOD_PROGRAMME}", f"{RULE_HEADER}\n{rule}")
    corpus = load_corpus(p, r, contaminated=frozenset())
    assert corpus.rules[0].requirement == ("unapplied", "cv")

def test_one_identity_cannot_be_both_accepted_and_rejected(tmp_path) -> None:
    """The scorer counts a report against the accepted set and the rejected set
    independently, so one identity in both would score as a hit AND a false
    positive. Two different sentences, same (key, value): the loader refuses."""
    rejected = GOOD_RULE.replace('"CV: max 2 pages."', '"Two pages max."').replace(
        ",accepted,", ",rejected,"
    )
    p, r = _write(
        tmp_path, f"{PROGRAMME_HEADER}\n{GOOD_PROGRAMME}", f"{RULE_HEADER}\n{GOOD_RULE}\n{rejected}"
    )
    with pytest.raises(CorpusError, match=r"\(max_pages, 2\) is both accepted and rejected"):
        load_corpus(p, r, contaminated=frozenset())


def test_a_contaminated_host_may_be_dev_but_never_heldout(tmp_path) -> None:
    dev = GOOD_PROGRAMME
    held = GOOD_PROGRAMME.replace("p1,", "p2,").replace(",dev", ",heldout")
    p, r = _write(tmp_path, f"{PROGRAMME_HEADER}\n{dev}\n{held}", RULE_HEADER)

    load_corpus(p, r, contaminated=frozenset({"other.example"}))  # unrelated host: fine
    with pytest.raises(CorpusError, match="p2.*may not be held out"):
        load_corpus(p, r, contaminated=frozenset({"example.edu"}))
    # A subdomain of a contaminated host is contaminated too (static.daad.de / daad.de).
    sub = held.replace("https://example.edu", "https://static.example.edu")
    p, r = _write(tmp_path, f"{PROGRAMME_HEADER}\n{sub}", RULE_HEADER)
    with pytest.raises(CorpusError, match="may not be held out"):
        load_corpus(p, r, contaminated=frozenset({"example.edu"}))


def test_a_blank_digest_and_a_stratum_missing_from_a_split_are_warnings(tmp_path) -> None:
    rule = GOOD_RULE.replace("a" * 64, "")
    p, r = _write(tmp_path, f"{PROGRAMME_HEADER}\n{GOOD_PROGRAMME}", f"{RULE_HEADER}\n{rule}")
    corpus = load_corpus(p, r, contaminated=frozenset())
    assert any("no source_sha256" in w for w in corpus.warnings)
    assert any(w.startswith("heldout: no programme carries") for w in corpus.warnings)


def test_contaminated_hosts_come_from_the_eval_csv_and_the_survey(tmp_path) -> None:
    eval_csv = tmp_path / "eval.csv"
    eval_csv.write_text(
        "id,source,language,sentence,outcome,detail\n"
        "a,https://www.daad.de/en/x/,en,s,europass,\n"
        "b,synthetic,en,s,none,\n",
        encoding="utf-8",
    )
    hosts = contaminated_hosts(eval_csv)
    assert "daad.de" in hosts
    assert "synthetic" not in hosts
    assert "sciencespo.fr" in hosts  # from the survey list


def test_normalizers() -> None:
    assert host("https://WWW.Example.EDU/a") == "example.edu"
    assert normalize_url("https://www.example.edu/Apply/") == normalize_url("http://example.edu/apply")
    assert normalize_url("https://x.example/a?b=1") != normalize_url("https://x.example/a")
    assert normalize_value("  Europass_Required ") == "europass_required"
    assert text_digest("a  b\n\nc") == text_digest("a b c")
    assert len(text_digest("x")) == 64


def _programme(
    pid: str, *, expected: str = "found", strata: str = "", split: str = "dev"
) -> Programme:
    return Programme(
        id=pid,
        institution="U",
        funder="",
        seed_url=f"https://{pid}.example",
        admissions_cycle="2026/27",
        expected_outcome=expected,
        strata=frozenset(s for s in strata.split(";") if s),
        split=split,
    )


def _rule(
    pid: str,
    key: str,
    value: str,
    *,
    enforcement: str = "BINDING",
    status: str = "accepted",
    url: str | None = None,
    sentence: str = "s",
) -> Rule:
    return Rule(
        programme_id=pid,
        source_url=url or f"https://{pid}.example/apply",
        source_sha256="",
        sentence=sentence,
        requirement_key=key,
        requirement_value=value,
        enforcement=enforcement,
        status=status,
        adjudicated_by="claude",
        pool_source="hand",
        note="",
    )


def _report(
    pid: str,
    *requirements: tuple[str, str],
    outcome: str = "found",
    statements: tuple[tuple[str, str], ...] = (),
) -> ProgrammeReport:
    return ProgrammeReport(
        programme_id=pid,
        outcome=outcome,
        statements=statements,
        requirements=tuple((k, v, "BINDING") for k, v in requirements),
    )


def test_binding_recall_is_scored_apart_from_advisory_recall() -> None:
    corpus = Corpus(
        programmes=(_programme("p"),),
        rules=(
            _rule("p", "max_pages", "2"),
            _rule("p", "cv_format_requirement", "europass_required"),
            _rule("p", "cv_directive", "emphasise(experience)", enforcement="ADVISORY_HIGH_RISK"),
        ),
        warnings=(),
    )
    reports = {"p": _report("p", ("max_pages", "2"))}

    table = score(corpus, reports, split="dev", per_stratum=False)

    tally = table.rows["ALL"]
    assert (tally.binding_hit, tally.binding_total) == (1, 2)
    assert tally.binding_recall == 0.5
    assert (tally.hit, tally.total) == (1, 3)
    assert tally.precision == 1.0
    assert tally.unjudged == 0


def test_precision_counts_rejected_rules_as_false_positives_and_lists_the_unjudged() -> None:
    corpus = Corpus(
        programmes=(_programme("p"),),
        rules=(
            _rule("p", "max_pages", "2"),
            _rule("p", "photo_allowed", "false", status="rejected"),
        ),
        warnings=(),
    )
    reports = {
        "p": _report("p", ("max_pages", "2"), ("photo_allowed", "False"), ("language", "de"))
    }

    table = score(corpus, reports, split="dev", per_stratum=False)

    tally = table.rows["ALL"]
    assert (tally.true_positive, tally.false_positive, tally.unjudged) == (1, 1, 1)
    assert tally.precision == 0.5
    # Never counted wrong: handed back for adjudication as post_hoc.
    assert table.unjudged == (("p", "language", "de"),)


def test_two_sentences_one_requirement_collapse_and_either_url_localizes() -> None:
    en = "https://p.example/en/apply"
    fr = "https://p.example/fr/candidater"
    corpus = Corpus(
        programmes=(_programme("p"),),
        rules=(
            _rule("p", "max_pages", "2", url=en, sentence="max 2 pages"),
            _rule("p", "max_pages", "2", url=fr, sentence="2 pages maximum"),
        ),
        warnings=(),
    )
    reports = {
        "p": _report(
            "p",
            ("max_pages", "2"),
            statements=(("http://www.p.example/fr/candidater/", "2 pages maximum"),),
        )
    }

    tally = score(corpus, reports, split="dev", per_stratum=False).rows["ALL"]

    assert tally.total == 1 and tally.hit == 1
    assert tally.localization == 1.0


def test_localization_is_zero_when_the_right_answer_came_from_the_wrong_page() -> None:
    corpus = Corpus(
        programmes=(_programme("p"),),
        rules=(_rule("p", "max_pages", "2", url="https://p.example/admissions"),),
        warnings=(),
    )
    reports = {
        "p": _report(
            "p",
            ("max_pages", "2"),
            statements=(("https://p.example/careers/how-to-write-a-cv", "2 pages"),),
        )
    }
    tally = score(corpus, reports, split="dev", per_stratum=False).rows["ALL"]
    assert tally.recall == 1.0 and tally.localization == 0.0


def test_a_no_cv_programme_is_scored_on_its_outcome_only() -> None:
    corpus = Corpus(
        programmes=(_programme("p", expected="no_cv", strata="no_cv"),),
        rules=(),
        warnings=(),
    )
    right = score(corpus, {"p": _report("p", outcome="no_cv")}, split="dev", per_stratum=True)
    wrong = score(
        corpus, {"p": _report("p", outcome="not_found")}, split="dev", per_stratum=True
    )

    assert right.rows["ALL"].outcome_accuracy == 1.0
    assert wrong.rows["ALL"].outcome_accuracy == 0.0
    assert right.rows["ALL"].recall is None  # no denominator, not a zero
    assert right.rows["no_cv"].programmes == 1


def test_per_stratum_rows_are_only_built_when_asked_and_a_control_row_collects_the_rest() -> None:
    corpus = Corpus(
        programmes=(
            _programme("a", strata="deep;blocked"),
            _programme("b"),
        ),
        rules=(
            _rule("a", "max_pages", "2"),
            _rule("b", "max_pages", "1"),
        ),
        warnings=(),
    )
    reports = {"a": _report("a", ("max_pages", "2")), "b": _report("b")}

    flat = score(corpus, reports, split="dev", per_stratum=False)
    assert set(flat.rows) == {"ALL"}

    table = score(corpus, reports, split="dev", per_stratum=True)
    assert set(table.rows) == {"ALL", "deep", "blocked", "(control)"}
    assert table.rows["deep"].binding_recall == 1.0
    assert table.rows["(control)"].binding_recall == 0.0
    assert table.rows["ALL"].programmes == 2


def test_only_the_requested_split_is_scored() -> None:
    corpus = Corpus(
        programmes=(_programme("d"), _programme("h", split="heldout")),
        rules=(),
        warnings=(),
    )
    table = score(corpus, {"d": _report("d")}, split="dev", per_stratum=False)
    assert table.rows["ALL"].programmes == 1  # "h" was neither required nor scored


def test_a_drifted_source_is_excluded_from_the_denominator_and_counted() -> None:
    corpus = Corpus(
        programmes=(_programme("p"),),
        rules=(
            _rule("p", "max_pages", "2", url="https://p.example/moved"),
            _rule("p", "language", "en", url="https://p.example/still"),
        ),
        warnings=(),
    )
    drifted = frozenset({("p", normalize_url("https://p.example/moved"))})
    tally = score(
        corpus,
        {"p": _report("p", ("language", "en"))},
        split="dev",
        drifted=drifted,
        per_stratum=False,
    ).rows["ALL"]
    assert tally.total == 1 and tally.recall == 1.0
    assert tally.drifted == 1


def test_format_table_prints_a_dash_for_an_undefined_ratio() -> None:
    corpus = Corpus(programmes=(_programme("p", expected="no_cv"),), rules=(), warnings=())
    text = format_table(
        score(corpus, {"p": _report("p", outcome="no_cv")}, split="dev", per_stratum=False)
    )
    header, row = text.strip().splitlines()
    assert header.split()[:3] == ["row", "n", "bind.recall"]
    assert row.split()[:4] == ["ALL", "1", "-", "-"]
    assert row.split()[6] == "1.00"  # outcome accuracy


def test_the_committed_corpus_loads(capsys) -> None:
    """The one fast guard on the real files: any row that breaks the contract
    breaks the default suite, not the next live run."""
    corpus = load_corpus()
    assert len(corpus.programmes) >= 18
    assert len(corpus.rules) >= 17
    assert {p.split for p in corpus.programmes} <= {"dev", "heldout"}
    for warning in corpus.warnings:
        print(warning)
