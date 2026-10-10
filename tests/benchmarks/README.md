# Benchmark fixtures — SYNTHETIC, NOT REAL ACCEPTANCE EVIDENCE

Every JSON file under `tests/benchmarks/` (`profiles/`, `reference_opportunities/`,
`cities/`) is a **hand-written, obviously fake placeholder**. Each file carries
`"_synthetic": true`. They exist only to exercise the Phase 1 scorecard
*pipeline* end to end (`scripts/evaluate_phase1.py`, `tests/acceptance/`) so
that the RED (missing evidence) -> GREEN (evidence present, correct shape)
mechanics can be proven to work correctly.

**They are NOT:**

- The five blinded reference lists an independent researcher must build
  without seeing AI output (`phased requirements.md` Section 3.5, item 1).
- The at-least-20 consultant-reviewed diverse profiles with reason codes
  (Section 3.5, item 2).
- Real student data of any kind.

**Phase 1 has not passed acceptance on the basis of this fixture data.**
`scripts/evaluate_phase1.py` detects the `_synthetic` marker and refuses to
report a real PASS — see its `--output` report for the explicit
"SYNTHETIC DATA — NOT REAL ACCEPTANCE EVIDENCE" banner and exit code 2.

Real acceptance requires:

1. An independent researcher to replace `reference_opportunities/*.json`
   with reference lists built without seeing this system's output.
2. A consultant to replace `profiles/*.json` with real (pseudonymized)
   reviewed-outcome labels and reason codes for at least 20 diverse profiles.
3. Re-running `uv run python scripts/evaluate_phase1.py` against that real
   data before any shadow-pilot go/no-go decision is made.

## Shape these fixtures exercise

- Five distinct cities (`cities/*.json`).
- One profile with an explicitly selected non-English teaching language.
- One profile with a funding-dependent (`FUNDING_FIRST`) strategy.
- A paired one-year / two-year duration-preference profile pair.
- Five profiles paired 1:1 with a blinded reference list, for
  precision/recall computation.
