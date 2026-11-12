"""Fetch and store the Central Bank of Azerbaijan's official rates for today,
then the European Central Bank's daily rates, which `rates.latest_table` crosses
through EUR for the currencies CBAR does not publish.

Invoked daily by FetchCbarRatesRule (infra/template.yaml). The research worker
builds every pack from the newest stored day, and the board converts with it
(lanes spec §7.6). A data file, so our own transport (egress.fetch_data_file),
never a page vendor. A failure of either fetch raises and records no run: the
heartbeat then reports the job silent. A CBAR table stored before an ECB failure
stays stored.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.funding.rate_sources import parse_cbar_daily, parse_ecb_daily
from apps.funding.rates import BAKU, store
from apps.research.egress import fetch_data_file
from apps.watch.heartbeat import record_run, report_silent

_URL = "https://www.cbar.az/currencies/{day:%d.%m.%Y}.xml"
#: Always the latest ECB working day, so no date in the URL.
_ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


class Command(BaseCommand):
    help = "Fetch today's CBAR official rates and the ECB daily rates, and store them"

    def handle(self, *_args: object, **_options: object) -> None:
        today = timezone.localdate(timezone=BAKU)
        result = fetch_data_file(_URL.format(day=today), require_https=True)
        stored = store(parse_cbar_daily(result.body))
        stored += store(
            parse_ecb_daily(fetch_data_file(_ECB_URL, require_https=True).body)
        )
        record_run("fetch_cbar_rates")
        report_silent()
        self.stdout.write(f"stored {stored} CBAR and ECB rates for {today:%d %b %Y}")
