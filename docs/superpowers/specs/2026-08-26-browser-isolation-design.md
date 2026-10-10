# Design: the browser does not run where the credentials are

Status: design, not yet implemented. Scope: give the JS-only fetch tier
(`apps/research/discovery.py::render_with_scrapling`) its own ECS task, its own
security group and no application credentials, so that a renderer escape while
retrieving a hostile page cannot reach the database, the Django secret key, or the
worker's task role.

Discharges the binding constraint recorded in `CLAUDE.md` under "When discovery is
wired, the browser does not run in a task holding application credentials."

## Out of scope, deliberately

- **The caller.** Nothing in production calls `retrieve_official_source` today. Who
  decides a lead needs a browser, and what happens to the bytes afterwards, is the
  discovery-wiring work this design must be finished *before*, not part of.
- **Making the Chromium sandbox work.** Settled and measured: Fargate refuses
  `CLONE_NEWUSER` (us-east-1, 2026-08-26, exit 44 under a probe that distinguishes a
  missing binary from a refused syscall). This design exists *because* that door is
  closed. Do not reopen it here.
- **Rate limiting, politeness, or per-tenant quota on browser fetches.** Real, but a
  property of whatever drives discovery, not of the renderer.
- **Anything about the Europass pipeline.** Different browser-shaped problem, already
  solved without a browser.

## The problem

`retrieve_official_source` falls back to a real Chromium for sources that only render
under JavaScript. Chromium launches with `--no-sandbox`, because Playwright pushes that
flag whenever `chromiumSandbox !== true` and the alternative does not exist on Fargate.
So the only thing between a renderer exploit and the rest of the system is the process
boundary — and today there is nothing on the other side of it worth having, because
there is nothing on the other side of it at all.

The browser is a *child of the research worker*. `WorkerTaskDefinition`
(`infra/template.yaml:996`) hands that process:

- `POSTGRES_RUNTIME_PASSWORD` and `DJANGO_SECRET_KEY`, as container secrets — which
  means environment variables, which means `/proc/self/environ`;
- `WorkerTaskRole`, reachable at `169.254.170.2` from anything sharing the task's
  network namespace — SQS consume, and read/write on the evidence bucket;
- `WorkerSecurityGroup`, which `DatabaseSecurityGroup` (`infra/template.yaml:229`)
  explicitly admits on 5432.

Container hardening does not touch any of that. Dropping capabilities and mounting the
root filesystem read-only narrow what an escaped process can *do to the container*; they
do not move the prize out of the container. The prize is one `open()` away.

The fix is therefore not a stronger wall around the browser. It is that the browser runs
somewhere the credentials are not.

## The fact that makes this cheap

**The browser fetch path imports no Django.**

`apps/research/discovery.py` imports `posixpath`, `unicodedata`, stdlib typing and
`.egress`; `apps/research/egress.py` imports stdlib plus `urllib3`. Verified by importing
both with `DJANGO_SETTINGS_MODULE` unset — clean import, `django` absent from
`sys.modules`.

That is the whole design. The browser side does not need `config.settings.production`, so
it never asks for `DJANGO_SECRET_KEY`, and it has no ORM, so it never asks for
`POSTGRES_RUNTIME_PASSWORD`. Those secrets are not *withheld* from the browser task by a
policy someone could later relax — they are structurally absent, because a
`python -m` entrypoint that never imports Django cannot boot into needing them.

The failure mode this avoids is worth naming: had the browser server been written as a
Django management command, the task would have required `DJANGO_SECRET_KEY` to start,
and the entire point of the exercise would have been lost to a convention.

## Architecture

```
research worker task                          browser task
(WorkerTaskRole, DB secret,                   (no task role, no secrets,
 Django secret, worker SG)                     browser SG)
        │                                             │
  retrieve_official_source(url)                       │
        ├── plain fetch (urllib3 + validate_public_url)
        │      └── ok? ──▶ return                     │
        │                                             │
        └── BrowserRequired ──▶ POST /render ─────────▶ LocalEgressProxy (127.0.0.1)
                                                       └── StealthyFetcher ──▶ CONNECT
             ◀───────────── bytes + final URL ─────────      (validate_public_url
                                                              per authority)
                                                                     │
                                                              NAT ──▶ internet
```

