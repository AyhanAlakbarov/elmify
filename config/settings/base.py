import json
import os
from decimal import Decimal
from pathlib import Path

from .database import database_config

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "development-only")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [
    value for value in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost").split(",") if value
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "apps.tenancy",
    "apps.research",
    "apps.accounts",
    "apps.funding",
    "apps.documents",
    "apps.reports",
    "apps.concierge",
    "apps.audit",
    "apps.portals",
    "apps.mailbox",
    "apps.watch",
    "apps.dashboard",
    "apps.privacy",
    "apps.leads",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.tenancy.middleware.content_security_policy",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.tenancy.middleware.HostTenantContextMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "apps.tenancy.middleware.TenantMembershipMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
LOGIN_URL = "accounts-login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "accounts-login"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.tenancy.context_processors.brand_colors",
                "apps.tenancy.context_processors.viewer_role",
                "apps.tenancy.context_processors.app_shell",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = database_config(os.environ, require_explicit_role=False)

#: A real Redis/Valkey URL in production (config/settings/production.py requires
#: it -- a shared counter is a production requirement, see apps/ratelimit.py).
#: Empty here so a developer machine or the test suite, with no cache server
#: running, falls back to LocMemCache below rather than failing to import.
#: DatabaseCache (Django's SQL-backed cache) was tried and rejected on review:
#: its incr() is a non-atomic get-then-set that resets the key's expiry to
#: Django's 300s default, so a rate limit's window stops holding the moment two
#: increments race or the key sits idle a few minutes -- RedisCache's INCR is
#: atomic and does not touch the TTL. ElastiCache Serverless was tried after
#: that and rejected too: it speaks only the cluster protocol, and Django's
#: RedisCache uses the plain non-cluster client -- production points this at a
#: node-based replication group, cluster mode disabled (infra/template.yaml).
CACHE_URL = os.getenv("CACHE_URL", "")
#: apps/ratelimit.py fails closed on a cache error -- a socket timeout this
#: short is what makes that fast rather than hanging a request until gunicorn's
#: own timeout notices Valkey is unreachable (AWS recommends at least 1s for
#: ElastiCache clients).
CACHE_SOCKET_TIMEOUT_SECONDS = 1.0
CACHES = {
    "default": (
        {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
            "OPTIONS": {
                "socket_connect_timeout": CACHE_SOCKET_TIMEOUT_SECONDS,
                "socket_timeout": CACHE_SOCKET_TIMEOUT_SECONDS,
            },
        }
        if CACHE_URL
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

#: Session and CSRF cookie lifetime and browser flags (AUTH-VULN-03 / AUTH-VULN-05).
#: 8-hour session lifetime with sliding renewal and browser-close expiry; Lax SameSite
#: so top-level OAuth redirects (/mailbox/callback/<provider>/) keep the session cookie.
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
RESEARCH_QUEUE_URL = os.getenv("RESEARCH_QUEUE_URL", "test-research-queue")

#: Early access: a student who signs up gets this academic year's cycle free,
#: so the search starts without a checkout (none exists yet; R13 uses
#: `manage.py mark_cycle_paid`). On by default only on a DEBUG machine; a
#: deployed site turns it on deliberately with EARLY_ACCESS_FREE_CYCLE=1.
EARLY_ACCESS_FREE_CYCLE = os.getenv("EARLY_ACCESS_FREE_CYCLE", "1" if DEBUG else "0") == "1"
EUROPASS_QUEUE_URL = os.getenv("EUROPASS_QUEUE_URL", "test-europass-queue")
DOCUMENT_QUEUE_URL = os.getenv("DOCUMENT_QUEUE_URL", "test-document-queue")
DOCUMENT_SCAN_QUEUE_URL = os.getenv("DOCUMENT_SCAN_QUEUE_URL", "test-document-scan-queue")
#: Where transcript OCR runs (apps/documents/ocr.py). Set in production: the Lambda function the
#: document worker invokes. Empty: a child process of this interpreter, run by OCR_PYTHON
#: (`uv sync --project ocr`'s ocr/.venv/bin/python).
OCR_FUNCTION_NAME = os.getenv("OCR_FUNCTION_NAME", "")
OCR_PYTHON = os.getenv("OCR_PYTHON", str(BASE_DIR / "ocr" / ".venv" / "bin" / "python"))
#: Azure Document Intelligence, the transcript reader for scanned pages and photos (spec
#: 2026-10-03-transcript-reader-redesign §4). The key only from the environment; the endpoint is
#: the EU resource's https URL. The API version is pinned: a newer one is adopted only after the
#: eval harness is re-run on it. Each OcrPage carries the version in memory; persisting it
#: with the reading is owed to the audit plan.
AZURE_DI_ENDPOINT = os.getenv("AZURE_DI_ENDPOINT", "")
AZURE_DI_KEY = os.getenv("AZURE_DI_KEY", "")
AZURE_DI_API_VERSION = "2024-11-30"
#: Launch gate (spec §4): no transcript reaches Azure until Microsoft's data-processing terms are
#: reviewed and this is set to 1. Checked in apps/documents/transcript.py before the upload opens.
TRANSCRIPT_AZURE_ENABLED = os.getenv("TRANSCRIPT_AZURE_ENABLED", "") == "1"
#: A course row's credit or grade cell below this Azure confidence is asked about on the summary
#: screen (spec §6.3). Starting value: below 0.8 flagged 71-100% of Azure's wrong lines in the
#: eval harness; spec §9 gate 5 tunes it on real transcripts.
TRANSCRIPT_LOW_CONFIDENCE_BELOW = 0.8
#: Spec 2026-10-03 §7.1: pages one paid academic-year cycle may have read, retakes included.
TRANSCRIPT_PAGES_PER_CYCLE = 50
#: Spec R3: retakes of one page before the student is asked to type its flagged cells instead.
TRANSCRIPT_MAX_RETAKES = 2
#: Spec §7.1: Azure pages one tenant may have read in a UTC day; past it, readings wait (DELAYED)
#: rather than bill without bound. The value is open (spec §11) -- 2,000 pages is about $20.
#: Counts both readers' Azure pages: transcripts and document fact reading.
TRANSCRIPT_TENANT_DAILY_AZURE_PAGES = int(
    os.environ.get("TRANSCRIPT_TENANT_DAILY_AZURE_PAGES", "2000")
)
#: Spec §7.1: an upload still READING (or scanned clean and never picked up) this long after its
#: last write was lost with a killed worker; the resume sweep takes it up again.
TRANSCRIPT_STUCK_AFTER_MINUTES = 30
#: Spec 2026-10-12: read a passport, ID card, diploma or certificate into facts.
#: Off until the launch gates in spec §9 are met; Azure also needs
#: TRANSCRIPT_AZURE_ENABLED, which now gates both readers.
FACT_READING_ENABLED = os.getenv("FACT_READING_ENABLED", "") == "1"
#: Pages sent to Azure per document, from the first: billing stops here.
FACT_READING_PAGE_CAPS = {"PASSPORT": 4, "DIPLOMA": 4, "LANGUAGE_CERTIFICATE": 2}
#: A value Azure reads with no strip to check it is proven only at or above this,
#: for the field and for every word in it (spec §5.2.3).
FACT_READING_CONFIDENCE = 0.95
#: Readings per student per hour; our own re-reads never count.
FACT_READING_HOURLY = 20
#: Two OpenRouter model ids from two vendors that read a diploma or certificate
#: (spec 2026-10-12 §5.3.3): the pair the catalogue reader measured (owner
#: decision 2026-10-12). "[]" turns diploma and certificate reading off.
# ponytail: one OpenRouter route per model; pin a single DeepSeek provider
# (OpenRouter provider routing) if answers drift between hosts.
FACT_READING_READERS: list[str] = json.loads(
    os.getenv("FACT_READING_READERS",
              '["deepseek/deepseek-v4.1-flash", "openai/gpt-6-luna"]')
)
FACT_READING_READER_MAX_TOKENS = 600
#: Pinned OpenRouter hosts per reader model (as measured in engine_eval/chat.py);
#: a model absent here is routed by OpenRouter.
FACT_READING_READER_HOSTS: dict[str, list[str]] = {"deepseek/deepseek-v4.1-flash": ["fireworks"]}
#: Reader calls per agency per day: the per-tenant cost breaker CLAUDE.md requires of
#: every LLM-calling path. Four calls at most per document (two readers, one retry each).
FACT_READING_TENANT_DAILY_CALLS = 2000
#: CV evidence spec §10.1: place supported GitHub and thesis/report bullets onto
#: generated CVs once the §14 accuracy gate is met.
CV_REPO_BULLETS_ENABLED = os.getenv("CV_REPO_BULLETS_ENABLED", "") == "1"
EVIDENCE_BUCKET_NAME = os.getenv("EVIDENCE_BUCKET_NAME", "test-evidence-bucket")
OPENAI_EXTRACTION_MODEL = os.getenv("OPENAI_EXTRACTION_MODEL", "gpt-5.6-luna")
OPENAI_EXPLANATION_MODEL = os.getenv("OPENAI_EXPLANATION_MODEL", "gpt-5.6-terra")
OPENAI_ESCALATION_MODEL = os.getenv("OPENAI_ESCALATION_MODEL", "gpt-5.6-sol")
OPENAI_MODEL_SCHEMA_VERSION = 2
#: One of the three CV-format judge readings (apps/documents/derive.py::_judge).
#: A different model family from OPENAI_EXTRACTION_MODEL on purpose: three
#: readings of one model share its systematic bias. The key is read by the SDK
#: from ANTHROPIC_API_KEY at use time, never a setting.
ANTHROPIC_JUDGE_MODEL = os.getenv("ANTHROPIC_JUDGE_MODEL", "claude-sonnet-5")
#: Whether a STUDENT'S OWN TEXT may be sent to that second family as well.
#: `apps/documents/letter_verification.py::check_written_requirements` sends
#: the finished letter -- the applicant's name and address in the header block,
#: and their own biography. OpenAI is already a processor for that data class
#: because generation sends it there; Anthropic was not.
#:
#: **ON by default since the owner's decision of 2026-09-24**, which was the
#: one thing this gate was waiting for: a written basis. Two conditions travel
#: with it and neither is enforced by code, so they are written here.
#: (1) The use agreement naming the second vendor is to be published -- the
#: agency DPAs (`docs/runbooks/shadow-pilot.md`) still do not name one, and
#: this default is ahead of that paperwork, not behind it.
#: (2) `ANTHROPIC_API_KEY` does not reach the worker task definition. Until it
#: does, the Claude reading is simply lost and the judge logs "judged by one
#: model family" -- the gate is on and the second opinion is not there, which
#: looks identical to working. Deploy the key or the decision buys nothing.
#: Why a second family at all, rather than a third reading of the same model:
#: three samples of one model share its bias (measured for the CV-format judge,
#: owner decision 2026-09-14).
LETTER_JUDGE_SECOND_FAMILY = os.getenv("LETTER_JUDGE_SECOND_FAMILY", "1") == "1"
#: Kept: `manage.py discover` and `pool_cv_corpus` read it, and it holds the
#: Tavily key today. The per-provider names below are what the roster needs
#: (roster §4.13) -- one generic name cannot carry four keys with four
#: different auth headers (Exa `x-api-key`, Brave `X-Subscription-Token`,
#: Tavily bearer).
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
#: Falls back to SEARCH_API_KEY, which is where the Tavily key lives today.
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "") or SEARCH_API_KEY
#: Exa: the research-fit site search (2026-09-22 design, D3). Written
#: permission on file (roster §8); queries are profile-free by construction
#: (anchors.guard_phrase) because Exa ToS 1.2(c) licenses query text.
EXA_API_KEY = os.getenv("EXA_API_KEY", "")
#: OpenAlex API key (mandatory since 2026-02-13; 2026-10-14-professor-and-paper-discovery.md
#: §1). No key, no request: the unauthenticated path is gone. Sent only to
#: api.openalex.org via the `api-key` header and never logged.
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "")
#: Diffbot Knowledge Graph: Enhance by name is the resolver's residue step
#: (spec 6.5; 7/10 on the syllabic-acronym and Georgian-script names no lexical
#: rule reaches). Its terms carry an explicit commercial grant and NO effective
#: date, so they are re-read before use: resolve_register refuses the rung
#: unless DIFFBOT_TERMS_READ_ON (ISO date) is within 31 days.
DIFFBOT_TOKEN = os.getenv("DIFFBOT_TOKEN", "")
DIFFBOT_TERMS_READ_ON = os.getenv("DIFFBOT_TERMS_READ_ON", "")
#: The free tier: 10,000 credits a month at 25 per entity (spec 13).
DIFFBOT_MONTHLY_ENTITIES = int(os.getenv("DIFFBOT_MONTHLY_ENTITIES", "400"))
#: One Tavily basic search is one credit; a name costs up to three (one per variant).
RESOLVER_TAVILY_CREDITS_PER_RUN = int(os.getenv("RESOLVER_TAVILY_CREDITS_PER_RUN", "100"))
#: Off until the fresh-script hold-out passes (build item 8 plan, Task 12).
RESOLVER_WRITES_ENABLED = os.getenv("RESOLVER_WRITES_ENABLED", "") == "1"
# --- The typed-decision layer (typed-decisions design §3.2, §9a; addendum 2026-09-26 §2) ---
#: Where Jev is reached. OpenRouter by default: TypeSafe paused new sign-ups,
#: and an OpenRouter key authenticates its System One route (the SDK appends
#: /v1/systemone). `https://api.typesafe.ai` reaches TypeSafe directly; moving
#: there also changes TYPESAFE_MODEL, whose ids carry no `typesafe/` prefix.
#: Every caller that wants Jev goes through apps/research/decisions.py::ask --
#: an absent key raises there and never degrades to a frontier model.
DECISIONS_BASE_URL = os.getenv("DECISIONS_BASE_URL", "https://openrouter.ai/api")
#: The key for any DECISIONS_BASE_URL that is not TypeSafe's own host. Env only,
#: never a default, never logged. Catalogue reads send public page sentences
#: only; a transcript reading (TRANSCRIPT_JEV_ENABLED, below) sends minimised
#: student content through this same route, so OpenRouter is a processor of
#: student-derived text once that gate opens and the DPA gate (docs/legal)
#: covers it too.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
#: The platform's one GitHub key (CV evidence spec §12.2): fine-grained, read-only, public
#: repositories only, no organisation access, held in Secrets Manager and delivered to the
#: document worker (infra/template.yaml). Empty means no request at all -- the
#: unauthenticated path through the shared NAT address is gone. Never logged, and sent to
#: api.github.com only (apps/documents/evidence/github.py).
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
#: Jev (TypeSafe System One) through OpenRouter (owner decision 2026-09-26):
#: `apps/research/jev.py` is the provenance vetoes' client (apps/research/blocking.py).
#: The key is OpenRouter's, env only. It coexists with the decision layer's client
#: above (DECISIONS_BASE_URL, TYPESAFE_MODEL); unifying the two is a later design decision.
#: Only page text is ever sent to it; no real student text before the DPA.
JEV_API_KEY = OPENROUTER_API_KEY
JEV_BASE_URL = os.getenv("JEV_BASE_URL", "https://openrouter.ai/api")
#: A pinned, versioned model -- never the moving `jev-latest` alias. Every
#: Jev threshold in the repo is tuned against this ID.
JEV_MODEL = os.getenv("JEV_MODEL", "jev-1.13")
#: Jev calls one provenance_check run may make for the two content vetoes
#: (spec §5.4 rules 3-4): the cost circuit-breaker the LLM rule requires.
PROVENANCE_VETO_RUN_LIMIT = int(os.getenv("PROVENANCE_VETO_RUN_LIMIT", "400"))
#: TypeSafe's own key: sent ONLY when DECISIONS_BASE_URL is api.typesafe.ai.
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY", "")
#: Launch gate for apps/documents/transcript.py::check_gates (tailored-programme
#: finding design §3.1): real students' transcripts go to Jev, through OpenRouter,
#: only after TypeSafe's DPA is accepted and OpenRouter's terms are reviewed. Off by
#: default -- checked in code, not left to DECISIONS_PROVIDER, because a shared
#: mapping is a setting someone else's decision could repoint. Do not set this in
#: infra/template.yaml until that review is done.
TRANSCRIPT_JEV_ENABLED = os.getenv("TRANSCRIPT_JEV_ENABLED", "") == "1"
#: The pinned OpenRouter id, never the `~typesafe/jev-latest` alias: thresholds
#: are tuned against a version and moved on our schedule. OpenRouter uses an
#: author-prefixed id as-is and answers with the dated snapshot it served
#: (`typesafe/jev-1.13-20260917`, read 2026-09-26), which DecisionRecord keeps.
TYPESAFE_MODEL = os.getenv("TYPESAFE_MODEL", "typesafe/jev-1.13")
#: Which provider answers which decision. "typesafe" means Jev through
#: DECISIONS_BASE_URL. An adapter entry appears ONLY when §11 gate 9's
#: measurement showed it better on that decision (optionally in one language:
#: "D4:kk-Cyrl"). Never a failover.
#: `evidence_support` (apps/documents/evidence/checks.py) is named even though it equals
#: the default: its state is student text (thesis spans), and checks.support refuses to
#: send it anywhere provider_for does not answer "typesafe" (CV evidence spec §7.4).
DECISIONS_PROVIDER: dict[str, str] = json.loads(
    os.getenv("DECISIONS_PROVIDER", '{"default": "typesafe", "evidence_support": "typesafe"}')
)
#: Layer 3 of the cost controls (spec §9a). Jev is cheap and unbounded; a
#: runaway sweep is still a bill. At $0.042/MTok this is about $8 a month.
DECISIONS_MONTHLY_TOKENS = int(os.getenv("DECISIONS_MONTHLY_TOKENS", "200000000"))
#: Per run, checked before every request. A run that exhausts it reschedules
#: through the fetch engine's retry queue rather than skipping pages silently.
DECISIONS_RUN_TOKENS = int(os.getenv("DECISIONS_RUN_TOKENS", "20000000"))
#: Classifier abstain threshold (spec 6.6): a verdict below this probability is
#: written as a confidence, never as a kind, and the host is asked again by the
#: next rung. 0.8 until the gate says otherwise.
ORG_CLASSIFY_MIN_P = float(os.getenv("ORG_CLASSIFY_MIN_P", "0.8"))
#: Model calls one classification run may make in an hour -- the cost
#: circuit-breaker the LLM rule requires, sized to a register pass.
ORG_CLASSIFY_RUN_LIMIT = int(os.getenv("ORG_CLASSIFY_RUN_LIMIT", "3000"))
#: The platform-only resolution queue (spec 11): "a daily cap per operator
#: (default 20)" -- decisions and parks both count -- and "expires_at (30 days
#: unopened)", counted from first filing.
RESOLUTION_DAILY_CAP_PER_OPERATOR = int(os.getenv("RESOLUTION_DAILY_CAP_PER_OPERATOR", "20"))
RESOLUTION_EXPIRY_DAYS = int(os.getenv("RESOLUTION_EXPIRY_DAYS", "30"))
#: CV relevance engine (apps/documents/relevance.py). Ships switched OFF: an
#: item is judged only when its language is listed here, and a language is
#: listed only after `manage.py cv_relevance_eval` reports it at or above the
#: pass mark (spec §7.2). "tr" and "az" must BOTH be listed for a Turkic
#: Latin line, because the script cannot tell them apart.
CV_RELEVANCE_LANGUAGES: frozenset[str] = frozenset()
#: P(unrelated) at or above which an item is left out. Set from the
#: measurement's Learn-then-Test bar; 0.9 is the spec's starting value.
CV_RELEVANCE_BAR = 0.9

# --- The card reader's stack (verified-catalog §5, §0.25; provisional until owner round 2) ---
#: Two cheap readers read every section; the decider answers only their split. One setting that
#: every question set and every session reuses (apps/research/card_engine/readers.py::stack
#: refuses a malformed one). Each OpenRouter reader is pinned to ONE host: a re-pinned host is a
#: re-certification (§5.5). DeepSeek's host (inference-net/fp8) was chosen by the 2026-10-12
#: three-host measurement; Fireworks 429'd on every call. gpt-6-luna takes no `temperature`
#: (404 under require_parameters, measured 2026-10-11). CARD_READERS_JSON replaces the whole stack.
_CARD_READERS_DEFAULT: dict[str, object] = {
    "pair": [
        {"name": "deepseek", "transport": "openrouter", "model": "deepseek/deepseek-v4.1-flash",
         "host": "inference-net/fp8",
         "params": {"reasoning": {"enabled": False}, "temperature": 0}},
        {"name": "luna", "transport": "openrouter", "model": "openai/gpt-6-luna",
         "host": "openai", "params": {"reasoning": {"effort": "none"}}},
    ],
    "decider": {"name": "opus", "transport": "anthropic", "model": "claude-opus-5-5"},
}
#: Unset means the default; anything set is used as written, so `{}`, `[]` or `0` is refused by
#: stack() (and `manage.py check`) instead of silently becoming the default.
def _card_readers(raw: str) -> object:
    """Malformed JSON stays a string so stack() raises StackMisconfigured and `manage.py check`
    reports research.E001, instead of settings import taking down every process."""
    if not raw:
        return _CARD_READERS_DEFAULT
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


CARD_READERS: object = _card_readers(os.getenv("CARD_READERS_JSON", ""))
#: Model calls (every attempt, D8 included) one catalogue run may make in an hour, and one
#: tenant's on-demand reads (a typed programme, §3.3): the cost circuit-breakers CLAUDE.md's LLM
#: rule requires, counted through apps/ratelimit.rate_limited.
CARD_READER_RUN_CALLS_PER_HOUR = int(os.getenv("CARD_READER_RUN_CALLS_PER_HOUR", "20000"))
CARD_READER_TENANT_CALLS_PER_HOUR = int(os.getenv("CARD_READER_TENANT_CALLS_PER_HOUR", "400"))

#: The sweep harness (spec 6.7). Generations per (country, family) per day --
#: one call per language of the pass, so 8 covers a four-language country
#: regenerated once.
SWEEP_ANGLE_GENERATIONS_PER_DAY = int(os.getenv("SWEEP_ANGLE_GENERATIONS_PER_DAY", "8"))
#: The model that writes the sweep's search sentences (angles.py), through OpenRouter with
#: OPENROUTER_API_KEY. DeepSeek, not OPENAI_EXTRACTION_MODEL: measured 2026-10-13 on Turkish
#: foundations (docs/superpowers/research/2026-10-13-sweep-sentence-writing-comparison.md), it was
#: the most consistent writer at a third of the cost, and the 2026-10-03 engine design names it.
SWEEP_ANGLE_MODEL = os.getenv("SWEEP_ANGLE_MODEL", "deepseek/deepseek-v4.1-flash")
#: One pass's search + classification-fetch ceiling, USD. $5 fits Exa's free
#: $10/month and Brave's free tier at measurement scale; corridor-scale runs
#: wait for the plans (spec section 7).
SWEEP_PASS_BUDGET_USD = float(os.getenv("SWEEP_PASS_BUDGET_USD", "5.0"))
#: The economic stop rule's two inputs. OWNER'S NUMBER OWED for the first:
#: "what the option is worth to a student" has no figure in the spec. 5.0 is
#: a tenth of the $50 cycle wallet. At the measured ~$0.3 a batch the rule
#: binds only below ~0.06 new verified hosts a batch, so the plateau rule
#: stops almost every measurement-scale pass -- which is the honest behaviour
#: until the owner sets this. Batch spend is search plus classification fetch
#: only -- the classifier's model cost is not counted.
SWEEP_VALUE_PER_AWARD_USD = float(os.getenv("SWEEP_VALUE_PER_AWARD_USD", "5.0"))
#: A verified host funds students, so it holds at least one award. 1.0 is that
#: floor: it overstates cost per award, so the rule errs toward stopping.
SWEEP_AWARDS_PER_VERIFIED_HOST = float(os.getenv("SWEEP_AWARDS_PER_VERIFIED_HOST", "1.0"))
#: An angle is retired only after this many asks (one ask = one provider, one
#: batch, one run) with zero verified first-discoveries across every run. Four
#: is two providers x two runs: never one run's noise (spec 15, +-2/16).
SWEEP_DEAD_AFTER_USES = int(os.getenv("SWEEP_DEAD_AFTER_USES", "4"))

# A hand-read closed list past this many days since `verified_on` prints STALE
# on the coverage line (spec 6.2: "a list past its verified-on date raises
# re-check priority"). One admissions season; it flags, it never fails the gate.
CLOSED_LIST_RECHECK_DAYS = int(os.getenv("CLOSED_LIST_RECHECK_DAYS", "90"))
# Wikimedia's User-Agent policy requires a contact; a generic client string is
# throttled or refused. Operator-run enumeration only (apps/research/wikidata.py).
WIKIDATA_USER_AGENT = os.getenv(
    "WIKIDATA_USER_AGENT",
    "elmify-enumerator/1.0 (https://github.com/0rkhann/elmify)",
)
# ROR v2 identifies heavy clients by a free client id sent as `Client-Id`;
# blank sends none.
ROR_CLIENT_ID = os.getenv("ROR_CLIENT_ID", "")
#: The institution provenance gate (2026-09-26 spec §7.7). OFF until
#: `manage.py provenance_check --all` has filled the verdict table: enforced on
#: an empty table, every pack is empty. docs/runbooks/deploy.md has the order.
PROVENANCE_GATE_ENFORCED = os.getenv("PROVENANCE_GATE_ENFORCED", "") == "1"
#: One re-check cycle: register reloads, UNCONFIRMED retries and the sweep's
#: two-cycle removal all count in these.
PROVENANCE_CYCLE_DAYS = int(os.getenv("PROVENANCE_CYCLE_DAYS", "30"))
#: A RECOGNISED pair gets a free screen (RDAP + mill list, no page fetch) this
#: often; only a flagged one is fully re-checked. MAX caps one run's screens.
PROVENANCE_RECOGNISED_SCREEN_DAYS = int(os.getenv("PROVENANCE_RECOGNISED_SCREEN_DAYS", "365"))
PROVENANCE_RECOGNISED_SCREEN_MAX = int(os.getenv("PROVENANCE_RECOGNISED_SCREEN_MAX", "500"))
#: Per-tenant daily ceiling on research-fit VENDOR SEARCH SPEND only --
#: summed from Exa costDollars and Tavily credits (service.py::spend_within_ceiling).
#: **Stale since the master merge, 2026-09-23:** page fetches used to be free
#: (our own local egress) when this comment was written; research-fit now
#: fetches through apps.research.discovery.retrieve_official_source, i.e. the
#: Firecrawl/scrape.do vendor path, so every fetch also spends a billable
#: vendor credit (~$0.0008, up to ~$0.003 on an escalated fetch) -- and this
#: ceiling does NOT meter that spend. One propose_research_fit call can fetch
#: up to roughly 2 anchors x domains x 2 queries x 3 pages, all unmetered here.
#: A fetch-side bound is an owed decision (D15, docs/superpowers/specs/
#: 2026-09-22-letter-research-fit-from-the-student-design.md), not yet made.
#: Model-call VOLUME (not fetch or search cost) is bounded separately by the
#: per-student `research-fit` rate limit (20/hour).
RESEARCH_FIT_DAILY_CEILING_USD = float(os.getenv("RESEARCH_FIT_DAILY_CEILING_USD", "5.0"))
#: List prices per million tokens, for turning a reading's RECORDED token counts
#: into dollars (funding master spec §9.3: "model tokens at list price ...
#: recorded, never estimated"). Data with a verified-on date, never logic: a
#: model with no row is reported UNPRICED, never priced at zero or at a
#: neighbour's rate -- a price table that goes stale in silence is exactly the
#: failure CLAUDE.md records against research_fit. `cache_read`/`cache_write`
#: are the prompt-cache rates (Anthropic: 0.1x and 1.25x input for the default
#: 5-minute TTL). OpenAI reports no cache writes, so its `cache_write` is never
#: charged; set it equal to `input`. MODEL_PRICES_JSON replaces the whole table.
MODEL_PRICES_VERIFIED_ON = os.getenv("MODEL_PRICES_VERIFIED_ON", "2026-09-26")
_PRICE_KEYS = frozenset({"input", "cache_read", "cache_write", "output"})


def _price_override(raw: str) -> dict[str, dict[str, float]]:
    """MODEL_PRICES_JSON, refused at startup when malformed -- never later, as
    a KeyError inside a cost report after the run has spent the money."""
    if not raw:
        return {}
    table = json.loads(raw)
    if not isinstance(table, dict) or not all(
        isinstance(row, dict)
        and set(row) == _PRICE_KEYS
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in row.values())
        for row in table.values()
    ):
        raise ValueError(
            "MODEL_PRICES_JSON must map each model to exactly "
            f"{sorted(_PRICE_KEYS)} as numbers (USD per million tokens)"
        )
    return {str(model): {k: float(v) for k, v in row.items()} for model, row in table.items()}


