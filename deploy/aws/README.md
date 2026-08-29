# Hosting this on AWS

Everything here assumes the two constraints that shaped it: **about $100 of
credit**, and **no domain name and no reserved IP address**. Both are less
limiting than they sound, and the second one turns out to decide the
architecture more than the first.

---

## What is actually being deployed

Three facts about this codebase determine the whole plan, and each was
verified against the code rather than assumed.

**The frontend never talks to the API from a server.** Every page under
`frontend/app/` is a shell; the data arrives in the browser through React
Query against `NEXT_PUBLIC_API_BASE_URL`. There are no route handlers, no
middleware, no `cookies()` or `headers()`, no server actions and no
`next/image`. That means Next.js can emit plain files:

```
$ STATIC_EXPORT=1 NEXT_PUBLIC_API_BASE_URL="" npm run build
✓ Generating static pages (12/12)
$ du -sh out          # 3.1 MB, 94 files, all 12 routes prerendered
```

So the frontend does not need a server at all. That is the single biggest
cost decision available here, and it is free: S3 plus CloudFront serves it
for approximately nothing, forever, rather than for the price of a Node
process running 24/7.

**The backend is CPU-heavy and stateful on disk.** `app/core/budget.py`
gives a run a 60-second total budget with 28 seconds of it in the fit stage,
across a `ProcessPoolExecutor` sized by `FORECAST_WORKERS`. Its dependency
tree — polars, pyarrow, duckdb, pandas, numpy, scipy, scikit-learn,
statsmodels — measures **1.0 GB of site-packages**, and it writes uploads,
Parquet and exports under `STORAGE_ROOT`. This rules out Lambda (cold-starting
a gigabyte of native extensions, no writable persistent disk) and it rules
out anything with a fractional vCPU. It wants **2 vCPU and 2 GB of RAM** and
it wants a disk.

**Redis and Celery are optional and not needed.** `settings.distributed` is
`bool(broker_url)`; leave the broker unset and `dispatch_run` uses an
in-process task instead. The production compose file here therefore drops the
`redis` and `worker` services, which is ~500 MB of RAM back on a small box.

**Postgres is optional too, if Supabase is the store of record.** The compose
file keeps a local Postgres behind a `localdb` profile for the case where it
is not. With `SUPABASE_DB_URL` set there is nothing for it to do —
`DATABASE_FALLBACK_ENABLED` must be `false` in production, so the local node
would never be written to — and leaving it out hands another ~512 MB to the
fitting pool. On a 2 GB box that is the difference between comfortable and
tight. Supabase's pooled host (`…pooler.supabase.com:6543`) is detected, and
server-side statement caching is disabled for it because pgbouncer in
transaction mode cannot carry a prepared statement between statements.

---

## The architecture

One CloudFront distribution, two origins.

```
                     ┌──────────────────────────────────┐
  browser ─── https ─┤  dxxxxxxxx.cloudfront.net        │
                     │  (AWS-issued certificate, free)  │
                     └───────────┬──────────────────────┘
                                 │
              ┌──────────────────┴─────────────────┐
              │                                    │
      default behaviour                  /api/*  /docs  /openapi.json
        CachingOptimized                     CachingDisabled
              │                                    │
      ┌───────▼────────┐                  ┌────────▼──────────────┐
      │  S3 bucket     │                  │  EC2 t4g.small        │
      │  (private, OAC)│                  │  Graviton, 2 vCPU/2 GB│
      │  out/ — 3.1 MB │                  │  ┌──────────────────┐ │
      └────────────────┘                  │  │ backend :80      │ │
                                          │  │ postgres         │ │
                                          │  └──────────────────┘ │
                                          │  EBS gp3: /storage    │
                                          └───────────────────────┘
                                            reached over a CloudFront
                                            VPC origin; inbound open
                                            only to CloudFront's own
                                            security group
```

Three things fall out of putting both origins behind one distribution, and
together they are why this shape wins:

1. **HTTPS without owning a domain.** Every distribution comes with a
   `*.cloudfront.net` name and a valid AWS-issued certificate. No ACM
   validation, no DNS, no cost.
2. **No CORS, ever.** The app and the API are the same origin, so
   `CORS_ORIGINS` can stay empty and no preflight is ever issued. This is why
   `deploy-frontend.sh` builds with `NEXT_PUBLIC_API_BASE_URL=""` — the
   bundle then requests `/api/...` relative to wherever it was loaded from,
   which is also what makes the same build work unchanged if a real domain
   is added later.
3. **The origin needs no public HTTPS of its own.** CloudFront terminates
   TLS at the edge and talks HTTP to the instance, so there is no
   certificate to install or renew on the box.

### Reaching the instance: use a VPC origin