`LocalEgressProxy` moves with the browser, because it must: it binds `127.0.0.1:0` in the
process that launches Chromium and validates every `CONNECT` authority. It was never a
containment boundary against a *compromised* browser — a compromised browser ignores its
own proxy setting — and it does not become one here. It is the guard that stops a *page*
from steering an honest browser at `169.254.170.2` or an RFC1918 address, and it keeps
doing exactly that job on the far side.

What changes is that on the far side, `169.254.170.2` has nothing to give.

### Components

| Unit | Responsibility |
|---|---|
| `apps/research/browser_server.py` | `python -m` entrypoint. stdlib `http.server`, one `POST /render`. Owns `LocalEgressProxy` and calls `render_with_scrapling`. Imports no Django. |
| `apps/research/discovery.py` | `retrieve_official_source`'s browser branch becomes an HTTP call to the service instead of an in-process render. `render_with_scrapling` itself is unchanged and moves nowhere. |
| `BrowserSecurityGroup` | New. Ingress only from `WorkerSecurityGroup` on the service port. |
| `BrowserTaskDefinition` / `BrowserService` | New. **No `TaskRoleArn` at all.** Cloud Map registration. |
| `BrowserNamespace` / `BrowserDiscoveryService` | New `AWS::ServiceDiscovery::*` pair giving `browser.tehsil.internal`. |
| `Dockerfile` `browser` stage | Gets `patchright install`; the `worker` stage **loses** it. |

## Decision: a synchronous internal HTTP call, not a queue

The codebase's precedent is queues — `apps/research/queue.py`, `run_research_worker`,
and the Europass pipeline all draw from SQS, and picking a second idiom is normally the
expensive choice. It is the right choice here, and the reason is not preference:

**Retrieval is request/response.** The caller cannot proceed without the bytes. Over SQS
that means a request queue, a reply queue, a correlation id, a worker blocking on a
receive loop for its own reply, and a timeout policy for replies that never arrive —
roughly four new resources and a correlation protocol, all to reimplement `POST`. Over
HTTP it is a `urllib3` request with a timeout, and `urllib3` is already a dependency of
`egress.py`.

The queue's usual payoffs do not apply either. Retry already exists one level up: a
browser fetch that fails raises `SourceBlocked`, the research message is not deleted, and
SQS redelivers the whole unit of work. Buffering is not wanted — a queue in front of the
browser would let a spike accumulate work for a service that can only ever do one render
at a time. And durability is pointless for a result whose only consumer is a caller
currently blocked waiting for it.

The cost of this choice, stated plainly: the research worker holds a connection for the
length of a browser render (up to ~2 minutes, below), and if the browser service is down
the worker discovers it by connection error rather than by queue depth. Both are
acceptable for a path that runs rarely and retries whole.

### The interface

Deliberately one endpoint and no serialization format:

```
POST /render
Content-Type: text/plain
<the url, as bytes>

200 OK
Content-Type: <the fetched content type>
X-Final-Url: <canonicalized final url>
<the body, raw>

502 Bad Gateway            the render failed (maps to BrowserRequired)
403 Forbidden              validate_public_url rejected the target
413 Payload Too Large      body exceeded MAX_RESPONSE_BYTES
```

Raw bytes rather than JSON because a 10 MB body base64s to 13 MB of JSON for no gain, and
because the worker's existing `FetchResult` wants bytes anyway. `X-Final-Url` and the
content type carry the only other two fields `FetchResult` needs; `redirects` is already
`()` on the browser path today.

This is a narrow interface on purpose. It is being designed ahead of its caller, and the
smaller it is, the less of it is wrong when the caller arrives.

## What the browser task holds — and does not

```yaml
BrowserTaskDefinition:
  # No TaskRoleArn. Not an empty role -- absent. With no task role, the ECS
  # credential endpoint at 169.254.170.2 has nothing to hand out, which is a
  # stronger statement than a role with no policies attached (that one is a
  # policy edit away from being wrong).
  ExecutionRoleArn: !GetAtt AppExecutionRole.Arn   # ECS agent's, not the container's
  Cpu: "1024"
  Memory: "2048"
  ContainerDefinitions:
    - Name: browser
      Image: !Ref BrowserImage
      Command: ["python", "-m", "apps.research.browser_server"]
      Environment: []      # deliberately empty -- see below
      # No Secrets block.
      LinuxParameters:
        InitProcessEnabled: true
        Capabilities: {Drop: [ALL]}
```