_MODEL_PRICES_OVERRIDE = _price_override(os.getenv("MODEL_PRICES_JSON", ""))
MODEL_PRICES_USD_PER_MTOK: dict[str, dict[str, float]] = _MODEL_PRICES_OVERRIDE or {
    # Anthropic pricing, verified 2026-09-26: Sonnet 5 is $2 input / $10 output
    # per MTok; cache read 0.1x input, 5-minute cache write 1.25x input.
    "claude-sonnet-5": {"input": 2.00, "cache_read": 0.20, "cache_write": 2.50, "output": 10.00},
    # Claude Opus 5.5, verified 2026-10-12 at platform.claude.com/docs/en/about-claude/pricing:
    # "| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok | $20 / MTok |"
    # (base input, 5m cache write, 1h cache write, cache hits, output). The page names models by
    # display name; claude-opus-5-5 is this repo's id for it (the card reader's decider).
    "claude-opus-5-5": {"input": 4.00, "cache_read": 0.20, "cache_write": 5.00, "output": 20.00},
    # OPENAI_EXTRACTION_MODEL (gpt-5.6-luna) is deliberately UNPRICED: no row
    # until a published OpenAI price for that exact model has been read (on
    # 2026-09-26 openai.com/api/pricing and platform.openai.com/docs/pricing
    # were unreachable from the build environment). Its readings are reported
    # in tokens only, and CostMeter counts them as `unpriced` -- never as $0.
}
#: What a service tier bills relative to list price. Anthropic's batch API is
#: 50% of every token class, cache included (Anthropic pricing, verified
#: 2026-09-26). OpenAI's batch 50% and "flex bills at batch rates" are the
#: plan's reading and are UNVERIFIED here (its pricing page was unreachable on
#: 2026-09-26); they price nothing today, because the OpenAI model has no row,
#: and must be confirmed on that page when the row is added. A tier with no
#: row here (priority, ultrafast) is unpriced, never assumed to be list price.
MODEL_TIER_MULTIPLIER: dict[str, float] = {"default": 1.0, "flex": 0.5, "batch": 0.5}
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
SCRAPEDO_API_KEY = os.getenv("SCRAPEDO_API_KEY", "")
#: Credits one sweep may spend, PER VENDOR, before it stops. Exists because
#: scrape.do applies per-domain multipliers of 10-200 credits server-side with no
#: request-time signal (spec 4.1a) -- a tariff in code cannot predict the bill, so
#: the budget is held against the cost header the response actually returns.
#: Per vendor rather than one pool because a credit is not a unit: Firecrawl's is
#: 7.16x scrape.do's (apps/research/fetch.USD_PER_CREDIT), so one shared ceiling
#: is seven different ceilings depending on which vendor happened to answer.
#: Defaults: half of scrape.do's free 1,000, a tenth of Firecrawl's.
FETCH_SWEEP_CREDITS = {
    "FIRECRAWL": int(os.getenv("FETCH_SWEEP_CREDITS_FIRECRAWL", "100")),
    "SCRAPE_DO": int(os.getenv("FETCH_SWEEP_CREDITS_SCRAPE_DO", "500")),
}
#: Firecrawl's webhook HMAC key. Environment only, like the API keys: a
#: settings default here would mean a deployment that forgot to set it still
#: verifies signatures -- against a value in the repository, which is the same
#: as not verifying them.
FIRECRAWL_WEBHOOK_SECRET = os.getenv("FIRECRAWL_WEBHOOK_SECRET", "")
#: The receiver is off until a public HTTPS endpoint exists. Until then the
#: monitor's delivery path is `manage.py poll_monitor_checks`, which costs no
#: credits. A URL route that 404s is a smaller surface than one that exists and
#: is unreachable -- Firecrawl retries three times and would report our own
#: unreachability as a delivery failure on every check. Do NOT turn it on as
#: is: the receiver writes a catalogue table from the web tier (`runtime_web`,
#: no grant), so every delivery 500s. See apps/research/views.py.
FETCH_WEBHOOKS_ENABLED = os.getenv("FETCH_WEBHOOKS_ENABLED", "") == "1"
#: Firecrawl Standard's concurrent browsers. Sizes `maxConcurrency` on a crawl,
#: and is HALVED for the rest of a sweep when a response reports
#: `concurrencyLimited` with a long queue (spec 9.3): the vendor is already
#: queueing our work, and asking for more parallelism buys latency, not pages.
FIRECRAWL_CONCURRENCY = int(os.getenv("FIRECRAWL_CONCURRENCY", "25"))
#: Standard's monthly credits. Read by the monitor pre-flight only: a monitor
#: is created only if the cycle's `estimatedCreditsPerMonth` fits inside this
#: minus the sweep reserve, because a monitor that cannot pay for its checks
#: reports `skipped_no_credits` forever and looks like a site that never changes.
FIRECRAWL_MONTHLY_CREDITS = int(os.getenv("FIRECRAWL_MONTHLY_CREDITS", "100000"))
#: Pages per host per sweep. 1 credit per page PLUS 1 per PDF page, so the
#: worst case is this times (1 + FETCH_PDF_MAX_PAGES) and the sweep budget is
#: checked against that ceiling before the crawl job is submitted -- Firecrawl's
#: own pre-flight answers 402 for a limit the balance cannot cover, and a 402
#: mid-sweep is a bill we did not choose.
FETCH_CRAWL_LIMIT = int(os.getenv("FETCH_CRAWL_LIMIT", "25"))
#: Per /agent run, SET EXPLICITLY on every call. The documented default is
#: 2,500 credits -- about $2 a programme at Standard, roughly eighty times what
#: this stage is meant to cost (spec 7.4, read from Firecrawl's own page
#: 2026-09-23). Leaving it unset is the single most expensive omission
#: available on this path.
FETCH_AGENT_MAX_CREDITS = int(os.getenv("FETCH_AGENT_MAX_CREDITS", "300"))
#: `on_miss` or `always` for funnel stages 3 and 4 (spec 7.0). The corpus flips
#: it by running the dear stages on programmes that already counted as found
#: and counting the rules the crawl missed. Any other value is an error at the
#: seam, never a silent "not always".
FETCH_NAVIGATOR_POLICY = os.getenv("FETCH_NAVIGATOR_POLICY", "on_miss")
#: URLs per Tavily guided map (spec 7.3a). Its key is the existing
#: SEARCH_API_KEY; Tavily bills 2 credits per ten successful pages WITH
#: instructions against 1 without, so this number is the stage's price.
FETCH_GUIDED_MAP_LIMIT = int(os.getenv("FETCH_GUIDED_MAP_LIMIT", "50"))
#: A PDF is billed per PAGE. A 200-page handbook is 200 credits, so the read is
#: capped and a truncated read is recorded as FETCHED_PARTIAL, never silently.
FETCH_PDF_MAX_PAGES = int(os.getenv("FETCH_PDF_MAX_PAGES", "60"))
#: Owner decision 2026-09-22: a capture within the current admissions cycle is
#: the rule applicants are held to. Older is `archive_stale`, and a person sees it.
FETCH_ARCHIVE_MAX_AGE_DAYS = int(os.getenv("FETCH_ARCHIVE_MAX_AGE_DAYS", "365"))
#: A host remembered at an expensive rung is retried from rung 1 this often, so
#: a host that got easier stops paying rung-4 prices.
FETCH_REPROBE_DAYS = int(os.getenv("FETCH_REPROBE_DAYS", "30"))
#: The Firecrawl request timeout when no HostProfile row exists yet.
#: HostProfile.timeout_ms (models.py) is the per-host override once one is
#: learned; this is deliberately the SAME default (60000) so the no-profile
#: path and the column default cannot diverge silently (Task 2 obligation).
FETCH_DEFAULT_TIMEOUT_MS = int(os.getenv("FETCH_DEFAULT_TIMEOUT_MS", "60000"))
#: Rung 5. How many RETRY_SCHEDULED rounds a URL gets before rung 6 (the
#: archive) is read. Three, per spec §4 -- a host that is merely down must not
#: be answered from a year-old capture on the first failure.
FETCH_MAX_RETRIES = int(os.getenv("FETCH_MAX_RETRIES", "3"))
#: Hours to wait before each retry round, per failure class (spec §4 rung 5).
#: A block clears sooner than an outage does, so the two schedules differ; a
#: round past the end of a list reuses its last entry.
FETCH_RETRY_HOURS = {
    "unreachable": [
        int(hours) for hours in os.getenv("FETCH_RETRY_HOURS_UNREACHABLE", "24,48,96").split(",")
    ],
    "blocked": [
        int(hours) for hours in os.getenv("FETCH_RETRY_HOURS_BLOCKED", "6,24,48").split(",")
    ],
}
#: How long a URL dropped at a budget boundary waits before it is worth asking
#: again. The sweep cap is per SWEEP, so the boundary was never the host's
#: fault: the BUDGET row carries this as `retry_after` and Task 10's queue picks
#: it up alongside RETRY_SCHEDULED. It is deliberately NOT a RETRY_SCHEDULED
#: row -- `_retries_spent` counts those forever, so writing one would spend one
#: of the three rounds a real failure is owed.
FETCH_BUDGET_RETRY_HOURS = int(os.getenv("FETCH_BUDGET_RETRY_HOURS", "24"))

