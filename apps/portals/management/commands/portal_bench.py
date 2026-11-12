"""Replay a portal form's recorded bench walk offline (spec §9).

    uv run python manage.py portal_bench <portal_form_id> --operator <email>
        [--walk-ok LOGIN|SIGNUP] [--promote --confirm DIGEST] [--new-walk]
        [--wording OUT.html]
    uv run python manage.py portal_bench --operator <email> --queue

Exit 1 when the report is not clean. The command never writes a rule: the
owner sets value_formats / option_synonyms / readback_equivalences (admin or
shell), or corrects the map, then re-runs.

A replay sees only what a static saved copy can show (selects, a box the
browser itself sanitises). A portal's own scripts never run here, so what it
does to a value -- uppercasing, reformatting a date -- is taught by hand from
the owner's live walk, not suggested by this command.
"""

from __future__ import annotations

import json
from argparse import ArgumentParser
from pathlib import Path
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.html import escape

from apps.funding.models import AuditEvent
from apps.portals import bench
from apps.portals.bench import PromotionRefused, mapping_digest, promote
from apps.portals.bench_runner import REPLAY_CSP, BenchReport, replay, suggest_rule
from apps.portals.models import FieldMap, PageRecord, PortalForm
from apps.portals.slots import parse_slots
from apps.research.resolution.platform import platform_agency
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency, Membership


def resolve_operator(email: str) -> Membership:
    """The named bench operator, read inside the platform tenant (Membership is
    FORCE RLS), exactly as funding_review resolves its operator."""
    try:
        platform = platform_agency()
    except Agency.DoesNotExist as error:
        raise CommandError(str(error)) from error
    with tenant_scope(platform.id), tenant_transaction(platform.id):
        operator = (
            Membership.objects.filter(
                tenant=platform, role=Membership.Role.PLATFORM_ADMIN,
                active=True, user__is_active=True, user__email__iexact=email,
            )
            .select_related("user")
            .first()
        )
        if operator is None or not bench.is_bench_operator(operator):
            raise CommandError(f"no bench operator with email {email} (PLATFORM_ADMIN + MFA)")
    return operator


def _inert(body: bytes) -> bytes:
    """A saved copy opened from disk has no server to send REPLAY_CSP, so
    it carries the policy itself, ahead of everything the page holds."""
    doctype = b"<!doctype html>"
    if body[: len(doctype)].lower() == doctype:
        body = body[len(doctype):]
    meta = f'<meta http-equiv="Content-Security-Policy" content="{REPLAY_CSP}">'
    return doctype + meta.encode() + body


def bench_map(form: PortalForm) -> FieldMap:
    """The shared (or verified) map, else the newest live tenant map: the bench
    verifies whichever map students are actually being served. A form that
    needs the bench again benches the relearn's map, not the stale verified row
    the portal changed under."""
    tenant_maps = FieldMap.objects.filter(
        portal_form=form, learned_by_tenant__isnull=False, superseded_at__isnull=True
    ).order_by("-version")
    current = tenant_maps.first() if form.needs_bench else None
    current = current or FieldMap.current_for(form, None) or tenant_maps.first()
    if current is None:
        raise CommandError("this form has no map yet: a student's first visit learns one")
    return current


def run_bench(form: PortalForm) -> tuple[BenchReport, FieldMap]:
    """Only the current walk: a superseded one describes a page that changed."""
    records = list(
        PageRecord.objects.filter(
            portal_form=form, source=PageRecord.Source.BENCH_WALK, superseded_at__isnull=True
        )
        .exclude(html_key="")
        .order_by("step")
    )
    if not records:
        raise CommandError("no recorded walk: walk it first (docs/runbooks/portal-bench.md)")
    field_map = bench_map(form)
    store = bench._store()
    pages: list[tuple[object, bytes]] = [(r, store.get(r.html_key)) for r in records]
    return replay(form, field_map, pages=pages), field_map


