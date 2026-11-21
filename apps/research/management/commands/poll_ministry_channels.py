"""Poll public Telegram `/s/` channels and ministry scholarship bulletin pages."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.research.fetch import fetch_page
from apps.research.social_monitor import (
    all_53_ministry_channels,
    bump_cycle_checks_for_announcements,
    fetch_channel_bytes_cheap_first,
    poll_channels,
)


class Command(BaseCommand):
    help = (
        "Poll ministry Telegram /s/ channels and official scholarship bulletins for Master's calls."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--countries",
            default="",
            help="Optional comma-separated ISO2 country filter (default: all 57 countries).",
        )
        parser.add_argument(
            "--telegram-only",
            action="store_true",
            help="Poll only public Telegram /s/ web-preview channels.",
        )
        parser.add_argument(
            "--cheap-http-first",
            action="store_true",
            help="Try zero-credit direct HTTPS GET before falling back to vendor fetch.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        raw_countries = options.get("countries") or ""
        countries = [c.strip().upper() for c in raw_countries.split(",") if c.strip()] or None
        channels = all_53_ministry_channels(country_codes=countries)
        if options.get("telegram_only"):
            channels = tuple(ch for ch in channels if ch.channel_kind == "telegram_s")

        def _vendor_fetch(url: str) -> bytes:
            page = fetch_page(url, purpose="read", tag="social-monitor")
            return page.body or b""

        use_cheap = bool(options.get("cheap_http_first"))

        def _fetch(url: str) -> bytes:
            if use_cheap:
                return fetch_channel_bytes_cheap_first(url, _vendor_fetch)
            return _vendor_fetch(url)

        announcements = poll_channels(channels, _fetch, record_pointers=True)
        bumped = bump_cycle_checks_for_announcements(announcements)
        total_leads = sum(len(a.leads) for a in announcements)
        self.stdout.write(
            f"Polled {len(channels)} channels -> {len(announcements)} announcements, "
            f"{total_leads} official leads. ({bumped} cycle checks bumped)"
        )