# --- Cycle verification (funding engine item 11; master spec 9.2-9.3) ----------
#: Step 1's crawl: spec 9.2's `limit: 15`, not FETCH_CRAWL_LIMIT's 25.
CYCLE_CRAWL_LIMIT = int(os.getenv("CYCLE_CRAWL_LIMIT", "15"))
#: Step 3: Exa `numResults`.
CYCLE_SEARCH_RESULTS = int(os.getenv("CYCLE_SEARCH_RESULTS", "10"))
#: Step 1b: how many previous cycles' captures, and how far a capture may sit
#: from the date asked for before it describes a different cycle.
CYCLE_ARCHIVE_YEARS_BACK = int(os.getenv("CYCLE_ARCHIVE_YEARS_BACK", "2"))
CYCLE_ARCHIVE_SKEW_DAYS = int(os.getenv("CYCLE_ARCHIVE_SKEW_DAYS", "120"))
#: How many upcoming intakes each award is verified for.
CYCLE_TRACKED_INTAKES = int(os.getenv("CYCLE_TRACKED_INTAKES", "2"))
#: Cadence (spec 9.3): monthly; weekly in the two months before last cycle's
#: call and from one month before a projected opening; daily within 14 days of
#: a known deadline; a projection 45 days late with no call lapses.
CYCLE_CHECK_DAYS_DEFAULT = int(os.getenv("CYCLE_CHECK_DAYS_DEFAULT", "30"))
CYCLE_CHECK_DAYS_SEASON = int(os.getenv("CYCLE_CHECK_DAYS_SEASON", "7"))
CYCLE_CHECK_DAYS_DEADLINE = int(os.getenv("CYCLE_CHECK_DAYS_DEADLINE", "1"))
CYCLE_DEADLINE_WINDOW_DAYS = int(os.getenv("CYCLE_DEADLINE_WINDOW_DAYS", "14"))
CYCLE_SEASON_WINDOW_DAYS = int(os.getenv("CYCLE_SEASON_WINDOW_DAYS", "61"))
CYCLE_PROJECTION_LEAD_DAYS = int(os.getenv("CYCLE_PROJECTION_LEAD_DAYS", "30"))
CYCLE_PROJECTION_LAPSE_DAYS = int(os.getenv("CYCLE_PROJECTION_LAPSE_DAYS", "45"))
#: Cost ceilings. Per award: spec 9.3's upper estimate. Per run: what one
#: scheduled invocation may spend across every award it verifies.
CYCLE_VERIFY_MAX_USD_PER_AWARD = float(os.getenv("CYCLE_VERIFY_MAX_USD_PER_AWARD", "0.40"))
CYCLE_VERIFY_RUN_BUDGET_USD = float(os.getenv("CYCLE_VERIFY_RUN_BUDGET_USD", "10"))
#: An award whose run raised is retried this many days later, not at once: a
#: row that fails every run would otherwise head the due queue for ever.
CYCLE_ERROR_BACKOFF_DAYS = int(os.getenv("CYCLE_ERROR_BACKOFF_DAYS", "1"))
CYCLE_RUN_CREDITS = {
    "FIRECRAWL": int(os.getenv("CYCLE_RUN_CREDITS_FIRECRAWL", "1000")),
    "SCRAPE_DO": int(os.getenv("CYCLE_RUN_CREDITS_SCRAPE_DO", "1000")),
}
#: The model-call circuit-breaker (CLAUDE.md "LLM/AI security"), per platform.
CYCLE_VERIFY_MODEL_CALLS_PER_HOUR = int(os.getenv("CYCLE_VERIFY_MODEL_CALLS_PER_HOUR", "600"))
#: Brave's list price, $5 per 1,000 requests (master spec 13).
BRAVE_USD_PER_REQUEST = float(os.getenv("BRAVE_USD_PER_REQUEST", "0.005"))