- **`Environment: []`.** Not even `DJANGO_SETTINGS_MODULE` — the `runtime` Dockerfile
  stage sets it as an `ENV`, and the browser stage should unset it, so that an accidental
  `import django.conf` fails loudly at build time rather than quietly succeeding into a
  settings module that wants secrets. The port is a constant in the module, not a knob.
- **`Capabilities: {Drop: [ALL]}`.** Fargate permits dropping capabilities (it is
  *adding* `CAP_SYS_ADMIN` and custom seccomp profiles that are unavailable). Nothing in
  a headless Chromium fetch needs one. This is the hardening that was correctly refused
  as a *substitute* for isolation and is worth having *alongside* it.
- **`InitProcessEnabled: true`.** Chromium forks liberally and orphans processes; a
  long-running task with no init reaps nothing and accumulates zombies until the task is
  replaced. One line, and the alternative is a slow leak nobody attributes correctly.
- **`readonlyRootFilesystem` is not set, deliberately.** Chromium writes a profile
  directory, `~/.cache`, and `/tmp`, so it needs at least two `tmpfs` mounts to survive a
  read-only root, and "at least" is doing real work in that sentence. It is worth trying
  — as a step in the implementation plan with a canary fetch as its pass criterion, not
  as an assertion in a design document. If it costs more than an hour, drop it: it
  narrows a blast radius that no longer contains anything.
- **`/dev/shm` needs no attention.** Fargate does not support
  `linuxParameters.sharedMemorySize`, which is normally where this bites, but Scrapling
  already passes `--disable-dev-shm-usage`
  (`scrapling/engines/constants.py:60`) and patchright carries it in its own defaults.
  Checked rather than assumed, because this is exactly the class of thing that works on a
  laptop with a 64 MB default and dies under load on Fargate.

**1 vCPU / 2 GB**, against the worker's 0.5/1024: Chromium with `network_idle` on a heavy
page is the memory consumer here, and an OOM-killed task is a fetch failure with a
confusing signature.

## Network: a new security group, and what must never be added to it

`BrowserSecurityGroup` is new, and the temptation to reuse `WorkerSecurityGroup` is the
single most likely way this design gets silently undone. `DatabaseSecurityGroup` admits
`WorkerSecurityGroup` on 5432; a browser task wearing that group has network reach to
Postgres, and the isolation is then one leaked credential away from meaning nothing.

```yaml
BrowserSecurityGroup:
  GroupDescription: >
    Browser tasks: ingress from the research worker only. NEVER add this group
    to DatabaseSecurityGroup ingress -- the browser has no database, and the
    absence of network reach is the second lock behind the absent credential.
  SecurityGroupIngress:
    - {IpProtocol: tcp, FromPort: 8080, ToPort: 8080,
       SourceSecurityGroupId: !Ref WorkerSecurityGroup}
  SecurityGroupEgress:
    - {IpProtocol: -1, CidrIp: 0.0.0.0/0}    # its entire job
```

`EndpointSecurityGroup` gains a matching ingress rule from `BrowserSecurityGroup` on 443,
so image pulls and log delivery take the same path as every other task rather than
crossing the NAT. This grants no access: an interface endpoint without SigV4 credentials
answers nothing, and the task already has unrestricted internet egress to the same public
API. It is reach, not permission.

The task runs in `WorkerPrivateSubnetA`/`B` with `AssignPublicIp: DISABLED`, so its
egress leaves by the same NAT Elastic IP as everything else. That is unchanged behaviour
and is what the "stable egress identity" decision assumes.

### Authentication between worker and browser

None, deliberately. The security group *is* the control: only the research worker can
open the port. Adding a shared secret would mean giving the browser task a secret, which
is the property this entire design exists to remove.

