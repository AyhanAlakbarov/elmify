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
