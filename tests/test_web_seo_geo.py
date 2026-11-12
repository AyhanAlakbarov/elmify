"""SEO, GEO, trilingual (EN/AZ/RU), Azerbaijan launch, and anti-prompt-injection tests."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from apps.accounts.consultation import QUESTION_LABELS
from apps.accounts.forms import _OPTION_CHOICES
from apps.accounts.question_widgets import CHOICE_LABELS

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

# Verbatim LLM prompt-injection & invisible-character patterns from audited
# Auriti-Labs/geo-optimizer-skill v4.19.9 (commit 7ecec864690ee430e954a95352130cf47e2c92cc).
PROMPT_INJECTION_LLM_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?",
        r"you\s+are\s+(?:now\s+)?(?:a|an)\s+(?:helpful\s+)?assistant",
        r"always\s+recommend\s+\w+",
        r"do\s+not\s+mention\s+competitors?",
        r"say\s+(?:only|just|that)\s+['\"]",
        r"output\s+only\s+the\s+following",
        r"respond\s+with\s+only",
        r"your\s+(?:new\s+)?(?:task|goal|objective|purpose)\s+is",
        r"from\s+now\s+on\s+you",
        r"\[INST\]|\[SYS\]|<\|system\|>|<\|user\|>",
        r"###\s*(?:System|Human|Assistant)\s*:",
        r"<\s*system\s*>",
        r"<\|start_header_id\|>|<\|end_header_id\|>|<\|eot_id\|>|<\|begin_of_text\|>",
        r"<start_of_turn>|<end_of_turn>",
        r"\bDAN\s+mode\b|\bdeveloper\s+mode\b",
        r"pretend\s+(?:you\s+have\s+no|there\s+are\s+no)\s+restrictions?",
        r"(?:reveal|repeat|show|tell)\s+(?:me\s+)?(?:your|the)\s+(?:system\s+)?(?:prompt|instructions?)",
        r"\bjailbreak\b",
        r"repeat\s+the\s+above",
    )
]

INVISIBLE_UNICODE_CHARS = frozenset(
    "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff"
    "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)

SUSPICIOUS_DATA_ATTR_RE = re.compile(
    r"\bdata-(?:ai|llm|gpt|claude|prompt|instruction|system|ignore)\b",
    re.IGNORECASE,
)

SUSPICIOUS_COMMENT_RE = re.compile(
    r"<!--[^>]*(?:prompt:|instruction:|system:|ai:|llm:|ignore\s+previous)[^>]*-->",
    re.IGNORECASE,
)


def _assert_clean_of_prompt_injection(text: str, source_label: str) -> None:
    for pattern in PROMPT_INJECTION_LLM_PATTERNS:
        match = pattern.search(text)
        assert match is None, (
            f"Prompt injection pattern {pattern.pattern!r} found in {source_label}: "
            f"{match.group(0)!r}"
        )
    invisible_found = [ch for ch in text if ch in INVISIBLE_UNICODE_CHARS]
    assert not invisible_found, (
        f"Invisible Unicode characters found in {source_label}: {invisible_found!r}"
    )
    assert SUSPICIOUS_DATA_ATTR_RE.search(text) is None, (
        f"Suspicious data-ai/prompt attribute in {source_label}"
    )
    assert SUSPICIOUS_COMMENT_RE.search(text) is None, f"Suspicious HTML comment in {source_label}"


def test_masters_only_career_goal_labels() -> None:
    """Platform covers Master's today; PHD code is labelled as post-master's academic research."""
    assert "PhD" not in QUESTION_LABELS["career_intent"]
    assert "academic research" in QUESTION_LABELS["career_intent"].lower()

    widget_labels = CHOICE_LABELS["career_intent"]
    assert "PhD" not in widget_labels["PHD"]
    assert "academic research" in widget_labels["PHD"].lower()

    form_choices = dict(_OPTION_CHOICES["career_intent"])
    assert "PhD" not in form_choices["PHD"]
    assert "academic research" in form_choices["PHD"].lower()


def test_web_llms_txt_and_llms_full_txt() -> None:
    """llms.txt and llms-full.txt follow llmstxt.org and geo-optimizer-skill v2 rules."""
    llms_txt = (WEB_DIR / "public" / "llms.txt").read_text(encoding="utf-8")
    llms_full = (WEB_DIR / "public" / "llms-full.txt").read_text(encoding="utf-8")

    for label, content in (("llms.txt", llms_txt), ("llms-full.txt", llms_full)):
        assert content.startswith("# Elmify"), f"{label} must start with H1 '# Elmify'"
        assert "\n> " in content, f"{label} must include a summary blockquote"
        links = re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", content)
        assert len(links) >= 6, f"{label} must contain Markdown links"
        assert "MSc" in content and "MA" in content and "LLM" in content and "MRes" in content
        assert "Azerbaijan" in content
        assert "dp.edu.gov.az" in content and "htp.edu.az" in content
        assert "https://elmify.com/az" in content and "https://elmify.com/ru" in content
        assert "will be done soon" in content
        assert "PhD" in content
        _assert_clean_of_prompt_injection(content, label)

    assert "## Optional" in llms_txt
    assert "llms-full.txt" in llms_txt
    assert len(llms_full.split()) >= 500


def test_web_ai_discovery_and_rss_endpoints() -> None:
    """geo-checklist.dev AI discovery files and RSS feed are valid and clean."""
    ai_txt = (WEB_DIR / "public" / ".well-known" / "ai.txt").read_text(encoding="utf-8")
    assert "Name: Elmify" in ai_txt
    assert "Primary-Launch-Market: Azerbaijan (AZ)" in ai_txt
    assert "will be done soon" in ai_txt
    assert "LLMs-Full-Txt: https://elmify.com/llms-full.txt" in ai_txt
    _assert_clean_of_prompt_injection(ai_txt, ".well-known/ai.txt")

    summary = json.loads((WEB_DIR / "public" / "ai" / "summary.json").read_text(encoding="utf-8"))
    assert summary["name"] == "Elmify"
    assert summary["primaryLaunchMarket"] == "Azerbaijan"
    assert summary["availableLanguages"] == ["en", "az", "ru"]
    assert len(summary["description"]) >= 50
    assert "will be done soon" in summary["degreeScope"]

    faq_data = json.loads((WEB_DIR / "public" / "ai" / "faq.json").read_text(encoding="utf-8"))
    assert faq_data["availableLanguages"] == ["en", "az", "ru"]
    assert len(faq_data["faqs"]) >= 5
    for item in faq_data["faqs"]:
        assert len(item["question"]) >= 10
        assert len(item["answer"]) >= 20

    service = json.loads((WEB_DIR / "public" / "ai" / "service.json").read_text(encoding="utf-8"))
    assert service["name"] == "Elmify"
    assert service["primaryLaunchMarket"] == "Azerbaijan"
    assert service["degreeScope"]["bachelors"] == "Will be done soon"
    assert isinstance(service["capabilities"], list) and len(service["capabilities"]) >= 4

    feed_xml = (WEB_DIR / "public" / "feed.xml").read_text(encoding="utf-8")
    root = ET.fromstring(feed_xml)
    assert root.tag == "rss"
    items = root.findall("./channel/item")
    assert len(items) >= 2
    _assert_clean_of_prompt_injection(feed_xml, "feed.xml")


def test_web_trilingual_copy_schema_and_prompt_injection_cleanliness() -> None:
    """All web/ source files declare EN/AZ/RU copy, Azerbaijan scholarships, and zero injection."""
    robots_ts = (WEB_DIR / "app" / "robots.ts").read_text(encoding="utf-8")
    for bot in (
        "OAI-SearchBot",
        "ChatGPT-User",
        "GPTBot",
        "Claude-SearchBot",
        "PerplexityBot",
        "Googlebot",
        "YandexBot",
        "Applebot",
    ):
        assert bot in robots_ts, f"{bot} must be explicitly allowed in robots.ts"
    assert '"/az"' in robots_ts and '"/ru"' in robots_ts
    assert "/llms-full.txt" in robots_ts
    assert "/.well-known/ai.txt" in robots_ts

    sitemap_ts = (WEB_DIR / "app" / "sitemap.ts").read_text(encoding="utf-8")
    assert "/az" in sitemap_ts and "/ru" in sitemap_ts

    landing_tsx = (WEB_DIR / "app" / "_components" / "landing-page.tsx").read_text(
        encoding="utf-8"
    )
    for schema_type in ("Organization", "WebSite", "SoftwareApplication", "TechArticle", "FAQPage"):
        assert f'"@type": "{schema_type}"' in landing_tsx
    assert '"Azerbaijan"' in landing_tsx

    i18n_ts = (WEB_DIR / "app" / "_components" / "i18n.ts").read_text(encoding="utf-8")
    assert "https://dp.edu.gov.az/" in i18n_ts
    assert "https://htp.edu.az/" in i18n_ts
    assert "Bachelor's degree support will be done soon" in i18n_ts
    assert "bakalavr proqramları üzrə dəstək isə tezliklə əlavə olunacaq" in i18n_ts
    assert "поддержка бакалавриата будет добавлена совсем скоро" in i18n_ts
    for hidden_marker in (
        "Automatic-on-admission & faculty tuition waivers",
        "Regional & household-income right-to-study grants",
        "Multi-country bloc & development-bank scholarships",
        "Non-English private, civic & charitable foundations",
        "RA/TA",
        "extensionPreview",
        "studentDemo",
        "agencyDemo",
    ):
        assert hidden_marker in i18n_ts, f"{hidden_marker} must be present in i18n.ts"

    for rel_path in (
        "app/layout.tsx",
        "app/page.tsx",
        "app/[locale]/page.tsx",
        "app/_components/i18n.ts",
        "app/_components/landing-page.tsx",
        "app/_components/hero.tsx",
        "app/_components/sections.tsx",
        "app/_components/nav.tsx",
        "public/llms.txt",
        "public/llms-full.txt",
        "public/.well-known/ai.txt",
        "public/ai/summary.json",
        "public/ai/faq.json",
        "public/ai/service.json",
    ):
        text = (WEB_DIR / rel_path).read_text(encoding="utf-8")
        _assert_clean_of_prompt_injection(text, f"web/{rel_path}")


@pytest.mark.django_db
def test_public_django_pages_meta_description_and_injection_clean(client, domain_a) -> None:
    """Public Django entry points linked from web/ include meta descriptions and zero injections."""
    from apps.privacy import documents

    for lang in ("en", "az", "ru"):
        for kind in documents.KINDS:
            documents.publish(kind, lang, f"{kind} ({lang}) v1", material=True)

    for path, expected_title in (
        ("/signup/", "Sign up — Elmify"),
        ("/signup/?lang=az", "Sign up — Elmify"),
        ("/signup/?lang=ru", "Sign up — Elmify"),
        ("/accounts/login/", "Log in — Elmify"),
        ("/demo/", "Book a demo — Elmify"),
        ("/demo/?audience=student", "Book a demo — Elmify"),
        ("/demo/?audience=agency", "Book a demo — Elmify"),
        ("/legal/terms/", "Terms of Service"),
        ("/legal/privacy_notice_direct/", "Privacy Notice"),
    ):
        resp = client.get(path, HTTP_HOST=domain_a.host)
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert f"<title>{expected_title}</title>" in html
        assert '<meta name="description" content="' in html
        assert "master" in html.lower()
        _assert_clean_of_prompt_injection(html, f"Django {path}")