The exposure if that reasoning is wrong is bounded: what an attacker inside the VPC gains
is the ability to make the browser fetch a *public* URL — `validate_public_url` runs on
every `CONNECT` authority, so it cannot be turned into an SSRF probe of the VPC. It is an
open proxy to the public internet from our NAT address, which is a reputation problem
rather than a data problem, and it requires already being inside the VPC.

## Service discovery

`AWS::ServiceDiscovery::PrivateDnsNamespace` (`tehsil.internal`) plus an
`AWS::ServiceDiscovery::Service` registered on the ECS service, giving an A record at
`browser.tehsil.internal` that tracks the task IP. Two resources and a ~$0.50/month
private hosted zone.

Rejected: an internal NLB (per-hour cost for one consumer and one backend), and passing a
task IP through an environment variable (the IP changes on every task replacement).

## What moves in the code

`retrieve_official_source` keeps its shape. Only the fallback branch changes:

```python
def retrieve_official_source(
    url: str,
    *,
    plain_fetch: Callable[..., FetchResult] = fetch_official_source,
    browser_render: Callable[[str], FetchResult] | None = None,
) -> FetchResult:
    ...
    render = browser_render or render_via_browser_service
    return render(canonical_url)
```

The `with LocalEgressProxy() as proxy:` block leaves this function and reappears in
`browser_server.py`, wrapping the handler. `render_with_scrapling` is untouched — it
still takes a proxy and returns a `FetchResult`; it is simply called from a different
task. The seam the tests already use (`browser_render=`) survives, one argument narrower.

`render_via_browser_service` is ~15 lines of `urllib3`: POST, 120-second timeout (the
Scrapling default is 30,000 ms *per operation* and `network_idle=True` can stack several,
so a 60–90 second render is normal and not an error), read at most
`MAX_RESPONSE_BYTES`, rebuild `FetchResult`, and raise `BrowserRequired` on any non-200.

### Two caps the isolated server must enforce that the in-process version did not

Both are pre-existing gaps that only become interesting once the response crosses a task
boundary from a less-trusted process:

1. **Body size.** `render_with_scrapling` returns `page.body` uncapped.
   `LocalEgressProxy._tunnel` caps at `MAX_RESPONSE_BYTES` *per connection*, and a page
   makes many, so nothing today bounds the total. The server truncates or 413s at
   `MAX_RESPONSE_BYTES`, and the worker independently caps what it reads — a cap enforced
   only on the sending side is not a cap, when the sending side is the untrusted one.
2. **Content type.** `fetch_official_source` checks `ALLOWED_CONTENT_TYPES`
   (`egress.py:149`); the browser path does not. It should, on the worker side, where the
   result is trusted.

**The response body is untrusted content and stays untrusted.** It was hostile page
content before this change; it is now hostile page content that arrived from a task we
assume can be compromised. Nothing downstream may treat it as more trustworthy for having
come over our own network — which is already the rule `apps/research/extraction.py`
follows by labelling fetched text as data in its prompts. This design does not relax it.

## Concurrency: one render at a time, and that is the control

`http.server.HTTPServer` is single-threaded. That is not a limitation being tolerated, it
is the serialization: each `StealthyFetcher.fetch` launches a Chromium, and two
concurrent launches in a 2 GB task is an OOM. With `DesiredCount: 1` the platform-wide
ceiling is one browser render at a time, which is the correct order of magnitude for a
fallback tier that exists for the minority of sources that need it.

`# ponytail: single-threaded server, one render at a time. If browser fetches ever
become the common path rather than the fallback, raise DesiredCount and put the tasks
behind an NLB -- not threads in this process.`

## Observability

Two metric filters on `BrowserLogGroup`, two alarms, and the split between them is the
design rather than a detail.

| Signal | Pattern | Threshold | Why |
|---|---|---|---|
| `BrowserRenderFailures` | `"render failed for"` | >3 in 5 min | A render failure is semi-routine: a source is down, a page times out, a site refuses a headless client. Rate, not count. |
| `BrowserCrashes` | `"Traceback (most recent call last)"` | >0 in 5 min | `do_POST` catches `Exception` around both the validation and the render, so an escaped traceback means the *server* broke — the proxy failed to bind, a handler died mid-response. One is a page. |

