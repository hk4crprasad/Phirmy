# Phirmy on Cynerza

Production host: `20.40.52.17`, SSH user `cynerza`. The existing Nginx server
continues to serve `phirmy.com` and the separate contact service.

| Public origin | Destination |
| --- | --- |
| `https://phirmy.com` | Existing MainPage/contact deployment |
| `https://app.phirmy.com` | Next.js, loopback port 13100 |
| `https://app.phirmy.com/backend/…` | API, loopback port 18100; prefix stripped |
| `https://api.phirmy.com` | API, loopback port 18100 |
| `wss://api.phirmy.com/v1/media` | Browser/widget voice socket |

Dashboard cookies and the registered Google, Cal.com and Calendly OAuth callbacks
stay on `app.phirmy.com/backend/…`. Internal Next.js requests use `http://api:8100`.
The web container receives `PUBLIC_API_ORIGIN` for its WebSocket CSP allowlist.
Nginx forwards upgrades and streams without buffering and overwrites forwarding
headers. API trusts only the dedicated Docker bridge gateway, `172.31.240.1`.
Widgets continue to require their configured allowed origins and user-initiated
microphone permission; a hosting site's restrictive Permissions Policy can block
microphone access.

## Private configuration

Server-only files, directory 0700 and files 0600:

- `/etc/phirmy-platform/runtime.env`: application configuration and restricted
  `phirmy_runtime` database login; no migration owner credentials.
- `/etc/phirmy-platform/migration.env`: migration login and stable application key.
- `/etc/phirmy-platform/database.env`: PostgreSQL backup-client environment.
- `/etc/phirmy-platform/backup.env`: only Azure/vector backup configuration.

The root `.env` remains tracked privately by explicit owner choice. CI deliberately
excludes it from the working tree and Docker build context. Runtime credentials are
installed separately over SSH. Updating the private repository's `.env` does **not**
automatically replace the server files: synchronize the relevant entries privately
and deploy again. Never print expanded Compose config; use `config --quiet`.
Never regenerate the stable `APP_SECRET` during deployment or restore.

## CI/CD

`Deploy Phirmy Platform` runs focused offline authentication, media and Sarvam
contracts on a GitHub-hosted runner, then deploys that exact SHA on the Cynerza
runner if it is still main's head. Docs-only and MainPage-only pushes do not deploy
the platform. `Backend and sandbox tests` remains the full suite for pull requests
and manual dispatch; it does not block beta releases. The beta pytest option has
an explicit module allowlist and cannot silently skip sandbox tests in a broader
selection. Public readiness, browser and WebSocket acceptance follow deployment.
Only trusted main-branch code reaches the self-hosted runner; pull requests cannot
deploy.

`deploy/platform.sh` builds locked API/sandbox/web images sequentially, creates a
PostgreSQL archive, stops the old worker, applies additive migrations and runtime
grants, reconciles the real object inventory for legacy workspaces missing their
initial storage state, then waits for every service and `/readyz`. An incomplete
inventory blocks promotion; existing files and usage limits are preserved. It installs the Nginx routes
only after private readiness passes and verifies public HTTPS before promotion.
Release images carry the commit SHA. Deployments restart services and can interrupt
active calls; this initial single-host beta does not provide zero-downtime releases.

Compose is `deploy/compose.production.yaml`, project name `phirmy`. Persistent
volumes hold app data, Redis, Qdrant and its snapshots. Redis and Qdrant have no
published ports. The network-disabled content sandbox has no credentials or app
mounts. Container logs are bounded. Never use `down -v`, global image/volume prune
or destructive database fixtures on this server.

## Operations and rollback

Current and previous release SHAs are in `/opt/phirmy-platform/`. Each successful
release retains its Compose definition under `releases/<sha>/compose.yaml`.
Use the explicit release SHA when running Compose:

```sh
export PHIRMY_RELEASE="$(cat /opt/phirmy-platform/current-release)"
docker compose --env-file /etc/phirmy-platform/runtime.env \
  -f "/opt/phirmy-platform/releases/$PHIRMY_RELEASE/compose.yaml" ps
curl --fail https://api.phirmy.com/readyz
```

For application rollback, select the recorded previous release and run its Compose
definition with `up -d --no-build api worker web content-sandbox`. Additive database
changes remain; never automatically restore a database over newer customer data.
Failed upgrades attempt to restore preceding application images. First deployment
has no prior production release to restore. Confirm readiness after any recovery.

Daily `phirmy-backup.timer` runs at 03:10 UTC with up to five minutes jitter. It
creates a database dump, validates its archive, snapshots vector collections and
uploads them to the **private** Azure container under `platform-backups/`.
Backup credentials exclude the database owner from the uploader. Local backup
archives/logs are private under `/var/backups/phirmy-platform`. Backups are retained;
monitor capacity and establish an owner-approved retention policy as data grows.
The initial PostgreSQL backup was restored into a separate, network-disabled
PostgreSQL container and all 64 original tables were recovered. That disposable
database was removed; production data was never overwritten.

Check `systemctl status phirmy-backup.timer` and the service journal for failures.
These local checks are not an external uptime/paging service. Preserve Azure object
data and the stable application key separately when planning disaster recovery.

Certbot manages a certificate for both app/API hostnames and its renewal timer.
The webroot challenge directory is `/var/www/phirmy-acme`; the renewal deploy hook
validates and reloads Nginx. Keep Cloudflare DNS pointed to this host and use
Full (strict) if enabling its proxy. Do not cache authenticated/API/widget-session
responses. DNS-only is sufficient for this deployment.

## Remaining product acceptance

Deployment health does not prove OAuth consent/provider approval, inbox delivery,
physical microphone behavior, carrier calls or payment processing. Existing calls,
phone purchases and paid activation stay disabled. Application legal/business
configuration still needs accurate owner-reviewed Phirmy information; do not mark
draft policies approved just to hide the remaining work. Use invited beta testers
until these product and operational acceptance items are completed.

## Bot protection and dashboard testing

The owner explicitly disabled CAPTCHA for this beta:
`WIDGET_BOT_CHALLENGE_ENABLED=false` applies in production too. Installation
origin/public-key validation, account and visitor quotas, rate limits and spending
caps remain enforced.

To enable CAPTCHA later, supply real `TURNSTILE_SITE_KEY` and
`TURNSTILE_SECRET_KEY`, set `WIDGET_BOT_CHALLENGE_ENABLED=true` in the private
project/server runtime configuration, and recreate services to load the values.
With the flag enabled, missing keys or invalid proof reject public session creation;
sessions created while disabled must reconnect and pass the check. No test keys
or automatic production override is used.

Authenticated dashboard previews use explicit credentialed requests and require
CSRF, application Origin, verified workspace membership and widget write access.
These previews do not need a public CAPTCHA, but retain widget/session quotas and
workspace spending limits. Public iframe/embed requests do not opt into this mode;
a forged preview header, browser account from another workspace or API key does
not bypass bot protection. The dashboard test tab can therefore work before
Turnstile onboarding, while public distribution follows the owner-controlled CAPTCHA setting.
