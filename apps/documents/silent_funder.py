"""Silent-funder playbook: default prompt shape when research finds nothing published.

Applies when ``ApplicationPrompt.source == UNRESOLVED`` -- a funder who published
nothing has not imposed a word limit, so the default length must never become a
bound. It is not returned here at all, and that is how it stays advisory:
``generate_letter`` recomputes the same ``defaults_for`` row from the same four
programme fields ``_create_inferred`` used, and ``target_word_count`` aims the
model at ``row.word_target`` whenever the stored prompt states no cap of its own.
This function used to return it as an ADVISORY_STYLE ``ConstraintRule`` that
``_create_inferred`` dropped on the floor -- and the only column it could have
been stored in, ``letter_max_words``, is read by ``constraints_from_shape`` as
BINDING, which would have turned a length we chose into a render block.

Archetypes come from ``letter_defaults.defaults_for`` (Task 6):
that table is keyed by mode (country's lettering system, track, portfolio-led)
rather than funder kind alone, and every row cites the research rule it rests on.
The former ``DEFAULT_ARCHETYPES_BY_FUNDER_KIND`` dict (five orders written to make
the plan work and cited nothing) is deleted, not merely superseded --
``tests/documents/test_silent_funder.py`` now asserts the same one-row-per-funder-kind
property through ``apply_silent_funder_defaults``'s output instead of the dict itself.
"""

from __future__ import annotations

from apps.funding.models import ApplicationPrompt

from .letter_defaults import defaults_for


def apply_silent_funder_defaults(
    *,
    funder_kind: str,
    country_code: str = "",
    track: str = "taught",
    portfolio_led: bool = False,
) -> dict[str, object]:
    """Return the default prompt shape for a funder that published nothing.

    Archetypes come from ``letter_defaults.defaults_for``, keyed by the
    programme's mode. ``CONSORTIUM`` is the one exception: it fails closed
    rather than taking a country- or track-derived default, fixed at an empty
    tuple exactly as the old funder-kind dict always fixed it.
    """
    structure = (
        ApplicationPrompt.Structure.SHORT_ANSWER_SET
        if funder_kind == ApplicationPrompt.FunderKind.IMMIGRATION_AUTHORITY
        else ApplicationPrompt.Structure.CONTINUOUS_LETTER
    )
    if funder_kind == ApplicationPrompt.FunderKind.CONSORTIUM:
        archetypes: tuple[str, ...] = ()
    else:
        archetypes = defaults_for(
            country_code=country_code,
            track=track,
            portfolio_led=portfolio_led,
            funder_kind=funder_kind,
        ).archetypes
    return {
        "structure": structure,
        "archetypes": archetypes,
        "header_block_required": True,
    }
