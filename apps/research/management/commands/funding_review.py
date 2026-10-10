"""The funding review queue, in a terminal: the resolution queue's AWARD_DISPUTED items.

    uv run python manage.py funding_review                          # list
    uv run python manage.py funding_review accept <item> --operator <email> \\
        [--field money_form=GRANT ...] [--note "why"]
    uv run python manage.py funding_review reject <item> --operator <email> \\
        --note "why" [--third-party]

Since plan 2026-09-25 Task 8 this reads the platform-only resolution queue,
not FundingOpportunity. The funding reader files every award its readings
could not serve alone as an AWARD_DISPUTED item, and this command and the
console at /platform/resolution/ are two views of the same items. A decision
here IS `operator.decide`: the same validation against the item's closed
question (accept answers every disputed field from its choices), the same
per-operator daily cap, the same AuditEvent under the platform agency. So the
terminal and the console cannot disagree.

Nothing here writes the catalogue. `manage.py apply_resolutions` applies the
decision -- `review_funding` is now its write-back, suspension guard and all
-- and until it runs the row stays unserved. A decision on a page that has
since changed, or on an award its page has since withdrawn, comes back OPEN
with the reason, and `list` shows it as "sent back".

`--operator` names the person, recorded as the AuditEvent's actor: an active
PLATFORM_ADMIN of the platform agency. The terminal has no MFA step of its
own; whoever can run it already holds a database credential. The catalogue is
shared by every tenant, so a decision here is every tenant's.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.funding.models import FundingOpportunity
from apps.research.models import ResolutionItem
from apps.research.resolution.kinds import AwardDisputedEvidence
from apps.research.resolution.operator import DecisionRefused, decide
from apps.research.resolution.platform import platform_agency
from apps.research.resolution.writers import award_why
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency, Membership

KIND = ResolutionItem.Kind.AWARD_DISPUTED
_LIVE = (ResolutionItem.State.OPEN, ResolutionItem.State.PARKED)

#: Kept under its old name: tests/funding/test_suspension_serve_guard.py holds
#: the suspension sentence to it.
_why = award_why


def _fields(pairs: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name.strip() or not value.strip():
            raise CommandError(f"--field takes name=value, not {pair!r}")
        fields[name.strip()] = value.strip()
    return fields


class Command(BaseCommand):
    help = "List the queue's disputed awards, or decide one as a platform operator"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "action", nargs="?", choices=("list", "accept", "reject"), default="list"
        )
        parser.add_argument("id", nargs="?", help="a resolution item id (see list)")
        parser.add_argument("--operator", default="", help="the deciding operator's email")
        parser.add_argument(
            "--field", action="append", default=[],
            help="accept: name=value for each disputed field",
        )
        parser.add_argument("--note", default="")
        parser.add_argument(
            "--third-party", action="store_true",
            help="reject: the money is a third party's, not this page's award",
        )

    def handle(self, *_args: object, **options: Any) -> None:
        try:
            platform = platform_agency()
        except Agency.DoesNotExist as error:
            raise CommandError(str(error)) from error
        action = str(options["action"])
        if action == "list":
            self._list(platform)
            return
        item_id = options["id"]
        if not item_id:
            raise CommandError(f"{action} needs an item id (see funding_review list)")
        note = str(options["note"])
        if action == "reject" and not note:
            raise CommandError("reject needs --note saying why")
        email = str(options["operator"]).strip()
        if not email:
            raise CommandError(f"{action} needs --operator <email>: a decision names its person")
        if action == "accept":
            data: dict[str, object] = {
                "option": "accept", "fields": _fields(list(options["field"])), "note": note,
            }
        else:
            option = "third_party" if options["third_party"] else "not_an_award"
            data = {"option": option, "fields": {}, "note": note}
        item = self._decide(platform, str(item_id), email, data)
        self.stdout.write(
            f"{item.id} DECIDED ({data['option']}); "
            "it reaches the catalogue on the next manage.py apply_resolutions"
        )

    def _decide(
        self, platform: Agency, item_id: str, email: str, data: dict[str, object]
    ) -> ResolutionItem:
        missing = CommandError(f"no live AWARD_DISPUTED item {item_id} (see funding_review list)")
        try:
            item_uuid = UUID(item_id)
        except ValueError as error:
            raise missing from error
        with tenant_scope(platform.id), tenant_transaction(platform.id):
            operator = (
                Membership.objects.filter(
                    tenant=platform, role=Membership.Role.PLATFORM_ADMIN, active=True,
                    user__is_active=True, user__email__iexact=email,
                )
                .select_related("user")
                .first()
            )
            if operator is None:
                raise CommandError(f"no active platform operator with email {email}")
            if not ResolutionItem.objects.filter(
                id=item_uuid, kind=KIND, state__in=_LIVE
            ).exists():
                raise missing
            try:
                return decide(item_uuid, operator, data, now=timezone.now())
            except ResolutionItem.DoesNotExist as error:
                raise missing from error
            except DecisionRefused as error:
                raise CommandError(str(error)) from error

    def _list(self, platform: Agency) -> None:
        with tenant_transaction(platform.id):
            items = list(
                ResolutionItem.objects.filter(kind=KIND, state__in=_LIVE).order_by("created_at")
            )
            evidence = {item.id: AwardDisputedEvidence.model_validate(item.evidence)
                        for item in items}
            rows = FundingOpportunity.objects.in_bulk(
                [e.canonical_key for e in evidence.values()], field_name="canonical_key"
            )
        for item in items:
            found = evidence[item.id]
            row = rows.get(found.canonical_key)
            self.stdout.write(f"{item.id}  {item.state}  {item.subject_key}")
            self.stdout.write(f"  ask: {item.ask}")
            # The row as it stands now, when the catalogue still holds it: a
            # suspension found after filing must be the first thing read.
            self.stdout.write(f"  why: {award_why(row) if row else found.why}")
            if item.apply_error:
                self.stdout.write(f"  sent back: {item.apply_error}")
            if row is not None:
                self.stdout.write(
                    f"  {row.agreement}  {row.kind}/{row.scope_type}  "
                    f"disputed: {row.disputed or 'none'}\n"
                    f"  internationals={row.internationals_included} "
                    f"nationality={row.nationality_shape} route={row.route} "
                    f"money={row.money_form} obligation={row.obligation or 'none'}"
                )
            for disputed in found.disputed:
                self.stdout.write(f"  {disputed.field}: {' | '.join(disputed.choices)}")
            for quote in found.quotes:
                self.stdout.write(f'  "{quote}"')
            self.stdout.write(f"  page: {found.page_url}")
        self.stdout.write(f"{len(items)} pending")
