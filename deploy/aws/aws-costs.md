# What it costs, and how long $100 lasts

## First, what "$100 of free tier credit" actually means in 2026

AWS replaced the free tier on **15 July 2025**, and the replacement works
differently enough that planning against the old one will mislead you. If your
account was created after that date — which the $100 credit implies — then:

| | |
| --- | --- |
| **Credit at signup** | $100 |
| **Further credit you can earn** | $100, as five $20 activities |
| **Credits expire** | 12 months after the account is created |
| **The "free plan" lasts** | 6 months, or until credits run out — whichever comes first |
| **The old 12-month allowances** | **Do not apply.** No 750 free EC2 hours, no free 30 GB EBS, no free RDS, no free public IPv4 hours, no free ECR storage. |

There is no "free tier instance" to aim for any more. Every hour of compute is
paid out of credits from the first hour. The question is not *how do I stay
inside the free tier* — it is *how low can I get the monthly burn*.

### Three things that will bite if you don't know them

**1. Earn the other $100 first.** Five activities, $20 each: launch and
terminate an EC2 instance, configure an RDS database, create a Lambda function
with a function URL, submit a prompt in the Bedrock text playground, and create
a Budget with a cost alert. Three of those you are doing anyway as part of this
deployment; the other two take about ten minutes. **Doing all five doubles your
runway.** Track them in the console's "Explore AWS" widget.

**2. When the free plan expires, AWS closes the account.** It does not quietly
convert to pay-as-you-go. Resources and data become inaccessible; AWS holds the
content for 90 days, and you must *upgrade to the paid plan* even to download
it. So **upgrade to the paid plan before the 6-month mark**, well before you
need to. Upgrading forfeits nothing — credits keep applying to your bill until
their 12-month expiry.

**3. Do not put this account into an AWS Organization.** Joining an
Organization, or setting up a Control Tower landing zone, **expires remaining
credits immediately** and makes the account ineligible to earn more.

---

## The bill

Rates below are **`ap-south-1` (Mumbai)**, from the AWS Price List API, EC2/EBS
file published 2026-08-10. Mumbai because `frontend/vercel.json` already
targets `bom1`; if your users are elsewhere, re-check, because the ratio
between instance families is not the same in every region.

### What is free, and stays free

| | Why |
| --- | --- |
| **CloudFront** | The perpetual free tier is **1 TB egress and 10,000,000 requests per month**, and it is a global allowance not tied to a region. The frontend is 3.1 MB; reaching 1 TB would take roughly 300,000 full cold page loads a month. This is not a trial and does not expire. |
| **S3 storage** | 3.1 MB of static export, at $0.025/GB-month. Under a cent. |
| **EBS baseline performance** | Every gp3 volume includes 3,000 IOPS and 125 MiB/s at no extra charge. This workload will not approach either. |
| **Budgets, free-tier alerts** | Free. |

The frontend costs nothing — now or in five years. Only the backend costs
money, which is why the whole plan is shaped around making the backend small.

### What the backend costs

| Option | Spec | Compute | Disk (30 GB gp3) | IPv4 | **Total/mo** |
| --- | --- | --- | --- | --- | --- |
| **`t4g.small`** ✅ | 2 vCPU Graviton, 2 GB | $8.18 | $2.74 | $3.65 | **$14.57** |
| Lightsail $12 plan | 2 vCPU, 2 GB, 60 GB, 3 TB transfer | flat $12.00 | incl. | incl. | $12.00 |
| `t3.small` | 2 vCPU x86, 2 GB | $16.35 | $2.74 | $3.65 | $22.74 |

Add roughly **$0.50–1.50/month** for CloudWatch metrics and log ingestion
beyond the always-free allowance, depending on how chatty `LOG_LEVEL` is.

> **The public IPv4 charge is not avoidable here, and it is worth being
> straight about why.** A CloudFront VPC origin removes the need for the
> instance to be *reachable* from the internet, and it is recommended for that
> reason — but the instance still needs to *reach out* for dnf, Docker Hub,
> PyPI and SSM. From a private subnet that requires a NAT gateway, at about
> $33/month, which is worse than the $3.65 it saves. So the instance keeps a
> public IPv4 for egress, and the security group keeps everything else out.

> **In Mumbai, `t4g.small` costs exactly half of `t3.small`** — $0.0112/hr
> against $0.0224/hr, for the same 2 vCPU and 2 GB. That is a bigger gap than
> in most regions, and it is the single largest saving available here.

### Runway

Assuming you earn the full $200 and upgrade to the paid plan before month six:

| Setup | $/month | $100 lasts | $200 lasts |
| --- | --- | --- | --- |
| **`t4g.small`** | $14.57 | 6.9 months | **the full 12-month credit window, with ~$25 to spare** |
| `t4g.small`, stopped nights and weekends | ~$7.50 | 13.3 months | the full window, ~$110 unspent |
| Lightsail $12 | $12.00 | 8.3 months | the full window, ~$56 to spare |
| `t3.small` | $22.74 | 4.4 months | 8.8 months |

The shape of the answer: **at or under about $16/month, credits cover your
whole first year.** Above that you start paying real money before they expire.
That threshold is the number worth designing to, and the recommended setup
clears it with room to spare.

---

## Graviton works here — verified, not assumed

The usual reason to avoid ARM is a dependency with no wheel that has to
compile. Checked against this project's actual pinned versions on PyPI:

