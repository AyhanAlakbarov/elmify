"""Measure how much a second search provider actually adds.

Two research runs ranked provider coverage across six languages without either of
them issuing a single query. This measures it instead. The number that decides
the design is the *marginal* recall of provider #2 over provider #1: if it is
small, the ensemble is complexity for nothing and one provider ships.

Search here is a recall-only component -- every URL is fetched and verified from
the origin afterwards, so a false positive costs one fetch and ranking quality is
worth nothing. Recall is therefore the only axis this measures.

    python scripts/search_recall.py --self-check          # no network, no keys
    python scripts/search_recall.py --verify-fixtures     # re-check targets are live
    TAVILY_API_KEY=... MOJEEK_API_KEY=... python scripts/search_recall.py

The provider adapters are UNEXERCISED until someone runs them with real keys --
they are written from each provider's documented request shape, not from a
successful call. The scoring logic below is what --self-check covers.
"""

import argparse
import json
import os
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import urllib3

SearchFn = Callable[[str, str, str], list[str]]
ProviderSpec = tuple[SearchFn, str]
HitKey = tuple[str, str, str]
Fixture = dict[str, Any]
Report = dict[str, Any]

FIXTURES = Path(__file__).with_name("search_recall_fixtures.json")
TIMEOUT = urllib3.Timeout(connect=10.0, read=25.0)
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign",
    "utm_term", "utm_content", "fbclid", "gclid",
}


def normalize_url(url: str) -> str:
    """Collapse the differences that are not differences.

    Providers return the same page with a trailing slash or without, with or
    without www, http or https, sometimes with a session id or a tracking tail.
    None of that changes whether we found the page.
    """
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().split("@")[-1]
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(":443") or host.endswith(":80"):
        host = host.rsplit(":", 1)[0]
    path = parts.path.rstrip("/") or "/"
    # jsessionid and friends ride in the path, not the query string
    if ";" in path:
        path = path.split(";", 1)[0].rstrip("/") or "/"
    # Drop tracking params and valueless ones (`?message=`). Neither distinguishes a
    # page, and the asymmetry favours dropping: a false negative silently understates
    # a provider's recall, while a false positive costs one wasted fetch.
    kept = sorted(
        pair
        for pair in parts.query.split("&")
        if "=" in pair
        and pair.split("=", 1)[1] != ""
        and pair.split("=", 1)[0].lower() not in TRACKING_PARAMS
    )
    query = "&".join(kept)
    return f"{host}{path}" + (f"?{query}" if query else "")


def is_hit(target: str, results: Iterable[str], *, prefix: bool = False) -> bool:
    """Exact match by default; prefix match counts a page we would crawl onward from.

    Finding uni.edu/funding/masters when the target is uni.edu/funding is a
    success for a discovery engine -- it reaches the target by crawling. That is
    a genuinely different measurement from exact match, so it is reported
    separately rather than folded in.
    """
    want = normalize_url(target)
    for result in results:
        got = normalize_url(result)
        if got == want:
            return True
        if prefix:
            # A root target normalizes to "host/", so the naive want + "/" builds
            # "host//" and nothing can ever match it. Compare on the slash-stripped
            # form so "host/" is a prefix of "host/anything".
            want_base = want.rstrip("/")
            got_base = got.rstrip("/")
            if got_base.startswith(want_base + "/") or want_base.startswith(got_base + "/"):
                return True
    return False


def _http() -> urllib3.PoolManager:
    return urllib3.PoolManager(timeout=TIMEOUT, retries=urllib3.Retry(2, backoff_factor=0.5))


def search_tavily(query: str, host: str, key: str) -> list[str]:
    """Tavily scopes by include_domains, not by a site: operator."""
    response = _http().request(
        "POST",
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        body=json.dumps({"query": query, "include_domains": [host], "max_results": 20}).encode(),
    )
    if response.status != 200:
        raise RuntimeError(f"tavily HTTP {response.status}")
    return [r["url"] for r in json.loads(response.data).get("results", []) if r.get("url")]


def search_mojeek(query: str, host: str, key: str) -> list[str]:
    """Mojeek scopes with its own site inclusion parameter."""
    response = _http().request(
        "GET",
        "https://www.mojeek.com/search",
        fields={"q": query, "si": host, "fmt": "json", "api_key": key, "t": "20"},
    )
    if response.status != 200:
        raise RuntimeError(f"mojeek HTTP {response.status}")
    payload = json.loads(response.data)
    return [r["url"] for r in payload.get("response", {}).get("results", []) if r.get("url")]


# Brave's free tier is 1 query/second. A shared clock is enough here -- the harness
# is single-threaded and issues a few dozen queries.
_BRAVE_LAST_CALL = 0.0
BRAVE_MIN_INTERVAL = 1.1