# --- The search tap and its cycle wallet (demand cells, build item 14) ------
# Money, so Decimal: every figure here is compared against a ledger of
# Decimal WalletCharge rows (apps/research/wallet.py).
#: Spec 10.5 / decision 28: one student's search budget for one admission cycle.
#: $100, owner 2026-10-14 (was $50): one big first search, then small follow-ups.
SEARCH_WALLET_USD = Decimal(os.getenv("SEARCH_WALLET_USD", "100"))
#: Retail B2C student search wallet cap on PlatformAgency (299 AZN / 499 AZN pass):
#: caps worst-case cold search COGS at $35 (~59.50 AZN) and 1 wallet per cycle.
STUDENT_B2C_SEARCH_WALLET_USD = Decimal(os.getenv("STUDENT_B2C_SEARCH_WALLET_USD", "35"))
STUDENT_B2C_SEARCH_WALLETS_PER_YEAR = int(os.getenv("STUDENT_B2C_SEARCH_WALLETS_PER_YEAR", "1"))
#: What the first search may not spend, so follow-ups stay possible.
SEARCH_FOLLOWUP_RESERVE_USD = Decimal(os.getenv("SEARCH_FOLLOWUP_RESERVE_USD", "10"))
#: Owner check (plan decision 4): an edited intake must not mint a new wallet
#: forever. A third intake inside 365 days reuses the newest wallet.
SEARCH_WALLETS_PER_YEAR = int(os.getenv("SEARCH_WALLETS_PER_YEAR", "2"))
#: Spec 10.5: a tap spends at most this share of what remains (recommended 0.5, §19).
TAP_WALLET_SHARE = Decimal(os.getenv("TAP_WALLET_SHARE", "0.5"))
#: Twice TAP_MAX_QUERIES: two providers make two calls per query. Follow-ups
#: only; the first search is bounded by money, the plateau and its time cap.
TAP_MAX_PROVIDER_CALLS = int(os.getenv("TAP_MAX_PROVIDER_CALLS", "60"))
#: Queries one follow-up renders (spec 10.5). Each goes to Exa ($0.009 at 12
#: results) and Brave ($0.005), so 30 queries are about $0.42 of search. The
#: first search is capped by money and the plateau rule instead.
TAP_MAX_QUERIES = int(os.getenv("TAP_MAX_QUERIES", "30"))
TAP_MAX_PAGES = int(os.getenv("TAP_MAX_PAGES", "30"))
#: A follow-up's time cap; the first search has FIRST_SEARCH_MAX_SECONDS.
TAP_MAX_SECONDS = int(os.getenv("TAP_MAX_SECONDS", "180"))
#: The first search runs in the worker, in the background. Under ResearchQueue's
#: VisibilityTimeout (900 s, infra/template.yaml): a run outlasting it would see
#: SQS hand the same message to another worker mid-search.
FIRST_SEARCH_MAX_SECONDS = int(os.getenv("FIRST_SEARCH_MAX_SECONDS", "840"))
#: A FIRST search that runs out of FIRST_SEARCH_MAX_SECONDS saves its place and
#: continues in a new job; money and the plateau end it, and this many
#: continuations is only a runaway guard (it then ends TIME_CAP).
FIRST_SEARCH_MAX_CONTINUATIONS = int(os.getenv("FIRST_SEARCH_MAX_CONTINUATIONS", "6"))
#: Search requests a tap has in flight at once (owner, 2026-10-15). Under both
#: providers' recorded limits: Exa 10 q/s (developer plan), Brave 50 q/s (Search
#: plan) -- docs/superpowers/research/2026-08-30-live-search-review-1.md. A
#: request asks its providers one after another, so each sees at most this many.
TAP_PARALLEL_CALLS = int(os.getenv("TAP_PARALLEL_CALLS", "8"))
#: The sweep's plateau rule, per query: stop when this many queries in a row
#: bring fewer than FIRST_SEARCH_PLATEAU_MIN_NEW new hosts between them.
FIRST_SEARCH_PLATEAU_BATCH = int(os.getenv("FIRST_SEARCH_PLATEAU_BATCH", "10"))
FIRST_SEARCH_PLATEAU_MIN_NEW = int(os.getenv("FIRST_SEARCH_PLATEAU_MIN_NEW", "2"))
#: The deep stage's results per query, Exa only (about $0.097 a call; Brave
#: returns at most 20 per query).
FIRST_SEARCH_DEEP_RESULTS = int(os.getenv("FIRST_SEARCH_DEEP_RESULTS", "100"))
#: A query any student ran within this many days is not run again: its hosts
#: are already in the catalogue (plan Task 4b reads it).
TAP_QUERY_REUSE_DAYS = int(os.getenv("TAP_QUERY_REUSE_DAYS", "30"))
#: Off until stage 2 is bound (plan Task 7): until then searches run by the
#: operator command only, so no student's money buys hosts nothing reads.
TAP_AUTOMATIC = os.getenv("TAP_AUTOMATIC", "") == "1"
#: Taps per student per rolling day, counted from SearchTap rows (durable),
#: never from apps/ratelimit.py's per-process cache.
TAP_PER_DAY = int(os.getenv("TAP_PER_DAY", "2"))
#: The cheapest per-page read the platform can make today. Spec 10.5: ~$0.35 a
#: host, ~$0.18 via Batch/Flex. RE-DERIVE whenever a page gets cheaper (§8.9's
#: cheap first read, Jev as classifier): the page backstop is computed from it.
CHEAPEST_PAGE_READ_USD = Decimal(os.getenv("CHEAPEST_PAGE_READ_USD", "0.35"))
#: A runaway guard for many wallets draining at once -- never the thing that
#: bounds the bill (the wallet does).
SEARCH_TENANT_DAILY_CEILING_USD = Decimal(os.getenv("SEARCH_TENANT_DAILY_CEILING_USD", "200"))
#: Worst-case price of one call, checked BEFORE it is made, per provider.
#: exa: the roster's list price (docs/superpowers/specs/
#: 2026-09-17-role-routed-discovery-design.md §4.13, Exa row: "$7/1k requests
#: + $1/1k per result beyond 10") at the tap's ceiling of 15 results:
#: 0.007 + 5 x 0.001 = $0.012. The $0.097 in spec 10.5 is the 100-result price
#: the sweep uses, not the tap's. brave: its per-request list price, the one
#: BRAVE_USD_PER_REQUEST above already carries -- reused, not restated.
PROVIDER_CALL_PREFLIGHT_USD = {
    "exa": Decimal(os.getenv("EXA_TAP_PREFLIGHT_USD", "0.012")),
    "brave": Decimal(str(BRAVE_USD_PER_REQUEST)),
}
#: One bounded AREA sweep's ceiling (spec 10.5 step 5), passed to the harness
#: as PassConfig.budget_usd -- replaces the plan's CELL_SWEEP_MAX_CALLS,
#: because the real harness is bounded by money and its own stop rules, not a
#: call count. A float because PassConfig.budget_usd is one.
CELL_SWEEP_BUDGET_USD = float(os.getenv("CELL_SWEEP_BUDGET_USD", "5.0"))
#: Off until the card reader's slice 3 serves the master's-only level rule: the
#: level-free funder sentences (commit 07a196dd) would let undergraduate-only
#: funders through. While False, no funder-family sweep runs (`sweep_organisations`
#: refuses, `run_area_sweeps` marks the row UNAVAILABLE). Every family in
#: `angles.PASS_SHAPES` is a funder sweep.
FUNDER_SWEEP_LEVEL_CHECK_LIVE = (
    os.getenv("FUNDER_SWEEP_LEVEL_CHECK_LIVE", "true").lower() == "true"
)
#: An area swept within this many days is not swept again on demand.
CELL_SWEEP_COOLDOWN_DAYS = int(os.getenv("CELL_SWEEP_COOLDOWN_DAYS", "30"))
#: How long `retry_due_fetches` holds a host's DomainLease for one re-entry.
#: Pacing against the ladder's OWN mechanism (services.acquire_domain_lease),
#: not a second one -- a concurrent sweep on the same host makes this worker
#: back off (DomainBusy) rather than race it.
FETCH_RETRY_LEASE_SECONDS = int(os.getenv("FETCH_RETRY_LEASE_SECONDS", "30"))

