"""The closed set of questions the platform asks a person, and nothing else.

Each kind is one closed question (spec 11: "ask (one closed question,
rendered), options"). Evidence and resolution are Pydantic models with
extra="forbid". The evidence model is what keeps a person out of a platform
table, and the resolution model is the trust boundary between an operator's
click and a write to the shared catalog.

A resolution is only ever validated against its item's evidence, passed as
Pydantic validation context, so a bad click raises an ordinary
`ValidationError` -- `validate_public_url`'s `UnsafeTarget` is a `ValueError`,
which Pydantic turns into one too.

Adding a kind (item 10's SITE_UNVOUCHED) is one KindSpec here, one write-back
in apply.py, and one migration widening ResolutionItem's two kind CHECKs.
test_kinds.py fails until all three agree.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from apps.research.egress import validate_public_url
from apps.research.hosts import registrable_domain
from apps.research.models import _RESOLUTION_PREFIXES, Organisation

_STRICT = ConfigDict(extra="forbid", frozen=True)

#: ResolutionItem.ask is a CharField(300).
ASK_LIMIT = 300


def _evidence(info: ValidationInfo) -> Any:
    context = info.context or {}
    if "evidence" not in context:
        raise ValueError("a resolution is only ever validated against its item's evidence")
    return context["evidence"]


def _cap(text: str) -> str:
    return text if len(text) <= ASK_LIMIT else text[: ASK_LIMIT - 1] + "…"


# --- SITE_UNKNOWN -----------------------------------------------------------


class Candidate(BaseModel):
    model_config = _STRICT
    url: str = Field(max_length=2048)
    title: str = Field(max_length=300)


# `register` shadows ABCMeta.register on BaseModel, and Pydantic warns once at
# class creation. The field is data and never called; the name is what the
# resolver and RegisterEntry.register call it, so it stays.
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message='Field name "register"', category=UserWarning)

    class SiteUnknownEvidence(BaseModel):
        """A register row with no site we could bind, or one two sources bind to
        two different bodies (a CONFLICT row -- brief D4). `why` is the conflict's
        one-line reason, e.g. "Wikidata Q1 is already on a.test"; blank for an
        UNRESOLVED row. For a CONFLICT the candidates are the conflicting bodies'
        sites."""

        model_config = _STRICT
        register: str = Field(max_length=40)
        external_key: str = Field(max_length=120)
        names: list[str] = Field(min_length=1, max_length=20)
        country_code: str = Field(max_length=2)
        candidates: list[Candidate] = Field(max_length=3)
        why: str = Field(default="", max_length=300)


class SiteUnknownResolution(BaseModel):
    model_config = _STRICT
    option: Literal["pick", "paste", "not_a_funder", "does_not_exist"]
    url: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def _against_evidence(self, info: ValidationInfo) -> SiteUnknownResolution:
        evidence: SiteUnknownEvidence = _evidence(info)
        if self.option == "pick" and self.url not in {c.url for c in evidence.candidates}:
            raise ValueError("pick must be one of the offered candidates")
        if self.option in {"pick", "paste"}:
            validate_public_url(self.url)
        elif self.url:
            raise ValueError(f"{self.option} takes no url")
        return self


def _site_ask(e: SiteUnknownEvidence) -> str:
    ask = f"Which site is {e.names[0][:200]}'s own?"
    return _cap(f"{ask} ({e.why})" if e.why else ask)


def _option_and_url(form: Mapping[str, str]) -> dict[str, object]:
    return {"option": form.get("option", ""), "url": form.get("url", "").strip()}


# --- AWARD_DISPUTED ---------------------------------------------------------


class DisputedField(BaseModel):
    model_config = _STRICT
    field: str = Field(max_length=40)
    choices: list[str] = Field(min_length=2, max_length=12)


class AwardDisputedEvidence(BaseModel):
    """A reader row no reading could serve alone. `disputed` holds only the
    split fields with a closed vocabulary (writers.AWARD_VOCABULARIES); an
    existence split is answered by the whole-row options. `why` is the one
    sentence saying why the row needs a person, stamped at filing so the
    console -- which cannot read the catalogue -- shows what the terminal does."""

    model_config = _STRICT
    canonical_key: str = Field(max_length=255)
    award_name: str = Field(max_length=80)
    page_url: str = Field(max_length=2048)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quotes: list[str] = Field(min_length=1, max_length=12)
    disputed: list[DisputedField] = Field(max_length=8)
    why: str = Field(default="", max_length=300)


class AwardDisputedResolution(BaseModel):
    model_config = _STRICT
    option: Literal["accept", "not_an_award", "third_party"]
    fields: dict[str, str] = Field(default_factory=dict)
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _against_evidence(self, info: ValidationInfo) -> AwardDisputedResolution:
        evidence: AwardDisputedEvidence = _evidence(info)
        if self.option != "accept":
            if self.fields:
                raise ValueError(f"{self.option} decides the whole row and takes no fields")
            return self
        choices = {d.field: set(d.choices) for d in evidence.disputed}
        if set(self.fields) != set(choices):
            raise ValueError("accept must answer every disputed field, and only those")
        for name, value in self.fields.items():
            if value not in choices[name]:
                raise ValueError(f"{value!r} is not a choice for {name}")
        return self


def _award_ask(e: AwardDisputedEvidence) -> str:
    fields = ", ".join(d.field for d in e.disputed) or "its benefit"
    return _cap(f"Is {e.award_name[:80]} an award on this page, and if so what is {fields}?")


def _award_form(form: Mapping[str, str]) -> dict[str, object]:
    return {
        "option": form.get("option", ""),
        "fields": {
            key.removeprefix("field:"): value
            for key, value in form.items()
            if key.startswith("field:")
        },
        "note": form.get("note", "").strip(),
    }


# --- HOST_UNREACHABLE -------------------------------------------------------


class TrailStep(BaseModel):
    model_config = _STRICT
    vendor: str = Field(max_length=20)
    rung: int = Field(ge=0, le=9)
    outcome: str = Field(max_length=20)
    reason: str = Field(default="", max_length=300)
    at: str = Field(max_length=40)


class HostUnreachableEvidence(BaseModel):
    model_config = _STRICT
    host: str = Field(max_length=253)
    url: str = Field(max_length=2048)
    trail: list[TrailStep] = Field(max_length=10)
    screenshot_object_key: str = Field(default="", max_length=500)
    #: The pipeline's one line on why it is asking: the ladder's refusal
    #: ("BLOCKED: origin_403"), or that the vendor rendered an empty shell --
    #: which no FetchAttempt row says, since the vendor reported it FETCHED.
    why: str = Field(default="", max_length=300)


class HostUnreachableResolution(BaseModel):
    model_config = _STRICT
    option: Literal["paste", "closed"]
    url: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def _against_evidence(self, info: ValidationInfo) -> HostUnreachableResolution:
        evidence: HostUnreachableEvidence = _evidence(info)
        if self.option == "closed":
            if self.url:
                raise ValueError("closed takes no url")
            return self
        validate_public_url(self.url)
        pasted = registrable_domain(urlsplit(self.url).hostname or "")
        if not pasted or pasted != registrable_domain(evidence.host):
            raise ValueError("a pasted page must be on the same organisation's domain")
        return self


def _host_ask(e: HostUnreachableEvidence) -> str:
    return _cap(f"We could not open {e.host[:200]}. Where is this page now?")


# --- KIND_OR_COUNTRY_UNSURE -------------------------------------------------


class KindOrCountryEvidence(BaseModel):
    model_config = _STRICT
    primary_domain: str = Field(max_length=253)
    homepage_title: str = Field(default="", max_length=300)
    guess_kind: str = Field(max_length=24)
    guess_country: str = Field(default="", max_length=2)
    confidence: float = Field(ge=0.0, le=1.0)


class KindOrCountryResolution(BaseModel):
    model_config = _STRICT
    option: Literal["set", "not_an_organisation"]
    kind: str = Field(default="", max_length=24)
    country_code: str = Field(default="", max_length=2)
    funds_students: bool | None = None

    @model_validator(mode="after")
    def _shape(self, info: ValidationInfo) -> KindOrCountryResolution:
        _evidence(info)
        if self.option == "not_an_organisation":
            if self.kind or self.country_code or self.funds_students is not None:
                raise ValueError("not_an_organisation takes no other answer")
            return self
        if self.kind not in dict(Organisation.KIND_CHOICES):
            raise ValueError(f"{self.kind!r} is not an organisation kind")
        if self.country_code and not (
            len(self.country_code) == 2 and self.country_code.isascii()
            and self.country_code.isupper()
        ):
            raise ValueError("country_code is ISO 3166 alpha-2 or empty")
        if self.funds_students is None:
            # Plan "Corrections" 8: without it classified_at caches a non-answer.
            raise ValueError("say whether it funds students")
        return self


def _kind_ask(e: KindOrCountryEvidence) -> str:
    return _cap(f"What is {e.primary_domain[:200]}, where is it, and does it fund students?")


def _kind_form(form: Mapping[str, str]) -> dict[str, object]:
    data: dict[str, object] = {"option": form.get("option", "")}
    if data["option"] == "set":
        data["kind"] = form.get("kind", "")
        data["country_code"] = form.get("country_code", "").strip().upper()
        data["funds_students"] = {"yes": True, "no": False}.get(form.get("funds_students", ""))
    return data


# --- the registry -----------------------------------------------------------


@dataclass(frozen=True)
class KindSpec:
    kind: str
    subject_prefix: str
    evidence: type[BaseModel]
    resolution: type[BaseModel]
    options: tuple[str, ...]
    render_ask: Callable[[Any], str]
    example_evidence: Callable[[], BaseModel]
    #: The console's form, read into the shape `resolution` validates. Here and
    #: not in the view so a new kind is still one entry in this registry.
    from_form: Callable[[Mapping[str, str]], dict[str, object]]


KINDS: dict[str, KindSpec] = {
    "SITE_UNKNOWN": KindSpec(
        kind="SITE_UNKNOWN",
        subject_prefix=_RESOLUTION_PREFIXES["SITE_UNKNOWN"],
        evidence=SiteUnknownEvidence,
        resolution=SiteUnknownResolution,
        options=("pick", "paste", "not_a_funder", "does_not_exist"),
        render_ask=_site_ask,
        example_evidence=lambda: SiteUnknownEvidence(
            register="vgm_tr", external_key="1", names=["Örnek Vakfı"], country_code="TR",
            candidates=[],
        ),
        from_form=_option_and_url,
    ),
    "AWARD_DISPUTED": KindSpec(
        kind="AWARD_DISPUTED",
        subject_prefix=_RESOLUTION_PREFIXES["AWARD_DISPUTED"],
        evidence=AwardDisputedEvidence,
        resolution=AwardDisputedResolution,
        options=("accept", "not_an_award", "third_party"),
        render_ask=_award_ask,
        example_evidence=lambda: AwardDisputedEvidence(
            canonical_key="read:x", award_name="Example Scholarship",
            page_url="https://uni.test/funding", snapshot_sha256="0" * 64, quotes=["q"],
            disputed=[DisputedField(field="money_form", choices=["GRANT", "LOAN"])],
        ),
        from_form=_award_form,
    ),
    "HOST_UNREACHABLE": KindSpec(
        kind="HOST_UNREACHABLE",
        subject_prefix=_RESOLUTION_PREFIXES["HOST_UNREACHABLE"],
        evidence=HostUnreachableEvidence,
        resolution=HostUnreachableResolution,
        options=("paste", "closed"),
        render_ask=_host_ask,
        example_evidence=lambda: HostUnreachableEvidence(
            host="www.uni.test", url="https://www.uni.test/x", trail=[]
        ),
        from_form=_option_and_url,
    ),
    "KIND_OR_COUNTRY_UNSURE": KindSpec(
        kind="KIND_OR_COUNTRY_UNSURE",
        subject_prefix=_RESOLUTION_PREFIXES["KIND_OR_COUNTRY_UNSURE"],
        evidence=KindOrCountryEvidence,
        resolution=KindOrCountryResolution,
        options=("set", "not_an_organisation"),
        render_ask=_kind_ask,
        example_evidence=lambda: KindOrCountryEvidence(
            primary_domain="vakfi.org.tr", guess_kind="PRIVATE_FOUNDATION", confidence=0.5
        ),
        from_form=_kind_form,
    ),
}


def evidence_for(kind: str, data: Mapping[str, object]) -> BaseModel:
    return KINDS[kind].evidence.model_validate(data)


def resolution_for(kind: str, data: Mapping[str, object], *, evidence: BaseModel) -> BaseModel:
    """Raises pydantic.ValidationError on any answer the closed question does not admit."""
    return KINDS[kind].resolution.model_validate(data, context={"evidence": evidence})