CloudFront **VPC origins** can point directly at an EC2 instance — a load
balancer is not required, and CloudFront reaches the instance on its *private*
address. It is better than the older pattern of a public instance filtered by
security group on every axis except availability:

| | Public custom origin + prefix list | VPC origin |
| --- | --- | --- |
| Restricts to *your* distributions | **No** — the prefix list admits any CloudFront customer, so you also need a secret origin header | Yes, via the service-managed security group |
| CloudFront → origin hop | Plaintext across the public internet | The AWS network |
| Security-group rules consumed | **55 of the 60 allowed** | one SG reference |
| Origin hostname after a stop/start | **Changes** — silently breaks the origin | Private DNS is stable |
| Availability | Everywhere | ~15 min to provision; region list unconfirmed for `ap-south-1` |

The first row is the one most people miss. The prefix list is an *AWS-wide*
list of CloudFront's edge ranges — allowing it means allowing every CloudFront
customer, any of whom can aim a distribution at your origin's public hostname.
Closing that needs a shared-secret origin header on top. A VPC origin's
service-managed security group scopes inbound to your distributions and nothing
else, with no secret to manage or rotate.

The third row is a quota trap: referencing the prefix list consumes 55 of a
security group's 60 rule slots, so you get one per group. The fourth matters if
you intend to stop the instance overnight, which is the largest cost lever
available.

**What a VPC origin does not do here is save the public IPv4 charge.** It is
easy to assume it will — the instance no longer needs to be *reachable* from
the internet. But it still needs to *reach out*, for dnf, Docker Hub, PyPI and
the SSM agent, and doing that from a private subnet means a NAT gateway at
roughly $33/month. So the instance stays in a public subnet with a public
IPv4, pays the $3.65, and the security group keeps everything out. See
`aws-costs.md`.

If VPC origins turn out not to be offered in your region, the fallback path in
`runbook.md` is fully specified, works everywhere, and costs the same.

### Does the progress stream survive CloudFront?

Yes, and the app is built so that it does not matter much either way.

CloudFront forwards `Transfer-Encoding: chunked` responses to the viewer as
they arrive rather than buffering them whole, which is what SSE needs. The
origin **response timeout** — 30 seconds by default — applies both to the wait
for the first byte *and* to the gap between successive packets, and each packet
resets it. `GET /api/forecasts/{id}/events` emits a `: keep-alive` comment
every 15 seconds (`SSE_KEEPALIVE_SECONDS`), comfortably inside that window, so
the stream can run indefinitely.

Three settings on the `/api/*` behaviour are load-bearing:

- **`CachingDisabled`** — not only so responses aren't cached, but because it
  is what disables *request collapsing*. Without it, two viewers opening the
  same SSE URL at the same moment can be merged onto one origin stream.
- **Compression off** — in practice CloudFront won't compress a chunked
  response with no `Content-Length` anyway, but turning it off removes the
  ambiguity.
- **Leave "response completion timeout" unset** — it is the one timeout that
  caps total response duration rather than the gap between packets. Unset, it
  enforces no maximum, which is exactly what a long-lived stream wants.

If it were cut anyway, `hooks/use-forecast-progress.ts` retries with
exponential backoff and then falls back to polling
`GET /api/forecasts/{id}/progress` every 2 seconds. The progress UI degrades;
it does not break.

### Where the progress frames come from

The fitting happens in a `ProcessPoolExecutor` worker, and the browser is
subscribed to a bus in the API process. Those are different processes, so a
worker cannot simply publish to it — `progress_bus` is a module-level object
and each process gets its own copy.

Workers are therefore handed a `multiprocessing.Queue` by the pool's
initializer, and the API process reads it on a dedicated thread that hands
each frame back to the event loop (`ExecutorRegistry.start_relay`). This is
what makes the model search legible: the engine reports before and after each
candidate model, roughly sixteen frames across a backtest, and without the
queue every one of them was written to a bus in the wrong process.

Two consequences worth knowing:

- **The API runs as a single uvicorn process, deliberately.** Progress lives in
  the memory of whichever process is running the forecast. With `--workers`,
  the process holding a viewer's `/events` connection is usually not the one
  running their run, and the stream would fall back to what the database last
  recorded. Concurrency comes from `FORECAST_WORKERS` — the fitting pool —
  which reports back over the queue.
- **Scaling past one API process means Celery + Redis.** In that configuration
  progress travels over the broker instead (`progress_relay.py`), and
  `PROGRESS_CHANNEL_URL` is what turns it on.

### What creating a forecast does not do

`create_run` returns immediately with a `pending` run — the fitting is
dispatched to a background task and watched over SSE. No request blocks for
the length of a forecast, so CloudFront's 30-second origin timeout is never
in tension with the 60-second run budget. This is worth knowing because it is
the usual reason a plan like this fails.