#: The OAuth client this platform is registered as. Not secrets in the
#: Secrets-Manager sense -- they identify the app, not a student -- but the two
#: client secrets are credentials and come from the environment like every other
#: one here. Empty by default so a developer machine has no live grant.
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
MICROSOFT_OAUTH_CLIENT_ID = os.getenv("MICROSOFT_OAUTH_CLIENT_ID", "")
MICROSOFT_OAUTH_CLIENT_SECRET = os.getenv("MICROSOFT_OAUTH_CLIENT_SECRET", "")
#: Absolute https base the provider redirects back to, e.g.
#: "https://agency.example.com". The callback path is appended by
#: apps/mailbox/oauth.py; it must match the redirect URI registered with both
#: providers exactly, including the scheme.
MAILBOX_OAUTH_REDIRECT_BASE = os.getenv("MAILBOX_OAUTH_REDIRECT_BASE", "")

#: The KMS key portal passwords are encrypted under (infra: PortalCredentialsKey).
#: Blank locally and in tests, where Secrets Manager's default key is used.
PORTAL_SECRETS_KMS_KEY_ID = os.getenv("PORTAL_SECRETS_KMS_KEY_ID", "")


def _providers(value: str) -> tuple[str, ...]:
    """Normalise a comma-separated MAILBOX_PROVIDERS value.

    Each item is stripped and upper-cased so "MICROSOFT, GOOGLE" (a stray
    space after the comma) and "microsoft" (lowercase) both match the
    Provider choices, and an empty item (leading/trailing/doubled comma) is
    dropped rather than becoming a provider string nothing ever equals (fix
    round 1, finding 2).
    """
    return tuple(item for item in (piece.strip().upper() for piece in value.split(",")) if item)


