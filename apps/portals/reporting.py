"""Which portals cost a human, per portal, across every tenant.

Applications are tenant-scoped and RLS keeps them that way, so the count is
gathered by looping tenants under tenant_scope rather than by one unscoped
query -- the same shape as apps/research/dispatch.py. PortalForm and
RecoveryEvent are platform-scoped and are read once, outside the loop.
"""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency

from .models import Application, ApplicationStep, PortalForm, RecoveryEvent


@dataclass(frozen=True)
class PortalIntervention:
    portal_host: str
    applications: int
    escalations: int
    recoveries: int

    @property
    def intervention_rate(self) -> float:
        """Escalations per application. Recoveries are excluded deliberately:
        §5.4's target is about work reaching a human, and a recovery is the
        system not needing one."""
        return round(self.escalations / self.applications, 4) if self.applications else 0.0


def intervention_rates() -> list[PortalIntervention]:
    """Call this outside any tenant scope.

    tenant_scope refuses to *switch* an active scope (TenantContextConflict),
    so a caller already inside one tenant would raise on the second. The
    management command runs unscoped; a per-tenant dashboard view wants a
    single-tenant query rather than this function.
    """
    hosts = {
        form.id: form.portal_host for form in PortalForm.objects.only("id", "portal_host")
    }
    applications: dict[str, int] = {host: 0 for host in hosts.values()}
    escalations: dict[str, int] = {host: 0 for host in hosts.values()}

    # .get(), not hosts[...]: `hosts` is a snapshot, and a PortalForm created
    # between it and any loop below would otherwise raise KeyError mid-report.
    # Skipping is right -- that form has no counted history in this snapshot,
    # and the next run picks it up.
    for tenant_id in Agency.objects.values_list("id", flat=True):
        with transaction.atomic(), tenant_scope(tenant_id):
            set_local_tenant(tenant_id)
            for row in Application.objects.values("portal_form_id").annotate(n=Count("id")):
                host = hosts.get(row["portal_form_id"])
                if host is not None:
                    applications[host] += row["n"]
            # Its own name, not `row` again: django-stubs 6.1 infers a precise
            # TypedDict per .values() call, and this one's key differs from the
            # loop above -- reusing the name binds it to that TypedDict and the
            # second assignment stops type-checking.
            for escalation_row in (
                ApplicationStep.objects.filter(kind="ESCALATION")
                .values("application__portal_form_id")
                .annotate(n=Count("id", distinct=True))
            ):
                host = hosts.get(escalation_row["application__portal_form_id"])
                if host is not None:
                    escalations[host] += escalation_row["n"]

    recoveries: dict[str, int] = {host: 0 for host in hosts.values()}
    for row in RecoveryEvent.objects.values("portal_form_id").annotate(n=Count("id")):
        host = hosts.get(row["portal_form_id"])
        if host is not None:
            recoveries[host] += row["n"]

    return [
        PortalIntervention(
            portal_host=host,
            applications=applications[host],
            escalations=escalations[host],
            recoveries=recoveries[host],
        )
        for host in sorted(applications)
    ]
