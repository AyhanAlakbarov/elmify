# Base images are pinned by digest, not tag: a tag is repointable, so
# "python:3.12-slim" is whatever the registry serves today. Both digests are
# multi-platform OCI indexes, so amd64 and arm64 both resolve. Bump these
# deliberately -- they will NOT pick up upstream security patches on their own.

# Named stage rather than COPY --from=<image> directly: Dependabot's docker
# updater only parses FROM lines (dependabot-core#5103), so an inline image
# reference here would never be bumped. The alias makes it a FROM line.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913 AS build

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913 AS runtime

WORKDIR /app
# Both final stages drop to this account before their CMD. Nothing in the app
# writes to /app at runtime, so the tree stays root-owned and read-only to the
# process -- a code-execution bug then lands as "app", not root.
RUN useradd --system --create-home --uid 10001 app
COPY --from=build /app/.venv /app/.venv
COPY . .
ENV DJANGO_SETTINGS_MODULE=config.settings.production
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

FROM runtime AS web
# WeasyPrint (apps/documents/render.py) loads Pango/cairo/GDK-PixBuf through
# cffi at import time -- python:3.14-slim ships none of them. fonts-dejavu-core
# is the letter and CV templates' own default: without it, a font-less renderer
# picks a substitute with different metrics, and page count gates a BINDING
# max_pages constraint.
#
# fonts-liberation is here to honour a font a PROGRAMME states. "Times New
# Roman, 12pt" is one of the commonest published letter rules, and the real
# Microsoft files cannot be in this image: they are Monotype's, licensed to
# Microsoft, and `ttf-mscorefonts-installer` only downloads them under an EULA
# that forbids redistributing the extracted files -- which is exactly what
# WeasyPrint does when it embeds a font in every PDF we produce. Liberation is
# the licensed metric-compatible answer (SIL OFL), and the metrics are the
# point, not the look: measured through this renderer, 600 words at 12pt is
# 2 pages in Liberation Serif and 3 in DejaVu Serif, so a page asking for
# "Times New Roman, max 2 pages" is satisfiable in one and impossible in the
# other. Debian's fontconfig maps the Microsoft names onto Liberation, so
# `font-family: "Times New Roman"` resolves here without our doing anything.
#
# libharfbuzz-subset0 is not required yet: WeasyPrint 70 only warns that a
# future version will need it. Added now because the failure would be invisible
# until it isn't -- a missing shared library does not fail `docker build`, it
# fails when WeasyPrint runs. The web-image CI job renders a PDF for that
# reason, and this is the package that job would otherwise be waiting to catch.
RUN apt-get update && apt-get install --no-install-recommends -y \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
    libharfbuzz-subset0 \
    fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
# Production storage serves only what collectstatic wrote (CLAUDE.md, "Static
# files"). Production settings refuse to import without their environment, so
# the build passes placeholders: collectstatic opens no database, cache or queue.
RUN DJANGO_SECRET_KEY=collectstatic-only DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_ROLE=runtime_web POSTGRES_WEB_USER=collectstatic POSTGRES_WEB_PASSWORD=collectstatic \
    POSTGRES_DB=tehsil POSTGRES_HOST=localhost \
    RESEARCH_QUEUE_URL=unused EUROPASS_QUEUE_URL=unused PORTAL_QUEUE_URL=unused \
    DOCUMENT_QUEUE_URL=unused DOCUMENT_SCAN_QUEUE_URL=unused MAILBOX_QUEUE_URL=unused \
    CACHE_URL=redis://localhost:6379/0 \
    python manage.py collectstatic --noinput
USER app
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]

FROM runtime AS worker
# The research fetch path is vendor-only (Firecrawl/Tavily); there is no
# browser tier here to isolate anymore. See
# docs/superpowers/specs/2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md.
USER app
CMD ["python", "manage.py", "run_research_worker"]

FROM runtime AS portal
# This stage DOES carry credentials: it holds the database password, the LLM
# key and a profile of live portal session cookies, because a fill has to read
# a FieldMap and write an audit trail while it types. What makes that
# acceptable is the renderer sandbox -- see apps/portals/engine.py, which
# refuses to open a session when it would be stripped. That is also why the
# portal service runs on EC2 capacity and not Fargate: Fargate refuses the
# unprivileged user namespaces the sandbox needs (measured, us-east-1,
# 2026-08-26), so Chrome would fail to launch there rather than run unprotected.
#
# playwright: apps/portals/engine.py needs Chrome for Testing, which is the
# revision playwright installs.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# xvfb because extensions do not load in headless_shell, so Chrome runs headful
# and headful Chrome needs a display. xauth is not optional here: xvfb-run
# shells out to it to generate the throwaway MIT-MAGIC-COOKIE and refuses to
# start without it ("xauth command not found"), discovered building this
# stage. fonts-dejavu-core keeps the rendered page close to what a portal
# expects to be filled in. No dbus-x11: the in-container sandbox validation
# (docker build --target portal, then scripts/validate_portal_sandbox.py)
# passed without it, so it is not installed -- add it back only if a real
# portal is found to need D-Bus session services.
RUN apt-get update && apt-get install --no-install-recommends -y \
    xvfb xauth fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN playwright install --with-deps chromium && chmod -R a+rX /ms-playwright
ENV PORTAL_PROFILE_ROOT=/var/lib/tehsil/portal-profiles
RUN mkdir -p /var/lib/tehsil/portal-profiles && chown app /var/lib/tehsil/portal-profiles
USER app
CMD ["xvfb-run", "-a", "--server-args=-screen 0 1280x1024x24", \
     "python", "manage.py", "run_portal_worker"]
