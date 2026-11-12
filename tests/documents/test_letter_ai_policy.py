import inspect

from apps.documents.letter_ai_policy import AIUsePolicyClass, resolve_ai_use_policy


def test_cambridge_is_prohibits() -> None:
    note = resolve_ai_use_policy("cambridge")
    assert note.policy_class == AIUsePolicyClass.PROHIBITS
    assert "hallucinations" in note.note_text.lower() or "fraud" in note.note_text.lower()


def test_rhodes_is_requires_disclosure() -> None:
    note = resolve_ai_use_policy("rhodes")
    assert note.policy_class == AIUsePolicyClass.REQUIRES_DISCLOSURE
    text = note.note_text.lower()
    assert "produced with the aid of" in text or "disclos" in text


def test_daad_is_requires_disclosure() -> None:
    note = resolve_ai_use_policy("daad")
    assert note.policy_class == AIUsePolicyClass.REQUIRES_DISCLOSURE


def test_australia_gs_is_immigration_prohibition() -> None:
    note = resolve_ai_use_policy("australia_gs")
    assert note.policy_class == AIUsePolicyClass.IMMIGRATION_PROHIBITION


def test_unmapped_funder_defaults_to_silent() -> None:
    note = resolve_ai_use_policy("some_unmapped_funder")
    assert note.policy_class == AIUsePolicyClass.SILENT
    assert "not permission" in note.note_text.lower()


def test_none_funder_defaults_to_silent() -> None:
    assert resolve_ai_use_policy(None).policy_class == AIUsePolicyClass.SILENT


def test_ai_policy_never_imported_by_gate_or_generation_modules() -> None:
    import apps.documents.letter_approval as approval_module
    import apps.documents.letter_gates as gates_module
    import apps.documents.letter_verification as verification_module
    import apps.documents.letters as letters_module

    for module in (letters_module, gates_module, verification_module, approval_module):
        source = inspect.getsource(module)
        msg = f"{module.__name__} must not import the AI-policy module"
        assert "letter_ai_policy" not in source, msg


def test_resolve_prompt_ai_policy_from_institution_immigration_and_written_requirements() -> None:
    from types import SimpleNamespace

    from apps.documents.letter_ai_policy import resolve_prompt_ai_policy

    cambridge_prompt = SimpleNamespace(
        funder_id=None,
        immigration=False,
        source_url="https://www.postgraduate.study.cam.ac.uk/application",
        programme=SimpleNamespace(
            name="MPhil in Advanced Computer Science",
            country_code="GB",
            institution=SimpleNamespace(name="University of Cambridge"),
        ),
        letter_written_requirements=[],
    )
    assert resolve_prompt_ai_policy(cambridge_prompt).policy_class == AIUsePolicyClass.PROHIBITS

    au_imm_prompt = SimpleNamespace(
        funder_id=None,
        immigration=True,
        source_url="https://immi.homeaffairs.gov.au/",
        programme=SimpleNamespace(
            name="Master of Engineering",
            country_code="AU",
            institution=SimpleNamespace(name="University of Melbourne"),
        ),
        letter_written_requirements=[],
    )
    assert (
        resolve_prompt_ai_policy(au_imm_prompt).policy_class
        == AIUsePolicyClass.IMMIGRATION_PROHIBITION
    )

    dynamic_prohibit = SimpleNamespace(
        funder_id=None,
        immigration=False,
        source_url="https://example.edu/apply",
        programme=SimpleNamespace(
            name="MSc Data Science",
            country_code="NL",
            institution=SimpleNamespace(name="Example University"),
        ),
        letter_written_requirements=[
            {
                "text": (
                    "The use of generative AI or ChatGPT to write your motivation letter "
                    "is strictly prohibited and treated as fraud."
                )
            }
        ],
    )
    note = resolve_prompt_ai_policy(dynamic_prohibit)
    assert note.policy_class == AIUsePolicyClass.PROHIBITS
    assert "ChatGPT" in note.note_text

    dynamic_disclose = SimpleNamespace(
        funder_id=None,
        immigration=False,
        source_url="https://example.edu/apply",
        programme=SimpleNamespace(
            name="MSc Data Science",
            country_code="DE",
            institution=SimpleNamespace(name="Example University"),
        ),
        letter_written_requirements=[
            {
                "text": (
                    "Applicants must disclose any generative AI tools used and include "
                    "a declaration of how AI supported the draft."
                )
            }
        ],
    )
    assert (
        resolve_prompt_ai_policy(dynamic_disclose).policy_class
        == AIUsePolicyClass.REQUIRES_DISCLOSURE
    )

