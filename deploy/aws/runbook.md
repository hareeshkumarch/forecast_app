# Runbook

In order. Step 0 is not optional — on a credit-funded account the thing that
hurts is not the hourly rate, it is finding out about it four weeks late.

Region below is `ap-south-1` (Mumbai), which is what `frontend/vercel.json`
already targets (`"regions": ["bom1"]`). Substitute freely; only the AMI id
and the prices change.

```bash
export AWS_REGION=ap-south-1
export BUCKET=forecast-app-web-$(aws sts get-caller-identity --query Account --output text)
```

---

## 0. Put a floor under the spending

Two alarms, because they fail differently: Budgets tells you what you have
spent, and a free-tier alert tells you when a service you thought was free
started charging.

```bash
# Console → Billing → Budgets → Create budget → Zero spend budget is the
# simplest useful one. A $20/month budget with alerts at 50/80/100% is better
# for this plan, since the plan does intend to spend.
```

Also switch on **Billing → Billing preferences → Free tier usage alerts** and
**Alert preferences → Receive AWS Free Tier alerts**. Both are free.

> Cost Explorer and Budgets show yesterday's data, not this minute's. An alarm
> is a smoke detector, not a circuit breaker.

---

## 1. The bucket for the frontend

Private. CloudFront reads it through an Origin Access Control; nothing is
world-readable, and there is no static-website-hosting endpoint involved.

```bash
aws s3api create-bucket \
  --bucket "$BUCKET" \
  --region "$AWS_REGION" \
  --create-bucket-configuration LocationConstraint="$AWS_REGION"

aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

---

## 2. The instance

A security group with **no inbound rules yet** — step 5 adds the only one it
will ever have.

```bash
SG_ID=$(aws ec2 create-security-group \
  --group-name forecast-api \
  --description "Forecast API, CloudFront origin" \
  --query GroupId --output text)
echo "$SG_ID"
```

Launch it. `t4g.small` — 2 vCPU, 2 GB, Graviton — is the size the fit budget
wants, and in Mumbai it costs exactly half what the x86 `t3.small` does. Every
pinned dependency has an aarch64 wheel; see `aws-costs.md` for the check.

```bash
AMI=$(aws ssm get-parameter \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
  --query 'Parameter.Value' --output text)

aws ec2 run-instances \
  --image-id "$AMI" \
  --instance-type t4g.small \
  --security-group-ids "$SG_ID" \
  --user-data file://deploy/aws/user-data.sh \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3","DeleteOnTermination":true,"Encrypted":true}}]' \
  --metadata-options 'HttpTokens=required,HttpEndpoint=enabled' \
  --instance-market-options '{}' \
  --iam-instance-profile '{}' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=forecast-api}]' \
  --query 'Instances[0].InstanceId' --output text
```

Notes on the flags that are not obvious:

- **`HttpTokens=required`** forces IMDSv2. Skipping it leaves the instance
  metadata service reachable by any SSRF in the app, which on a box holding
  encrypted customer credentials is not a theoretical concern.
- **30 GB gp3** because the backend image is ~1.4 GB, Postgres grows, and
  `/storage` accumulates Parquet. The legacy free tier's 30 GB is exactly
  this number, which is not a coincidence.
- **No key pair.** Use Session Manager for shell access — it needs no inbound
  port and no key file, which is what lets the security group stay closed to
  everything except CloudFront. Attach an instance profile with
  `AmazonSSMManagedInstanceCore` in place of the empty `--iam-instance-profile`
  above. Once step 5 runs, this is the *only* way onto the box, so do not
  skip it.

> **A note on the subnet, and on what the VPC origin actually buys you.**
>
> Leave this instance in a **public subnet with an auto-assigned public IPv4**.
> It needs outbound internet — dnf, Docker Hub, PyPI, and the SSM agent — and
> the only way to get that from a private subnet is a NAT gateway, which at
> roughly $33/month costs more than everything else in this plan combined. Do
> not do that.
>
> So the VPC origin does **not** save you the $3.65/month here; that is an
> honest correction to a claim it is easy to make. What it does buy is worth
> having anyway:
>
> - inbound is scoped to **your** distributions via the service-managed
>   security group, rather than to every CloudFront customer;
> - the CloudFront→origin hop runs over the AWS network instead of plaintext
>   across the public internet;
> - the origin address is the instance's **private** DNS name, which does not
>   change on stop/start — which is what makes the "stop it overnight" cost
>   lever safe to use;
> - it does not consume 55 of your 60 security-group rule slots.
>
> A public IP on the instance is not an exposure as long as the security group
> admits only the CloudFront service-managed SG, which is what step 5a does.

First boot builds the backend image on the instance, which takes 10–20
minutes on 2 vCPUs. Watch it:

```bash
aws ssm start-session --target <instance-id>
sudo journalctl -u forecast -f
```

### 2b. Point it at Supabase

`user-data.sh` deliberately leaves `SUPABASE_DB_URL` blank. A connection
string with a password in it must not go into user data — that is readable
from the instance metadata service by anything running on the box, including
an SSRF in the app. Paste it in afterwards instead:

```bash
sudo vi /opt/forecast/.env
```

```ini
SUPABASE_URL=https://YOUR-PROJECT-REF.supabase.co
SUPABASE_DB_URL=postgresql://postgres.YOUR-PROJECT-REF:YOUR-PASSWORD@aws-0-YOUR-REGION.pooler.supabase.com:6543/postgres