#: Providers a student may connect. Google stays off until the app passes
#: Google's restricted-scope verification (owner decision 2026-09-26).
MAILBOX_PROVIDERS = _providers(os.getenv("MAILBOX_PROVIDERS", "MICROSOFT"))

#: Graph push for Microsoft mailboxes (apps/mailbox/push.py, watch spec §3a).
#: Off by default: subscribing needs a public HTTPS tenant host Graph can reach
#: and the mailbox worker running, and neither exists on a developer machine.
MAILBOX_PUSH_ENABLED = os.getenv("MAILBOX_PUSH_ENABLED", "") == "1"
MAILBOX_QUEUE_URL = os.getenv("MAILBOX_QUEUE_URL", "test-mailbox-queue")

#:The address deadline reminders are sent from. Empty by default and empty in
#: production today: no company sending domain exists yet (owner, 2026-09-19),
#: and an unset value is what keeps the channel dormant rather than failing.
#: Setting it, plus an SES-backed EMAIL_BACKEND, is the whole switch-on.
REMINDER_EMAIL_FROM = os.getenv("REMINDER_EMAIL_FROM", "")

#: Launch gate for apps/documents/cv_verbs.py (CV design 2026-10-12 §5.1): a
#: student's CV bullets go to Jev, through OpenRouter, only after the same DPA
#: and terms review TRANSCRIPT_JEV_ENABLED waits for. Off: lines stay as written.
CV_VERB_JEV_ENABLED = os.getenv("CV_VERB_JEV_ENABLED", "") == "1"

