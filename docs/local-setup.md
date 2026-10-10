# Running Elmify on your own computer

Two programs: the **app** (Django, the dashboard, port 8000) and the
**website** (Next.js landing page in `web/`, port 3000). The website's
"Get started", "Log in" and "Book a demo" buttons open the app.

## Once

1. Install Docker Desktop, Git, and uv
   (`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` on Windows).
2. `git clone https://github.com/AyhanAlakbarov/elmify.git` and `cd elmify`.
3. If another project already uses port 5432, change the port line in
   `compose.yaml` to `"5433:5432"` and set `POSTGRES_PORT=5433` (below).

## The app (first window)

```powershell
docker compose up -d postgres
uv sync
$env:DJANGO_DEBUG="true"
# $env:POSTGRES_PORT="5433"   # only if you changed compose.yaml
uv run python manage.py migrate
uv run python scripts/seed_demo.py        # once: demo agency, users and programmes
uv run python manage.py runserver
```

Open http://localhost:8000/accounts/login/ — demo logins, password
`elmify-demo-2026`: `aysel` (student), `counselor`, `owner`, `platform`.
Staff logins ask for a 6-digit code: `seed_demo.py` prints each one's TOTP
secret; add it to an authenticator app.

## The research worker (second window)

A student who signs up and finishes their profile gets programmes only when
the research worker runs. In production that is a queue and a worker; locally:

```powershell
$env:DJANGO_DEBUG="true"
uv run python scripts/local_research.py --watch
```

## The website (third window)

```powershell
cd web
npm install
npm run dev
```

Open http://localhost:3000. When the app lives somewhere else, set
`NEXT_PUBLIC_APP_URL` (for example `https://app.elmify.com`) before building.

## What needs outside services

| Feature | Needs |
|---|---|
| Upload a CV or document | AWS S3 bucket + GuardDuty scan (`EVIDENCE_BUCKET_NAME`, AWS keys) |
| "Write my CV", letters | OpenAI key, and a confirmed CV upload first |
| Connect an inbox | Google / Microsoft OAuth app (`*_OAUTH_CLIENT_ID`, `_SECRET`, `MAILBOX_OAUTH_REDIRECT_BASE`) |
| Real programmes | The research engine with Firecrawl / scrape.do / OpenAI keys |
| Free first cycle for sign-ups | `EARLY_ACCESS_FREE_CYCLE=1` (on by default when `DJANGO_DEBUG=true`) |