class Command(BaseCommand):
    help = (
        "Replay a portal form's recorded bench walk offline from synthetic students. "
        "Portal-side changes (uppercasing, reformatting) cannot replay from a saved "
        "copy; teach those by hand from the live walk."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("portal_form_id", nargs="?", type=UUID)
        parser.add_argument("--operator", required=True, help="the bench operator's email")
        # --walk-ok returns before any replay, so with --promote it would
        # silently skip the promotion.
        action = parser.add_mutually_exclusive_group()
        action.add_argument(
            "--walk-ok", choices=["LOGIN", "SIGNUP"],
            help="mark the newest recorded page of this kind as having worked in the live walk",
        )
        action.add_argument(
            "--promote", action="store_true",
            help="after a clean replay, make the map the verified one every tenant is served",
        )
        parser.add_argument(
            "--confirm", metavar="DIGEST", default="",
            help="with --promote: the mapping digest printed after you checked every row",
        )
        action.add_argument(
            "--new-walk", action="store_true",
            help="supersede this form's recorded walk so the next one starts fresh",
        )
        action.add_argument(
            "--wording", metavar="OUT_HTML",
            help="write the four-language wording sheet beside the recorded pages' saved copies",
        )
        action.add_argument(
            "--queue", action="store_true",
            help="list the forms still to walk: unverified ones students use, and changed ones",
        )

    def handle(self, *args: object, **options: object) -> None:
        operator = resolve_operator(str(options["operator"]))
        if options["queue"]:
            self._queue()
            return
        form = self._form(options["portal_form_id"])
        if options["wording"]:
            self._wording(form, Path(str(options["wording"])))
            return
        if options["new_walk"]:
            count = PageRecord.objects.filter(
                portal_form=form, source=PageRecord.Source.BENCH_WALK, superseded_at__isnull=True
            ).update(superseded_at=timezone.now())
            self.stdout.write(f"{count} recorded pages superseded: the next walk starts fresh")
            return
        if options["walk_ok"]:
            kind = str(options["walk_ok"])
            candidates = PageRecord.objects.filter(
                portal_form=form, source=PageRecord.Source.BENCH_WALK,
                page_kind=kind, superseded_at__isnull=True,
            )
            if kind == "SIGNUP":
                # promote reads the rules off the walked SIGNUP page, so the
                # attestation must land on a page that has them.
                record = (
                    candidates.exclude(password_rules="")  # nosec B106 -- rule text
                    .order_by("-created_at").first()
                )
                if record is None:
                    raise CommandError("no SIGNUP page with its password rules recorded")
            else:
                record = candidates.order_by("-created_at").first()
                if record is None:
                    raise CommandError(f"no recorded {kind} page for this form")
            # The human attestation the gate rests on: who vouched for which
            # page, committed with the flag (as store_bench_page does). Ids only.
            with tenant_scope(operator.tenant_id), tenant_transaction(operator.tenant_id):
                record.walk_ok = True
                record.save(update_fields=["walk_ok"])
                AuditEvent.objects.create(
                    tenant_id=operator.tenant_id,
                    actor=operator,
                    actor_kind=AuditEvent.ActorKind.HUMAN,
                    event="portal.bench_walk_ok",
                    object_id=record.id,
                )
            self.stdout.write(f"{kind} marked as worked in the live walk")
            return
        report, field_map = run_bench(form)
        self._print(report)
        digest = self._print_mapping(form, field_map)
        if not report.clean:
            raise CommandError("not clean: set the suggested rules or correct the map, re-run")
        if options["promote"]:
            if options["confirm"] != digest:
                raise CommandError(
                    "check every row above against the real portal, then re-run with "
                    f"--promote --confirm {digest}"
                )
            # Only ever after the replay just run: never a report from elsewhere.
            try:
                verified = promote(
                    form, field_map, report, operator=operator, confirmed=digest
                )
            except PromotionRefused as refused:
                raise CommandError(str(refused)) from refused
            self.stdout.write(f"verified: field map v{verified.version} now serves every tenant")

    def _wording(self, form: PortalForm, out: Path) -> None:
        """One table per recorded page, in walk order: every message in az, tr,
        ru and en, beside the page's own control labels, with a link to the
        page's saved copy written next to the sheet -- never the live portal.
        Message texts and control labels only: no student data exists here."""
        dist = Path(__file__).resolve().parents[4] / "extension" / "dist" / "i18n.json"
        if not dist.exists():
            raise CommandError("no extension/dist/i18n.json: npm --prefix extension run build")
        catalogue: dict[str, dict[str, str]] = json.loads(dist.read_text())
        out.parent.mkdir(parents=True, exist_ok=True)
        store = bench._store()
        parts = ["<!doctype html><meta charset='utf-8'><title>Wording</title>"]
        records = PageRecord.objects.filter(
            portal_form=form, source=PageRecord.Source.BENCH_WALK, superseded_at__isnull=True
        ).exclude(html_key="").order_by("step")
        for record in records:
            copy = f"page-{record.step}.html"
            (out.parent / copy).write_bytes(_inert(store.get(record.html_key)))
            snapshot = record.snapshot if isinstance(record.snapshot, dict) else {}
            controls = snapshot.get("controls", [])
            labels = ", ".join(escape(str(c.get("label", ""))) for c in controls)
            parts.append(
                f"<h2>{escape(record.page_kind)} &middot; step {record.step}</h2>"
                f"<p><a href='{copy}'>saved copy</a> &middot; labels on this page: {labels}</p>"
                "<table><tr><th>key</th><th>az</th><th>tr</th><th>ru</th><th>en</th></tr>"
            )
            for key in sorted(catalogue["en"]):
                cells = "".join(
                    f"<td>{escape(catalogue[lang][key])}</td>" for lang in ("az", "tr", "ru", "en")
                )
                parts.append(f"<tr><td>{escape(key)}</td>{cells}</tr>")
            parts.append("</table>")
        out.write_text("".join(parts), encoding="utf-8")
        self.stdout.write(f"wrote {out.resolve().as_uri()}")

    def _queue(self) -> None:
        """The owner's walk list: forms students already meet with no verified
        map, and forms whose portal changed under their verified map. The map
        version is the one `bench_map` would bench."""
        verified = FieldMap.objects.filter(
            verified_at__isnull=False, superseded_at__isnull=True
        ).values_list("portal_form_id", flat=True)
        live = PageRecord.objects.filter(source=PageRecord.Source.LIVE_LEARN)
        unverified = PortalForm.objects.filter(
            id__in=live.values_list("portal_form_id", flat=True)
        ).exclude(id__in=verified)
        rows = [(form, "changed") for form in PortalForm.objects.filter(needs_bench=True)] + [
            (form, "unverified") for form in unverified.exclude(needs_bench=True)
        ]
        for form, reason in sorted(rows, key=lambda row: row[0].portal_host):
            records = PageRecord.objects.filter(portal_form=form, superseded_at__isnull=True)
            try:
                version = f"v{bench_map(form).version}"
            except CommandError:
                version = "no map"
            self.stdout.write(
                f"{form.id}  {form.portal_host}  {reason}  "
                f"live={records.filter(source=PageRecord.Source.LIVE_LEARN).count()} "
                f"walked={records.filter(source=PageRecord.Source.BENCH_WALK).count()}  "
                f"bench={version}"
            )

    def _form(self, form_id: object) -> PortalForm:
        if not isinstance(form_id, UUID):
            raise CommandError("name a portal form id")
        form = PortalForm.objects.filter(id=form_id).first()
        if form is None:
            raise CommandError(f"no portal form {form_id}")
        return form

    def _print_mapping(self, form: PortalForm, field_map: FieldMap) -> str:
        """Every row as field -> box, beside the box's label on the operator's
        own walk: the one check read-back cannot make (a map that types the
        passport number into the referee's e-mail box reads back clean)."""
        source = (
            f"tenant {field_map.learned_by_tenant_id}" if field_map.learned_by_tenant_id
            else "shared"
        )
        self.stdout.write(f"map v{field_map.version} ({source}): does each box ask for this?")
        seen: dict[str, str] = {}
        records = PageRecord.objects.filter(
            portal_form=form, source=PageRecord.Source.BENCH_WALK, superseded_at__isnull=True
        )
        for record in records:
            snapshot = record.snapshot if isinstance(record.snapshot, dict) else {}
            for control in snapshot.get("controls", []):
                words = " / ".join(
                    str(control.get(key) or "") for key in ("heading", "label", "context")
                    if control.get(key)
                )
                seen.setdefault(str(control.get("selector", "")), words)
        for row in field_map.entries:
            action = row.get("action")
            selector = str(action.get("selector", "")) if isinstance(action, dict) else ""
            label = seen.get(selector, "not on any recorded page")
            self.stdout.write(f"  {row.get('profile_field')} -> {selector}  [{label}]")
        for slot in parse_slots(field_map.slots):
            label = seen.get(slot.selector, "not on any recorded page")
            degree = f" degree {slot.degree}" if slot.degree else ""
            self.stdout.write(
                f"  upload {slot.kind}/{slot.variant}{degree} -> {slot.selector}  [{label}]"
            )
        digest = mapping_digest(field_map)
        self.stdout.write(f"mapping digest: {digest}")
        return digest

    def _print(self, report: BenchReport) -> None:
        self.stdout.write(f"blocked requests to anywhere but the bench: {report.blocked_requests}")
        for name, run in report.per_student.items():
            self.stdout.write(
                f"{name}: {len(run.ambers)} amber, {len(run.refused)} refused, "
                f"{len(run.manual_documents)} manual documents, {run.open_choices} open choices "
                f"(the student's own), {len(run.untested)} not proved by this sample"
            )
            for amber in run.ambers:
                self.stdout.write(
                    f"  {amber['profile_field']}: {amber['expected']!r} -> {amber['actual']!r}"
                    f"  [{suggest_rule(amber['expected'], amber['actual'])}]"
                )
            for verdict in run.refused:
                self.stdout.write(f"  refused {verdict['profile_field']}: {verdict['reason']}")
            for filename in run.manual_documents:
                self.stdout.write(f"  attach by hand: {filename}")
        for row in report.refused_rows:
            self.stdout.write(f"map row refused: {row['profile_field']}: {row['reason']}")
        for guess in report.unsure:
            self.stdout.write(
                f"map row unsure: {guess['profile_field']} ({guess['selector']}): "
                "set sure or drop it"
            )
        for selector in report.untested_slots:
            self.stdout.write(
                f"upload box untested: {selector} (no sample's document went in on any page)"
            )
        for selector in report.left_to_student:
            self.stdout.write(f"upload box left to the student (OTHER): {selector}")
        if report.boxes == 0 or not report.per_student:
            self.stdout.write("nothing proved: the map has no boxes, or no sample ran")
        for profile_field in report.untested:
            self.stdout.write(
                f"untested by every sample: {profile_field} (no sample value, or its box is "
                "on no recorded page)"
            )
        self.stdout.write("CLEAN" if report.clean else "NOT CLEAN")