#: The same budget, per ONE research-fit proposal rather than per sweep (design
#: D15). Every page `propose_research_fit` reads is a billable vendor credit and
#: `RESEARCH_FIT_DAILY_CEILING_USD` meters SEARCH spend only, so before this the
#: fetch half was bounded by nothing but the per-student 20/hour call limiter --
#: a count, not a dollar figure. (Why `MAX_PAGES_CLASSIFIED` does not bound it
#: either is in `service.propose_research_fit`.)
#: The numbers are that search space: 2 anchors x 2 domains x 2 queries x
#: TOP_PAGES = 24 attempts at Firecrawl's 1 credit, and half of them escalating
#: to scrape.do's 25-credit residue tier. About $0.055 a proposal at the plans
#: priced on 2026-09-19 -- and the dollars, not the credits, are what the daily
#: per-tenant ceiling now sees, because the budget's usd() is added to it.
RESEARCH_FIT_FETCH_CREDITS = {
    "FIRECRAWL": int(os.getenv("RESEARCH_FIT_FETCH_CREDITS_FIRECRAWL", "24")),
    "SCRAPE_DO": int(os.getenv("RESEARCH_FIT_FETCH_CREDITS_SCRAPE_DO", "300")),
}

# Without this, apps.documents.europass_worker's "EuropassCallMade" log line
# (and every other apps.* logger call) is dropped before it reaches any
# handler: DEBUG=False in production, Django's default console handler is
# filtered by require_debug_true and is only attached to the "django"
# logger anyway, so an unconfigured "apps.*" logger propagates to a
# handler-less root and logging.lastResort silently swallows anything below
# WARNING. EuropassCallsFilter's metric (infra/template.yaml) reads zero
# forever without this. Deliberately minimal: only "apps" is configured, so
# Django's own logging (DEFAULT_LOGGING, applied before this) is untouched.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "apps": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
