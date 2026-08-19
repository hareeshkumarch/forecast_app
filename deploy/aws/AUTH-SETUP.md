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
