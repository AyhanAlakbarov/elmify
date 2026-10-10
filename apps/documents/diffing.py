from __future__ import annotations

from dataclasses import dataclass

from .schemas import CVContent


@dataclass(frozen=True)
class FieldChange:
    field_path: str
    old_value: object
    new_value: object


def _walk(prefix: str, old: object, new: object, out: list[FieldChange]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            _walk(f"{prefix}.{key}" if prefix else key, old.get(key), new.get(key), out)
        return
    if isinstance(old, list) and isinstance(new, list):
        for index in range(max(len(old), len(new))):
            old_item = old[index] if index < len(old) else None
            new_item = new[index] if index < len(new) else None
            _walk(f"{prefix}[{index}]", old_item, new_item, out)
        return
    if old != new:
        out.append(FieldChange(prefix, old, new))


def diff_cv_content(old: CVContent, new: CVContent) -> tuple[FieldChange, ...]:
    changes: list[FieldChange] = []
    _walk("", old.model_dump(mode="json"), new.model_dump(mode="json"), changes)
    return tuple(changes)
