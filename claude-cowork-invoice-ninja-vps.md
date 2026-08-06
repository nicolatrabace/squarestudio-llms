# Claude Cowork — VPS + Invoice Ninja (Square Studio)

Documento da usare con **Claude Cowork**: copia il prompt nella chat.

Valori verificati sulla VPS (ago 2026).

---

## Risposte da dare a Cowork (copia-incolla)

```text
1. Utente SSH: root
2. Host: puoi usare admin.squarestudio.design (punta alla VPS). L’IP Hostinger è in Hostinger → VPS → Overview (e come secret Cursor VPS_SSH_HOST). Hostname: srv1395735.
3. Cartella docker-compose Invoice Ninja: /root/dockerfiles/octane
   File: /root/dockerfiles/octane/docker-compose.yml
   .env stack: /root/dockerfiles/octane/.env
   Backup script: /root/backup-invoiceninja.sh → /root/backups/invoiceninja
4. Token API: NON è nel .env Docker. Si crea/copia da Invoice Ninja UI → Settings → API Tokens.
   Uso operativo: variabile d’ambiente INVOICE_NINJA_TOKEN (sul Mac o in Cowork).
   Non stampare il token. Tenere in password manager (1Password).
```

---

## 1. Prompt da incollare in Claude Cowork

```text
Sei l’assistente operativo di Square Studio (Lussemburgo) per Invoice Ninja self-hosted.

## Contesto
- Azienda: Square Studio s.à.r.l.
- Invoice Ninja UI: https://admin.squarestudio.design
- API: https://admin.squarestudio.design/api/v1
- VPS Hostinger: SSH come root su admin.squarestudio.design (o IP da Hostinger / $VPS_SSH_HOST)
- Hostname tipico: srv1395735
- Stack Docker Compose project: octane
- Path: /root/dockerfiles/octane
- Container: octane-app-1, octane-app-worker-*, octane-app-scheduler-1, octane-mysql-1, octane-redis-1
- Traefik fa da reverse proxy (container traefik)
- Tax rates: LUX 17%, EXO 0%
- Valuta: EUR

## Accesso
- SSH: `ssh root@admin.squarestudio.design` (porta 22) — chiave SSH già configurata
- Compose: `cd /root/dockerfiles/octane && docker compose …`
- Backup: `/root/backup-invoiceninja.sh` → `/root/backups/invoiceninja`
- Token API: env `INVOICE_NINJA_TOKEN` (creato in UI Settings → API Tokens). Non è nel `.env` Docker. Non stampare mai il token completo.

## Come lavori
1. Preferisci l’API HTTPS per clienti, fatture, quote, progetti, prodotti, task.
2. Usa SSH + Docker solo per: stato servizi, log, restart, aggiornamenti, .env, backup, disco/SSL.
3. Prima di modifiche distruttive (delete, wipe, migrate, downgrade): spiega e chiedi conferma.
4. Dopo ogni intervento: verifica rapida (UI raggiungibile o clients?per_page=1) e riassumi.
5. Rispondi in italiano, breve e operativo (comandi + esito).
6. Non modificare Productive.io. Non committare secret.

## Header API obbligatori
- X-Api-Token: $INVOICE_NINJA_TOKEN
- X-Requested-With: XMLHttpRequest

## Comandi infra utili
- Stato: `cd /root/dockerfiles/octane && docker compose ps`
- Log: `cd /root/dockerfiles/octane && docker compose logs -f --tail=100`
- Restart: `cd /root/dockerfiles/octane && docker compose restart`
- Backup: `/root/backup-invoiceninja.sh`

## Regole business Square Studio
- Progetti Active = lavoro corrente; finiti → Archive
- Prima riga Public Notes progetto: `BUDGET: … EUR`
- Progress ore = solo retainer a ore (es. DSK, jemmic, MaPS)
- DSK: budget 38.016 € / 384 h è biennale 2025–2026 (non annuale)
- Prodotti catalogo semplificati (Framer, Brand identity, Design services day, DSK design/extra) — non ripristinare le vecchie 47 tariffe Productive senza richiesta

## Obiettivo tipico
Entra in VPS, controlla che Invoice Ninja sia up, leggi log se serve, gestisci dati via API senza rompere lo stack.
```

---

## 2. Istruzioni semplici

### A. Entrare nella VPS

```bash
ssh root@admin.squarestudio.design
# oppure: ssh root@$VPS_SSH_HOST
```

### B. Stato Invoice Ninja

```bash
cd /root/dockerfiles/octane
docker compose ps
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'octane|traefik'
```

Browser: https://admin.squarestudio.design

### C. Log / restart

```bash
cd /root/dockerfiles/octane
docker compose logs -f --tail=100
docker compose restart
```

### D. Token API

1. UI → **Settings → API Tokens** → crea/copia token  
2. Sul Mac:

```bash
export INVOICE_NINJA_TOKEN='…'
```

### E. Test API

```bash
curl -s \
  -H "X-Api-Token: $INVOICE_NINJA_TOKEN" \
  -H "X-Requested-With: XMLHttpRequest" \
  "https://admin.squarestudio.design/api/v1/clients?per_page=1"
```

---

## 3. Riferimenti stack

| Voce | Valore |
|------|--------|
| SSH user | `root` |
| Host SSH | `admin.squarestudio.design` (o IP Hostinger) |
| Compose dir | `/root/dockerfiles/octane` |
| Compose file | `/root/dockerfiles/octane/docker-compose.yml` |
| App .env | `/root/dockerfiles/octane/.env` (`APP_URL=https://admin.squarestudio.design`) |
| DB | MySQL container `octane-mysql-1`, db `ninja` |
| Backup | `/root/backup-invoiceninja.sh` |
| Migrazione locale VPS | `/root/Migrazione_Productive_InvoiceNinja` |
| API token | UI Invoice Ninja → env `INVOICE_NINJA_TOKEN` (non nel `.env` Docker) |

---

## 4. Cosa NON fare

- Non cancellare volumi Docker o database senza backup.
- Non esporre MySQL/Redis pubblicamente.
- Non incollare password/token interi in chat lunghe o in git.
- Non riscrivere dati migrati a caso: molti record hanno `productive_id` in `custom_value1` / note.