def search_brave(query: str, host: str, key: str) -> list[str]:
    """Brave takes a real site: operator in the query string."""
    global _BRAVE_LAST_CALL
    wait = BRAVE_MIN_INTERVAL - (time.monotonic() - _BRAVE_LAST_CALL)
    if wait > 0:
        time.sleep(wait)
    _BRAVE_LAST_CALL = time.monotonic()
    response = _http().request(
        "GET",
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        fields={"q": f"site:{host} {query}", "count": "20"},
    )
    if response.status != 200:
        raise RuntimeError(f"brave HTTP {response.status}")
    payload = json.loads(response.data)
    return [r["url"] for r in payload.get("web", {}).get("results", []) if r.get("url")]


def search_exa(query: str, host: str, key: str) -> list[str]:
    """Exa scopes with includeDomains and matches by meaning rather than keyword."""
    response = _http().request(
        "POST",
        "https://api.exa.ai/search",
        headers={"x-api-key": key, "Content-Type": "application/json"},
        body=json.dumps(
            {"query": query, "includeDomains": [host], "numResults": 20, "type": "auto"}
        ).encode(),
    )
    if response.status != 200:
        raise RuntimeError(f"exa HTTP {response.status}")
    return [r["url"] for r in json.loads(response.data).get("results", []) if r.get("url")]


def search_serpapi(query: str, host: str, key: str) -> list[str]:
    """SerpApi proxies Google, so host scoping is Google's own site: operator.

    Note this is a Google-derived index: it is here to test the claim that Google
    leads on non-English and university-subdomain coverage, not as a candidate.
    Its terms put use-side liability back on us (see the live-search synthesis).
    """
    response = _http().request(
        "GET",
        "https://serpapi.com/search.json",
        fields={"engine": "google", "q": f"site:{host} {query}", "num": "20", "api_key": key},
    )
    if response.status != 200:
        raise RuntimeError(f"serpapi HTTP {response.status}")
    payload = json.loads(response.data)
    return [r["link"] for r in payload.get("organic_results", []) if r.get("link")]


PROVIDERS: dict[str, ProviderSpec] = {
    "tavily": (search_tavily, "TAVILY_API_KEY"),
    "mojeek": (search_mojeek, "MOJEEK_API_KEY"),
    "brave": (search_brave, "BRAVE_API_KEY"),
    "exa": (search_exa, "EXA_API_KEY"),
    "serpapi": (search_serpapi, "SERPAPI_API_KEY"),
}


def measure(
    fixtures: list[Fixture], providers: dict[str, ProviderSpec], *, prefix: bool
) -> Report:
    """One row per (fixture, provider, query-language). Errors are recorded, not raised."""
    hits: dict[HitKey, bool] = {}
    errors: list[dict[str, str]] = []
    for fixture in fixtures:
        for lang_mode in ("en", "local"):
            query = fixture[f"query_{lang_mode}"]
            for name, (fn, env) in providers.items():
                try:
                    urls = fn(query, fixture["host"], os.environ[env])
                    hits[(fixture["id"], name, lang_mode)] = is_hit(
                        fixture["target_url"], urls, prefix=prefix
                    )
                except Exception as error:  # a provider failure is data, not a crash
                    hits[(fixture["id"], name, lang_mode)] = False
                    errors.append(
                        {"fixture": fixture["id"], "provider": name, "mode": lang_mode,
                         "error": f"{type(error).__name__}: {error}"}
                    )
    return {"hits": hits, "errors": errors}


def _recall(
    fixtures: list[Fixture],
    hits: dict[HitKey, bool],
    names: list[str],
    lang_mode: str,
    language: str | None = None,
) -> tuple[int, int]:
    """Union recall over `names`: a fixture counts if ANY named provider found it."""
    pool = [f for f in fixtures if language is None or f["language"] == language]
    found = sum(1 for f in pool if any(hits.get((f["id"], n, lang_mode)) for n in names))
    return found, len(pool)


def report(
    fixtures: list[Fixture], result: Report, providers: dict[str, ProviderSpec]
) -> Report:
    hits = result["hits"]
    names = list(providers)
    languages = sorted({f["language"] for f in fixtures})
    out: Report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "fixture_count": len(fixtures),
        "providers": names,
        "errors": result["errors"],
        # Per-fixture detail, because an aggregate cannot distinguish a provider that
        # missed the page from a fixture whose target is a site root the query never
        # asked for. Diagnosing that difference is most of the value of a first run.
        "per_fixture": {
            f["id"]: {
                "language": f["language"],
                "target_url": f["target_url"],
                **{
                    name: {m: hits.get((f["id"], name, m), False) for m in ("en", "local")}
                    for name in names
                },
            }
            for f in fixtures
        },
        "by_mode": {},
    }
    for lang_mode in ("en", "local"):
        block: Report = {"per_provider": {}, "per_language": {}}
        for name in names:
            found, total = _recall(fixtures, hits, [name], lang_mode)
            block["per_provider"][name] = {"found": found, "of": total}
        union_found, total = _recall(fixtures, hits, names, lang_mode)
        block["union"] = {"found": union_found, "of": total}
        if len(names) > 1:
            base = names[0]
            base_found, _ = _recall(fixtures, hits, [base], lang_mode)
            block["marginal_over_first"] = {
                "base": base,
                "base_found": base_found,
                "union_found": union_found,
                "added": union_found - base_found,
            }
        for language in languages:
            block["per_language"][language] = {
                name: dict(
                    zip(("found", "of"), _recall(fixtures, hits, [name], lang_mode, language))
                )
                for name in names
            }
        out["by_mode"][lang_mode] = block
    return out