# was `localdb` — blank it, so the bundled Postgres stops starting
COMPOSE_PROFILES=
```

```bash
sudo systemctl restart forecast
```

Three things worth knowing about this:

- **The pooled host is the right one to use.** `…pooler.supabase.com:6543` is
  detected, and the platform turns off server-side statement caching for it,
  because pgbouncer in transaction mode cannot carry a prepared statement
  between statements. Both the `:6543` port and the `pooler.supabase` host
  trigger it.
- **`DATABASE_FALLBACK_ENABLED` must stay `false`.** `APP_ENV=production`
  with the fallback on is rejected by `config.py` and the API will not start.
  That is deliberate: with the fallback on, a Supabase outage diverts writes
  to a local node nothing reads, and the first symptom is two sets of numbers
  that disagree.
- **Dropping the local Postgres is worth ~512 MB** on a 2 GB box, which is
  memory the fit stage would rather have. That is what blanking
  `COMPOSE_PROFILES` does.

`SUPABASE_ANON_KEY` has no effect here. The backend connects to Postgres
directly over the DSN and never goes through PostgREST, so there is no anon
key for it to use; `config.py` ignores unknown keys, so setting it is harmless
but does nothing.

Confirm which store it actually chose. `/api/health` reports
`database_target` as `supabase` or `local`, and returns `status: degraded`
whenever Supabase is configured but something else is serving:

```bash
curl -fsS http://<instance-public-dns>/api/health
# want: "database_target":"supabase", "status":"ok"
```

With the fallback off, a wrong password does not degrade — it fails the boot,
so the symptom is a service that never comes up. `journalctl -u forecast -n 50`
has the reason.

---

## 3. The CloudFront distribution

The console is genuinely easier here than the CLI, because the CLI wants the
whole distribution config as one JSON document. Console path:

**CloudFront → Create distribution.**

**Origin 1 — the frontend**
- Origin domain: the S3 bucket (pick it from the dropdown, not the website
  endpoint)
- Origin access: **Origin access control settings**, create a new OAC, then
  use the button CloudFront offers to copy the generated bucket policy into
  the bucket
- Default root object: `index.html`

**Origin 2 — the API.** Two ways to do this. Try (a); fall back to (b).

**(a) VPC origin — preferred.** CloudFront → **VPC origins** → Create, select
the EC2 instance, protocol **HTTP only**, port 80. Provisioning takes up to 15
minutes. Then add it as an origin on the distribution, choosing it from the
VPC-origins list rather than typing a domain name.

- CloudFront creates a service-managed security group named
  `CloudFront-VPCOrigins-Service-SG`. Do not edit it — you *reference* it from
  your own security group in step 5a.
- VPC origins are IPv4-only and cannot front an NLB with a TLS listener.
  Neither matters here.
- **AWS's region list for VPC origins could not be confirmed for
  `ap-south-1`.** If the option is absent in the console, that is your answer;
  use (b).

**(b) Public custom origin — the fallback that works everywhere.**
- Origin domain: the instance's **public DNS name**
  (`ec2-….ap-south-1.compute.amazonaws.com`). CloudFront will not accept a
  bare IP address for a custom origin — it needs a resolvable name.
- Protocol: **HTTP only**, port 80.
- Add a **custom origin header**, e.g. `X-Origin-Verify: <openssl rand -hex 32>`.
  This is not optional if you take this path: the prefix list in step 5b admits
  traffic from *any* CloudFront distribution, including other AWS customers',
  so the header is what identifies yours. Treat the value as a credential and
  rotate it periodically. You will need something in front of the API — or a
  small FastAPI middleware — that rejects requests lacking it.
- Note that this origin's hostname **changes if you ever stop and start the
  instance**, and you will have to update the distribution when it does.

Either way:
- Response timeout: **30** (the default). The SSE keep-alive is 15 s, so the
  stream never idles long enough to trip it.
- Leave **response completion timeout unset** — it caps total response
  duration rather than the gap between packets, and unset means no maximum.

**Default behaviour** → S3 origin
- Viewer protocol policy: Redirect HTTP to HTTPS
- Allowed methods: GET, HEAD
- Cache policy: `CachingOptimized`
- Compress objects automatically: **yes**

**Behaviour `/api/*`** → EC2 origin
- Viewer protocol policy: Redirect HTTP to HTTPS
- Allowed methods: **GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE**
- Cache policy: **`CachingDisabled`**
- Origin request policy: **`AllViewerExceptHostHeader`**
- Compress objects automatically: **no** — gzip at the edge buffers the SSE
  stream, which is the one thing that actually breaks it

Add two more behaviours pointing at the EC2 origin with the same settings,
for `/docs*` and `/openapi.json`, if you want the Swagger UI reachable. Leave
them out if you would rather it were not public.

**Custom error responses** — a static export has no server to rewrite unknown
paths, so map them onto the exported 404 page:
- HTTP 403 → `/404.html`, response code 404
- HTTP 404 → `/404.html`, response code 404

Note the distribution's domain name when it finishes deploying:

```bash
export CF_DOMAIN=dxxxxxxxxxxxxx.cloudfront.net
export CF_ID=EXXXXXXXXXXXXX
```

---

## 4. Publish the frontend

```bash
S3_BUCKET="$BUCKET" CLOUDFRONT_DISTRIBUTION_ID="$CF_ID" ./deploy/aws/deploy-frontend.sh
```

---

## 5. Close the instance to everything except CloudFront

Until now the instance has had no inbound rule at all. Which rule it gets
depends on which origin you built in step 3.

This step matters more than it looks. Without it the instance's public DNS
serves the whole API over plain HTTP to anyone who finds it — including
`POST /api/datasets` and the connector credential endpoints, which store
customer database passwords — and the CloudFront distribution in front of it
is decoration.

### 5a. If you used a VPC origin

Allow port 80 from CloudFront's service-managed security group. This is the
tightest rule available: it admits **your** distributions and nothing else,
not merely "some CloudFront". The group only exists once the VPC origin has
finished provisioning.

```bash
CF_SG=$(aws ec2 describe-security-groups \
  --filters Name=group-name,Values=CloudFront-VPCOrigins-Service-SG \
  --query 'SecurityGroups[0].GroupId' --output text)

aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --ip-permissions "IpProtocol=tcp,FromPort=80,ToPort=80,UserIdGroupPairs=[{GroupId=$CF_SG}]"
```

### 5b. If you used a public custom origin

Allow port 80 from the AWS-managed CloudFront origin-facing prefix list, which
AWS keeps current for you at no cost.

```bash
PL_ID=$(aws ec2 describe-managed-prefix-lists \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text)

aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --ip-permissions "IpProtocol=tcp,FromPort=80,ToPort=80,PrefixListIds=[{PrefixListId=$PL_ID}]"
```

Two things to know about this rule:

- **It consumes 55 of the security group's 60 rule slots.** The prefix list
  carries a weight of 55, so you get essentially one of these per security
  group without requesting a quota increase.
- **It admits every CloudFront distribution, not just yours** — anyone can
  point their own distribution at your origin's public hostname. The secret
  origin header from step 3(b) is what closes that, and it is why that step
  said the header is not optional.

---

## 6. Check it

```bash
curl -fsS "https://$CF_DOMAIN/api/health"     # backend, through the edge
curl -fsSI "https://$CF_DOMAIN/" | head -1    # frontend
curl -fsS "http://<instance-public-dns>/api/health"   # must now FAIL/hang
```

Then open `https://$CF_DOMAIN` and run a forecast on the seeded dataset. The
progress indicator should say it is streaming; if it says it is polling, the
`/api/*` behaviour has compression on or is not using `CachingDisabled`.

---

## Redeploying

**Frontend** — rerun `deploy-frontend.sh`.

**Backend** — on the instance:

```bash
cd /opt/forecast
sudo git fetch --depth 1 origin main && sudo git checkout -f FETCH_HEAD
sudo systemctl restart forecast
```

One thing to know before you do it: without a Celery broker the executor has
no durable queue, so `reap_orphaned_runs` marks every in-flight run
`failed` with "The service restarted before this run finished" on the way
back up. It is a clean, retryable failure rather than a stuck run — but it
is a reason to redeploy when nobody is mid-forecast, and a reason not to run
this on Spot capacity.

---

## Adding a domain later

Nothing above changes. Register the domain, request an ACM certificate **in
`us-east-1`** (CloudFront only reads certificates from that region wherever
the distribution serves), add it and the alternate domain name to the
distribution, and point a Route 53 alias at it. The frontend bundle needs no
rebuild, because it was built with relative API paths.