| | |
| --- | --- |
| polars, pyarrow, duckdb, scipy, numpy, scikit-learn, statsmodels, pandas | aarch64 wheels published |
| pymssql, psycopg2-binary, asyncpg, cryptography, fastexcel | aarch64 wheels published |
| reportlab | `py3-none-any` — pure Python, architecture-independent |
| prophet | `manylinux_2_17_aarch64` wheel, 14.7 MB, with the Stan model already compiled inside it |

Every pinned dependency installs from a prebuilt wheel on arm64. No compilation
step, no reason to pay double for x86.

Prophet is the one worth spelling out, because its reputation says otherwise.
The aarch64 wheel carries `prophet/stan_model/prophet_model.bin` — a 2.8 MB
binary built by the wheel's publisher — so Graviton neither compiles Stan at
install time nor on first fit. Installed weight is ~200 MB with cmdstanpy and
matplotlib behind it, against a 30 GB volume.

Its cost here is CPU, not disk or architecture: a Prophet candidate fits a
Stan model per prior combination, and the run's prior search is capped at two
hold-out windows (`PROPHET_TUNING_SPLITS`) for exactly that reason. On a
2-vCPU box it is the slowest candidate in the roster by some margin. If the
28-second fit budget matters more than having it, build the image with
`--build-arg INSTALL_OPTIONAL_MODELS=false` and the platform will run the
other nine models and say plainly that it did.

---

## Sizing: why not something smaller

`app/core/budget.py` gives a run 60 seconds total, 28 of them in the fit stage,
across `FORECAST_WORKERS` processes. Two consequences:

- **2 vCPU is the floor.** Anything with a fractional vCPU — Lightsail
  container services, the smallest Fargate tasks — misses the fit budget by
  construction, not by tuning.
- **2 GB RAM is the floor.** Site-packages alone measures **1.0 GB**, and two
  fitting processes each hold their own arrays on top of the API's footprint.
  A 1 GB instance (`t4g.micro`, at half the price) will OOM-kill the API
  mid-run. `user-data.sh` adds 2 GB of swap for the same reason: the peak of
  fitting eight candidate models is well above the average, and a slow
  forecast is a better failure than a killed API.

---

## The levers, in order of what they save

**1. Stop the instance when nobody is using it.** A portfolio or demo
deployment does not need 8,760 hours a year. Stopped overnight and at weekends
is about 40% of the hours, turning $8.18 of compute into roughly $3.30 and the
IPv4 charge into roughly $1.50 — a stopped instance releases its auto-assigned
address. The disk keeps billing; nothing else does. EventBridge Scheduler runs
the start/stop schedule on a cron for free.

> If you do this, **use a VPC origin.** An instance's public DNS name changes
> on every stop/start, which silently breaks a CloudFront origin pointed at it.
> The private DNS name a VPC origin uses does not change. The alternative is an
> Elastic IP, which bills at the same $0.005/hr whether attached or idle and so
> cancels part of the saving.

**2. Use Graviton.** $8.17/month in Mumbai, for the price of choosing a
different AMI. Verified above.

**3. Use a VPC origin.** It costs nothing extra and, per the note above, it
does not save the IPv4 charge — but it is what makes lever 1 safe, because a
private DNS name survives a stop/start where a public one does not.

**4. Shrink the image.** The backend image is roughly 1.4 GB: ~1.0 GB of
site-packages, ~250 MB of `build-essential` needed only at build time, and
~85 MB of pytest/mypy/ruff with no business in a production image. A
multi-stage build and a split requirements file would cut about a quarter of
it. This buys rebuild and boot speed rather than dollars, since the plan builds
on the instance and never pushes to ECR — which is just as well, because ECR's
500 MB private allowance is a 12-month offer that a new account does not get.

**5. Spot instances — recommended against.** In `ap-south-1` a `t4g.small`
Spot runs about 55% below on-demand, which is real, but the AWS Spot Instance
Advisor puts its interruption frequency in the 5–10% band. Without a Celery
broker there is no durable queue: `reap_orphaned_runs` marks every in-flight
run `failed` when the process restarts. That turns a rare deploy-time event
into a routine one, and it kills every open SSE stream, to save about
$4.50/month.

---

## Guardrails to set on day one

- A **Budget** at $20/month with alerts at 50/80/100%. This is also one of the
  five $20 credit activities, so it pays for itself four times over.
- **Free tier usage alerts**, under Billing preferences.
- A **CloudWatch billing alarm**, because Budgets evaluates on a delay.
- Keep `LOG_LEVEL=INFO`. The compose file already caps container logs at
  3 × 10 MB per service so the disk cannot fill, but CloudWatch ingestion
  beyond 5 GB/month is billed.

None of these stop spending — they tell you about it while it is still small,
which on a credit-funded account is the whole game.

---

## If you want a real domain later

Nothing in the architecture changes; the frontend is already built with
relative API paths, so it needs no rebuild.

- **Cheapest real domain:** Route 53 registers `.click` at about $3/year, plus
  $0.50/month per hosted zone — roughly $9/year all in. Then request an ACM
  certificate **in `us-east-1`** (CloudFront reads certificates only from that
  region, wherever it serves), attach it and the alternate domain name to the
  distribution.
- **Free, if you must:** FreeDNS (afraid.org) is the only free subdomain
  provider here that supports CNAME records, which is what ACM's DNS
  validation requires. DuckDNS and nip.io/sslip.io **cannot** complete ACM
  validation — DuckDNS exposes only A/AAAA/TXT, and nip.io has no record
  database at all. (DuckDNS does work with Let's Encrypt DNS-01 over TXT, if
  you would rather self-manage certificates on the box.)
