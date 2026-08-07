# Documenso (Square Studio)

Self-hosted document signing at **https://sign.squarestudio.design**.

Runs on the same Hostinger VPS as Invoice Ninja (`admin.squarestudio.design`), behind Traefik + Let’s Encrypt. It is a **separate app** — Documenso cannot be installed inside Invoice Ninja. Native e-sign inside Ninja is [DocuNinja](https://invoiceninja.com/documents/) (Enterprise). For Square Studio we use Documenso Community Edition on a subdomain.

## VPS layout

| Path | Purpose |
|------|---------|
| `/docker/documenso/docker-compose.yml` | Stack (app + Postgres + Mailpit) |
| `/docker/documenso/.env` | Secrets (mode `600`) |
| `/opt/documenso/cert.p12` | Document signing certificate |
| `/root/.documenso-admin-credentials` | Initial admin login |
| `/root/backup-documenso.sh` | DB + cert backup |
| `/root/backups/documenso/` | Backup output |

## Admin

- URL: https://sign.squarestudio.design
- Email: `nicola.trabace@squarestudio.lu` (ADMIN)
- Password: see `/root/.documenso-admin-credentials` on the VPS — change after first login

Signup is limited to `@squarestudio.lu` / `@squarestudio.design`. After your team accounts exist, set `NEXT_PUBLIC_DISABLE_SIGNUP=true` and recreate the container.

## Email (important)

Outbound mail currently goes to **Mailpit** (internal only). Signing invites will not reach clients until real SMTP is configured in `.env`:

```bash
NEXT_PRIVATE_SMTP_HOST=...
NEXT_PRIVATE_SMTP_PORT=587
NEXT_PRIVATE_SMTP_USERNAME=...
NEXT_PRIVATE_SMTP_PASSWORD=...
NEXT_PRIVATE_SMTP_SECURE=true   # or false depending on provider
NEXT_PRIVATE_SMTP_UNSAFE_IGNORE_TLS=false
NEXT_PRIVATE_SMTP_FROM_ADDRESS=sign@squarestudio.design
```

Then:

```bash
cd /docker/documenso && docker compose --env-file .env up -d
```

Peek at trapped mail (debug only):

```bash
docker exec documenso-mailpit wget -qO- http://127.0.0.1:8025/api/v1/messages
```

## Common commands

```bash
cd /docker/documenso
docker compose ps
docker compose logs -f documenso
docker compose pull && docker compose --env-file .env up -d
/root/backup-documenso.sh
```

## Relation to Invoice Ninja

| Need | Use |
|------|-----|
| Sign quotes/invoices inside Ninja portal | DocuNinja (IN Enterprise) |
| Free self-hosted signing (contracts, NDA, SoW) | Documenso at `sign.squarestudio.design` |
| Deep “one UI” merge of Documenso into Ninja | Not supported — keep separate |

This folder mirrors the compose template for disaster recovery; live secrets stay only on the VPS.