---

## Why not the alternatives

| Option | Why not |
| --- | --- |
| **Lambda + API Gateway** | 1 GB of native wheels cold-starts for many seconds, `/storage` has no durable disk, and the 15-minute ceiling sits awkwardly against background fitting. A container image would fit the size limit; nothing else about it fits. |
| **App Runner** | **Not available.** It closed to new customers on 30 April 2026, so a new account cannot use it at all. It would otherwise have been tempting — free `*.awsapprunner.com` HTTPS, managed — but it has no persistent disk and no EFS support, so `/storage` would have been lost on every deploy regardless. AWS points new users at ECS Express Mode. |
| **ECS Fargate + ALB** | The ALB alone costs more per month than the whole instance plan, and it cannot serve valid public HTTPS without a domain: an HTTPS listener requires a certificate whose name matches, and ACM refuses to issue for `amazonaws.com`. |
| **Amplify Hosting** | Would work for the frontend, but its free allowance is a 12-month offer that accounts created after July 2025 do not get — so it would cost money that S3 + CloudFront does not. And it does nothing for the backend, which is the part that actually costs. |
| **Elastic Beanstalk** | Its `*.elasticbeanstalk.com` name has no usable public certificate — AWS's own docs say HTTPS there requires a custom domain, or a self-signed cert "for development and testing". The mixed-content problem returns. |
| **Vercel (frontend) + AWS (backend)** | The repo already carries `vercel.json`, and Vercel's free tier would host the frontend at no cost. It is a legitimate option — see below, because it is the one being run. |

---

## Running the frontend on Vercel instead

This is the shape currently deployed, and it works: `vercel.json` rewrites
`/api/*`, `/docs` and `/openapi.json` to the backend, so the browser only ever
talks to the Vercel origin over HTTPS and the plain-HTTP hop happens
server-side at Vercel's edge. No mixed content and no CORS, which is why
`NEXT_PUBLIC_API_BASE_URL` is empty there too.

**It still needs the CloudFront distribution.** Not for the frontend — Vercel
does that better and for nothing — but because the alternative destination for
those rewrites is the instance's public hostname, and that has two costs:

- **The instance must accept `:80` from the whole internet.** Vercel's proxy
  addresses are not a published fixed set, so the rule is `0.0.0.0/0` in
  practice. `POST /api/datasets` and the connector-credential endpoints are
  then served over plaintext to anybody who finds the hostname.
  `app/core/ratelimit.py` says as much where it explains why the limiter is a
  control against accident rather than against somebody determined.
- **The hostname changes on stop/start**, which silently breaks the rewrites
  and takes the largest cost lever in `aws-costs.md` with it.

Pointing the rewrites at the distribution fixes both: CloudFront reaches the
instance by its *private* DNS name through the VPC origin, so stop/start is
safe, and the security group can then admit nothing but CloudFront. The
frontend stays on Vercel and `deploy-frontend.sh` is simply not run — the S3
origin sits unused and costs nothing.

```bash
./deploy/aws/finish-cloudfront.sh            # once, creates the distribution
aws cloudfront wait distribution-deployed --id <id>
./deploy/aws/point-vercel-at-cloudfront.sh   # switches vercel.json over
```

The second script prints the remaining steps, including the security-group
revocation that has to come *after* Vercel has redeployed rather than before.

---

## Cost

See `aws-costs.md` for the full breakdown, the region choice, and the levers
that change the number.

---

## Files here

| File | What it is |
| --- | --- |
| `docker-compose.prod.yml` | The instance's compose file: the backend, no frontend, no Redis, no Celery worker, and Postgres only under the `localdb` profile. |
| `env.production.example` | The shape of `/opt/forecast/.env`, with placeholders. The real one holds a database password and never goes into git. |
| `user-data.sh` | EC2 first-boot script. Installs Docker, generates secrets, adds swap, installs a systemd unit, sets up log rotation and image pruning. |
| `deploy-frontend.sh` | Builds the static export and publishes it to S3 with correct cache headers, then invalidates CloudFront. |
| `aws-costs.md` | What it costs per month, how long $100 lasts, and how to make it last longer. |
| `runbook.md` | The click-by-click and CLI setup, in order. |
| `finish-cloudfront.sh` | The distribution, the bucket policy and the security-group rule, split out because a new account cannot create CloudFront resources until AWS verifies it. Idempotent. |
| `point-vercel-at-cloudfront.sh` | Moves `frontend/vercel.json`'s rewrites off the instance's public hostname and onto the distribution, after checking the distribution is Deployed and its `/api/health` answers. |
