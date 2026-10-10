from django.core.management.base import BaseCommand

from apps.portals.reporting import intervention_rates


class Command(BaseCommand):
    help = "Print the per-portal intervention rate (§5.4's 90/10/2 targets, measured)"

    def handle(self, *_args: object, **_options: object) -> None:
        self.stdout.write(f"{'portal':40} {'apps':>6} {'escal':>6} {'recov':>6} {'rate':>7}")
        for row in intervention_rates():
            self.stdout.write(
                f"{row.portal_host:40} {row.applications:6} {row.escalations:6} "
                f"{row.recoveries:6} {row.intervention_rate:7.2%}"
            )
