# Turning on Google sign-in

Auth ships **off**. `AUTH_ENABLED` defaults to `false`, so deploying this
changes nothing until the steps below are done. That is deliberate: the API
cannot verify a token before a Supabase project is configured to issue one,
so a default of `true` would answer 401 to every request the moment it shipped.

## 1. Supabase

Dashboard → **Authentication → Providers → Google**:

1. Create an OAuth client in Google Cloud Console (*APIs & Services →
   Credentials → OAuth client ID → Web application*).
2. Add Supabase's callback as an authorised redirect URI. Supabase shows the
   exact URL on the provider page — it is
   `https://<project-ref>.supabase.co/auth/v1/callback`.
3. Paste the client ID and secret into Supabase, and enable the provider.

Then **Authentication → URL Configuration**: add the Vercel site URL, and
`https://<your-vercel-domain>/dashboard` as a redirect URL. Sign-in fails with
a redirect error if this is missed.

## 2. Vercel

Project → Settings → Environment Variables:

| Name | Value |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | the project's **anon / publishable** key |

The anon key is designed to be public and ships in the browser bundle. The
**service_role** key must never appear here — it bypasses every access rule
Supabase has.

Redeploy for the variables to take effect.

## 3. EC2

In the backend environment (`deploy/aws/.env.production` or wherever the
compose file reads from):

```
AUTH_ENABLED=true
SUPABASE_URL=https://<project-ref>.supabase.co
# Only if the project signs with HS256. Newer projects publish a key set and
# need nothing here — the token's own header says which is in use.
SUPABASE_JWT_SECRET=<project JWT secret>
```

Optional, and worth setting:

```
# Only these domains may sign in. Empty means any Google account at all.
AUTH_ALLOWED_EMAIL_DOMAINS=yourcompany.com
# Individual addresses admitted whatever the domain rule says.
AUTH_ALLOWLIST=contractor@example.com
```

Then redeploy: `sudo /opt/forecast/deploy/aws/update-backend.sh`

## 4. Prove it, in this order

```bash
# Still open, and must stay open — the redeploy script polls it
curl -fsS http://<host>/api/health

# With AUTH_ENABLED=false: 200. With it true: 401.
curl -s -o /dev/null -w '%{http_code}\n' http://<host>/api/datasets

# With a real token from the browser (Application → Local Storage → the
# supabase auth key → access_token)
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer <token>" http://<host>/api/datasets
```

Flip `AUTH_ENABLED` **after** sign-in is proven to work in the browser, not
before. The order matters: turn it on first and a misconfigured redirect locks
everybody out of a working deployment with no way back in but a shell on the box.

## What is not done yet

The origin is still plain HTTP and publicly reachable. Until CloudFront is in
front of it, tokens cross the internet in clear text and the box answers anyone
who knows its hostname. Auth is worth having before that lands, but it is not
a substitute for it.

---

# Approving people

Anyone can sign in with Google. Nobody gets in until an administrator says so.

A new account lands as `pending`, an email goes to `AUTH_ADMIN_EMAILS` with an
**Approve** and a **Reject** link, and until one is clicked that person sees a
"waiting for approval" screen rather than the app. The API refuses their
requests with 403 for the same reason, so the wait is not something the browser
is politely observing.

The links carry their own authority — signed with `CREDENTIAL_SECRET_KEY`, they
name one account and one decision and expire after
`AUTH_APPROVAL_LINK_TTL_HOURS` (a week by default). No session is needed to use
one, which is the point: approving from a phone should not mean signing in
first.

```
AUTH_ADMIN_EMAILS=you@gmail.com
AUTH_REQUIRE_APPROVAL=true
PUBLIC_API_BASE_URL=https://<the API's public address>
```

`PUBLIC_API_BASE_URL` is where the links point. Get it wrong and the mail
arrives with links that go nowhere.

Administrators are approved on sight — otherwise the first one would be waiting
on themselves.

## Sending the mail, for nothing

Plain SMTP, so any of these work without a code change:

| | Free allowance | Notes |
| --- | --- | --- |
| **Gmail** | free | Needs 2-factor on the account, then an [App Password](https://myaccount.google.com/apppasswords). `smtp.gmail.com:587`. Simplest if the mail is going to your own inbox. |
| **Brevo** | 300/day | Real sending domain, better deliverability |
| **Resend** | 3,000/month | Needs a verified domain for anything but test sends |

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=<the 16-character app password, not your Google password>
SMTP_FROM=you@gmail.com
SMTP_STARTTLS=true
```

If mail is not configured, or sending fails, the request is still recorded —
`GET /api/auth/pending` lists everyone waiting, for administrators. A mail
server being down delays access; it does not lose the request.

---

# Secrets from Infisical

Set these four and every other setting is read from Infisical instead of the
environment:

```
INFISICAL_CLIENT_ID=<machine identity client id>
INFISICAL_CLIENT_SECRET=<machine identity client secret>
INFISICAL_PROJECT_ID=<project id>
INFISICAL_ENVIRONMENT=prod        # optional, defaults to prod
INFISICAL_SECRET_PATH=/           # optional, defaults to /
INFISICAL_HOST=https://app.infisical.com   # optional, or your own instance
```

These four stay in the environment and have to: a secret manager cannot hold
the credential used to reach it. Create the machine identity under
**Access Control → Identities**, give it *Universal Auth*, and grant it read
access to the project.

Values from Infisical **override** anything already in the environment. It has
been made the source of truth, and a leftover variable on the box quietly
winning over the thing everyone is editing is the failure that costs an
afternoon.

Fetched once, at startup, before any setting is read — so a change in Infisical
needs a restart, the same as an environment variable did.

`GET /api/health` reports `"secrets_source": "infisical"` or `"environment"`,
so which one is in force is answerable without a shell.

**If Infisical is unreachable** the app still starts, on whatever the
environment holds, and logs a warning. That is deliberate: a secret manager
being briefly down should not take a working deployment with it. The existing
production checks still refuse to start with a default credential key, so this
cannot silently degrade into an insecure install.

## Cost

Infisical Cloud has a free tier that covers this. Self-hosting is free
software but needs somewhere to run, which is not free — on the current
budget, use the cloud free tier.