def verify_fixtures(fixtures: list[Fixture]) -> int:
    """Re-fetch every target. A dead target silently deflates every provider's recall."""
    http = _http()
    stale = 0
    for fixture in fixtures:
        status: int | str
        try:
            status = http.request("GET", fixture["target_url"], redirect=True).status
        except Exception as error:
            status = type(error).__name__
        expected = fixture["verified"]
        ok = status == 200 or (expected == "bot_blocked" and status in (401, 403, 412, 429))
        if not ok:
            stale += 1
        mark = "ok  " if ok else "STALE"
        print(f"{mark} {status!s:>6}  {fixture['id']}  {fixture['target_url']}")
    print(f"\n{len(fixtures) - stale}/{len(fixtures)} fixtures still good")
    return 1 if stale else 0


def self_check() -> int:
    """The scoring logic, exercised without a network or a key."""
    assert normalize_url("https://WWW.Tum.de/en/x/") == "tum.de/en/x"
    assert normalize_url("http://tum.de/en/x") == "tum.de/en/x"
    session_url = "https://www.studyinkorea.go.kr/en/main.do;jsessionid=ABC?message="
    assert normalize_url(session_url) == "studyinkorea.go.kr/en/main.do"
    assert normalize_url("https://a.io/p?utm_source=x&b=2") == "a.io/p?b=2"
    assert normalize_url("https://a.io/") == "a.io/"
    assert normalize_url("https://a.io/p?message=&b=2") == "a.io/p?b=2"  # valueless param dropped

    assert is_hit("https://tum.de/a", ["https://www.tum.de/a/"])
    assert not is_hit("https://tum.de/a", ["https://tum.de/b"])
    assert not is_hit("https://tum.de/a", ["https://tum.de/a/b"])
    assert is_hit("https://tum.de/a", ["https://tum.de/a/b"], prefix=True)
    # a root target is a prefix of every page on its host -- the naive form built
    # "host//" and matched nothing, which silently understated prefix recall
    assert is_hit("https://metu.edu.tr/", ["https://www.metu.edu.tr/foo"], prefix=True)
    assert not is_hit("https://metu.edu.tr/", ["https://www.metu.edu.tr/foo"])
    assert not is_hit("https://tum.de/en/x", ["https://tum.de/en/xyz"], prefix=True)

    # marginal arithmetic: provider two adds only what provider one missed
    fixtures = [
        {"id": str(i), "language": "de", "query_en": "", "query_local": ""} for i in range(4)
    ]
    hits = {
        ("0", "p1", "en"): True,  ("0", "p2", "en"): True,   # both
        ("1", "p1", "en"): True,  ("1", "p2", "en"): False,  # p1 only
        ("2", "p1", "en"): False, ("2", "p2", "en"): True,   # p2 only -> the marginal one
        ("3", "p1", "en"): False, ("3", "p2", "en"): False,  # neither
    }
    assert _recall(fixtures, hits, ["p1"], "en") == (2, 4)
    assert _recall(fixtures, hits, ["p2"], "en") == (2, 4)
    assert _recall(fixtures, hits, ["p1", "p2"], "en") == (3, 4)  # union, not sum
    assert _recall(fixtures, hits, ["p1"], "en", "de") == (2, 4)
    assert _recall(fixtures, hits, ["p1"], "en", "ko") == (0, 0)  # empty pool, no ZeroDivision
    print("self-check passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument(
        "--providers", default="tavily,mojeek", help="comma-separated; first is the baseline"
    )
    parser.add_argument(
        "--prefix-match", action="store_true", help="count a page we would crawl onward from"
    )
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--verify-fixtures", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.self_check:
        return self_check()

    data = json.loads(args.fixtures.read_text(encoding="utf-8"))
    fixtures = data["fixtures"]
    if args.verify_fixtures:
        return verify_fixtures(fixtures)

    chosen: dict[str, ProviderSpec] = {}
    for name in args.providers.split(","):
        name = name.strip()
        if name not in PROVIDERS:
            parser.error(f"unknown provider {name!r}; have {sorted(PROVIDERS)}")
        if not os.environ.get(PROVIDERS[name][1]):
            parser.error(f"{PROVIDERS[name][1]} is not set")
        chosen[name] = PROVIDERS[name]

    out = report(fixtures, measure(fixtures, chosen, prefix=args.prefix_match), chosen)
    out["power_warning"] = data.get("power_warning")
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