Merging these into one metric would defeat the purpose. The threshold loose enough for
routine render failures swallows a crash entirely, and the crash is the signal you
actually want at 3am.

Both carry `TreatMissingData: notBreaching`, which matters more here than on the other
services: `BrowserDesiredCount` is 0 until discovery is wired, so "no data" is the normal
state of a service deliberately not running, not a broken alarm.

**Deliberately not alarmed: the 403 path.** A refused target is the SSRF guard firing,
which sounds like it should be loud — but `validate_public_url` also rejects a URL whose
DNS does not resolve, and a dead domain in a discovery lead is ordinary. A threshold-0
alarm here would page on a typo'd hostname. If a real signal is wanted later, it needs a
log line that separates "resolved to a private address" from "did not resolve", which the
server does not currently emit.

**The failure mode every log-pattern alarm has:** reword the log line and the filter goes
quiet, with no error anywhere and a green dashboard. `tests/infra/test_template.py` pins
the filter pattern against the literal in `browser_server.py` for that reason, and a
second test asserts the general rule — no long-running service log group ships without a
filter — so the next service added has to make the decision deliberately rather than
inherit this omission.

## Cost, and shipping ahead of the caller

A permanently-running 1 vCPU / 2 GB Fargate task is roughly $36/month for a code path
with no production caller. So `BrowserDesiredCount` is a template parameter defaulting to
**0**, and the service ships stopped. Nothing calls the browser tier today, so nothing
notices; the discovery-wiring change that adds the first caller sets it to 1 in the same
deploy that makes it necessary.

This is the same discipline the constraint itself came from: the infrastructure is
defined now, so that wiring discovery is a one-line parameter change rather than a
disentangling exercise, but it costs nothing until it earns its keep.

## The image split

The `worker` Dockerfile stage currently runs `patchright install --with-deps chromium`.
Once the browser has its own task, the credential-holding task should not carry a browser
at all — a `browser` stage inherits `runtime` and takes the `patchright install`, and the
`worker` stage drops it. That removes several hundred MB and, more to the point, removes
the ability to launch a browser from the task that holds the database password. A
template parameter `BrowserImage` carries it, following the existing `ProbeImage`
precedent rather than overloading `AppImage`.

## Testing

- `retrieve_official_source` still falls back on `BrowserRequired`, still returns plain
  results untouched, and still honours an injected `browser_render` — the existing tests
  in `tests/research/test_discovery.py` adapt to the one-argument seam.
- `render_via_browser_service` maps 200 → `FetchResult` with the `X-Final-Url` header as
  `final_url`, and maps 403/502/timeout → `BrowserRequired`, against a stdlib
  `http.server` stub.
- The server truncates a body over `MAX_RESPONSE_BYTES` and the worker refuses to read
  past it — asserted from both sides, since the point is that neither side trusts the
  other's cap.
- A template test (following `tests/infra/`'s existing CloudFormation parser) asserts the
  three things a future edit is most likely to break: `BrowserTaskDefinition` has **no**
  `TaskRoleArn` and an empty `Secrets`, `BrowserSecurityGroup` does **not** appear in
  `DatabaseSecurityGroup`'s ingress, and the browser container's `Environment` contains no
  `POSTGRES_*` or `DJANGO_SECRET_KEY` entry. These are the assertions that make the
  design binding rather than advisory.
- Live verification is the existing canary shape: one real fetch of a JS-only source
  through the deployed service, checked for non-trivial content length.

## What this design cannot close

- **`--no-sandbox` remains.** This design accepts a renderer compromise as possible and
  makes it cheap; it does not prevent one. If Fargate ever permits unprivileged user
  namespaces, `chromium_sandbox=True` becomes worth revisiting — and per the note in
  `CLAUDE.md`, re-measure rather than believe the announcement.
- **The NAT address is shared.** A browser task that gets our egress IP blocked by a
  source blocks every other outbound path too, including europa.eu. Unchanged by this
  design, and the reason `solve_cloudflare` stays off.
- **It is designed ahead of its caller.** The interface is one endpoint and three
  headers precisely because some of what is assumed about the caller will be wrong. The
  parts that are hard to change later — no task role, its own security group, no Django
  import — are the parts chosen to be structural rather than configurable.
