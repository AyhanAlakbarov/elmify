"""A card's copy of how its programme is applied for (lanes spec §3.1).

The web tier reads this copy, never the catalogue. Plan 1b writes it from the
catalogue's served route (verified-catalog spec §3.4) in this same shape; until
then the only writer is the agency fallback: the portal a person recorded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from .models import Application, PortalForm


class SnapshotDate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    date: str = ""
    timezone: str = ""
    timezone_source: str = ""
    quote: str = ""


class SnapshotStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int
    purpose: Literal["APPLY", "PRE_CHECK", "RANKING_ROUND", "VISA_PREENROL"]
    channel: Literal["PORTAL", "EMAIL", "POST", "NONE"]
    portal_url: str = ""
    portal_system: str = ""
    fee_amount: str = ""
    fee_currency: str = ""
    fee_deadline: str = ""
    dates: list[SnapshotDate] = []
    quote: str = ""
    source_url: str = ""


class RouteSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["AGENCY", "CATALOGUE"]
    route_id: str = ""
    audience: str = "ALL"
    kind: str = "SELF_FUNDED"
    intake: str = ""
    steps: list[SnapshotStep]


def snapshot_from_portal(form: PortalForm | None) -> dict[str, Any]:
    """The fallback as stored JSON: one APPLY step on the portal a person recorded,
    nothing else known; ``{}`` when no portal is recorded."""
    if form is None:
        return {}
    step = SnapshotStep(position=1, purpose="APPLY", channel="PORTAL", portal_url=form.form_url)
    return RouteSnapshot(source="AGENCY", steps=[step]).model_dump(mode="json")


def read_snapshot(application: Application) -> RouteSnapshot | None:
    """The card's snapshot, or None when there is none or it no longer parses."""
    if not application.route_snapshot:
        return None
    try:
        return RouteSnapshot.model_validate(application.route_snapshot)
    except ValidationError:
        return None
