"""The provenance vetoes' Jev (TypeSafe System One) client, reached through OpenRouter.

Owner decision 2026-09-26: `POST {JEV_BASE_URL}/v1/systemone` -- OpenRouter's
native route, the same request shape as api.typesafe.ai (a `state` and typed
`questions`), authenticated with the OpenRouter key. Not chat completions:
OpenRouter's `typesafe/jev-router` is a router over chat models, not Jev's
typed classifier. The model is a pinned versioned ID (`JEV_MODEL`, never
`jev-latest`), because a tuned threshold is pinned to the model that produced
it (2026-09-22 typed-decisions spec §3); the reply's `model` field names what
actually answered, and a caller that pins a threshold checks it.

Only page text is ever sent, never student data. Its caller is
apps/research/blocking.py. It coexists with the typed-decision layer's client
(apps/research/decisions.py); unifying the two is an open design decision.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from .egress import fetch_json_api


class JevUnavailable(RuntimeError):
    """No key, a transport failure, or a reply without answers."""


@dataclass(frozen=True)
class JevReply:
    answers: dict[str, Any]
    model: str
    input_tokens: int


def jev_url() -> str:
    return f"{settings.JEV_BASE_URL.rstrip('/')}/v1/systemone"


def ask(
    state: object,
    questions: Mapping[str, object],
    *,
    post: Callable[..., dict[str, object]] = fetch_json_api,
    api_key: str | None = None,
) -> JevReply:
    key = settings.JEV_API_KEY if api_key is None else api_key
    if not key:
        raise JevUnavailable("OPENROUTER_API_KEY is not set")
    try:
        data = post(
            jev_url(),
            payload={"state": state, "model": settings.JEV_MODEL, "questions": dict(questions)},
            headers={"Authorization": f"Bearer {key}"},
        )
    except Exception as error:  # noqa: BLE001 - any vendor failure is JevUnavailable
        # The type only: a transport message can echo request headers.
        # from None: a chained __cause__ can carry the Authorization header
        # into whatever logs the traceback.
        raise JevUnavailable(f"jev call failed: {type(error).__name__}") from None
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise JevUnavailable("jev reply had no answers")
    usage = data.get("usage")
    tokens = int(usage.get("input_tokens", 0)) if isinstance(usage, dict) else 0
    return JevReply(answers=answers, model=str(data.get("model") or ""), input_tokens=tokens)
