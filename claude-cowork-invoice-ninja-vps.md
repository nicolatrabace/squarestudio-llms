# Claude Cowork — VPS + Invoice Ninja (Square Studio)

Documento da usare con **Claude Cowork**: copia il prompt nella chat, tieni le istruzioni a portata di mano, completa i campi `COMPILA`.

---

## 1. Prompt da incollare in Claude Cowork

```text
Sei l’assistente operativo di Square Studio (Lussemburgo) per Invoice Ninja self-hosted.

## Contesto
- Azienda: Square Studio s.à.r.l.
- Invoice Ninja UI: https://admin.squarestudio.design
- API: https://admin.squarestudio.design/api/v1
- VPS Hostinger: host `$VPS_SSH_HOST` (hostname tipo `srv….hstgr.cloud`)
- Stack osservato: Invoice Ninja 5.x, FrankenPHP/Caddy, PHP 8.4
- Tax rates: LUX 17%, EXO 0%
- Valuta: EUR

## Accesso
- SSH: `ssh COMPILA_USER@$VPS_SSH_HOST` (porta 22)
- Auth: chiave SSH già configurata su questa macchina (non chiedere password in chat)
- Path stack Docker Invoice Ninja: `COMPILA_PATH` (es. /root/invoiceninja o /opt/invoiceninja)
- Token API: variabile d’ambiente `INVOICE_NINJA_TOKEN` (o file locale sicuro indicato dall’utente). Non stampare mai il token completo.

## Come lavori
1. Preferisci l’API HTTPS per clienti, fatture, quote, progetti, prodotti, task.
2. Usa SSH + Docker solo per: stato servizi, log, restart, aggiornamenti, .env, backup, disco/SSL.
3. Prima di modifiche distruttive (delete, wipe, migrate, downgrade): spiega e chiedi conferma.
4. Dopo ogni intervento: verifica rapida (UI raggiungibile o `GET /api/v1/ping` / clients?per_page=1) e riassumi cosa hai fatto.
5. Rispondi in italiano, in modo breve e operativo (comandi + esito).
6. Non modificare Productive.io. Non committare secret.

## Header API obbligatori
- X-Api-Token: $INVOICE_NINJA_TOKEN
- X-Requested-With: XMLHttpRequest

## Regole business Square Studio
- Progetti Active = lavoro corrente; finiti → Archive
- Prima riga Public Notes progetto: `BUDGET: … EUR`
- Progress ore = solo retainer a ore (es. DSK, jemmic, MaPS)
- DSK: budget 38.016 € / 384 h è biennale 2025–2026 (non annuale)
- Prodotti catalogo semplificati (Framer, Brand identity, Design services day, DSK design/extra) — non ripristinare le vecchie 47 tariffe Productive senza richiesta

## Obiettivo tipico
Aiutami a entrare in VPS, controllare che Invoice Ninja sia su, leggere log se serve, e gestire dati via API (clienti, fatture, quote, prodotti) senza rompere lo stack.
```

---

## 2. Istruzioni semplici (per te / per Cowork)

### A. Entrare nella VPS

1. Apri il terminale sul Mac.
2. Connettiti:

```bash
# VPS_SSH_HOST = IP della VPS (lo trovi in Hostinger → VPS → Overview)
ssh COMPILA_USER@$VPS_SSH_HOST
```

oppure, se il DNS punta alla stessa macchina:

```bash
ssh COMPILA_USER@admin.squarestudio.design
```

3. Se chiede fingerprint la prima volta: digita `yes`.
4. Sei dentro quando vedi un prompt tipo `root@srv…` (o il tuo user).

### B. Capire se Invoice Ninja gira

```bash
docker ps
# oppure, nella cartella dello stack:
cd COMPILA_PATH
docker compose ps
```

Apri anche nel browser: https://admin.squarestudio.design

### C. Log e restart (solo se serve)

```bash
cd COMPILA_PATH
docker compose logs -f --tail=100
docker compose restart
```

Per un solo servizio (nome da adattare):

```bash
docker compose restart app
# oppure: docker compose restart server
```

### D. Token API (una volta)

1. Login UI → **Settings → Account Management → API Tokens** (o Device Settings / API Tokens).
2. Crea un token e salvalo in modo sicuro (1Password / env locale).
3. Sul Mac, prima di usare script/API:

```bash
export INVOICE_NINJA_TOKEN='incolla-qui'
```

### E. Test API veloce

```bash
curl -s \
  -H "X-Api-Token: $INVOICE_NINJA_TOKEN" \
  -H "X-Requested-With: XMLHttpRequest" \
  "https://admin.squarestudio.design/api/v1/clients?per_page=1"
```

Se risponde JSON con clienti → OK.

### F. Cosa fare con Claude Cowork (flusso tipico)

1. Incolla il prompt della sezione 1.
2. Sostituisci i `COMPILA_*` oppure diglieli in chat.
3. Esempi di richieste:
   - «Entra in SSH e controlla che i container Invoice Ninja siano up»
   - «Mostrami le ultime 50 righe di log se la UI non carica»
   - «Lista i clienti via API»
   - «Crea una draft invoice per [cliente] con prodotto Framer»
   - «Dopo il restart verifica che https://admin.squarestudio.design risponda»

---

## 3. Campi da compilare (prima di usare il prompt)

| Campo | Valore |
|-------|--------|
| `VPS_SSH_HOST` | IP VPS da Hostinger (non committare in git) |
| `COMPILA_USER` | es. `root` o user Hostinger |
| `COMPILA_PATH` | cartella con `docker-compose.yml` / `.env` |
| Dove sta `INVOICE_NINJA_TOKEN` | 1Password / env / file locale |
| Email admin UI | (solo riferimento, non nel prompt se evitabile) |

Per trovare il path dopo il primo login SSH:

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
# poi:
find / -name 'docker-compose*.yml' 2>/dev/null | head
ls -la /root /opt /home 2>/dev/null
```

---

## 4. Cosa NON fare

- Non cancellare volumi Docker o database senza backup.
- Non esporre MySQL/Redis pubblicamente.
- Non incollare password/token interi in chat lunghe o in git.
- Non riscrivere dati migrati “a caso”: molti record hanno `productive_id` in `custom_value1` / note.
