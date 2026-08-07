# Sync Productive ↔ admin (Invoice Ninja)

Istanza: https://admin.squarestudio.design  
API: `https://admin.squarestudio.design/api/v1`  
Header: `X-Api-Token` + `X-Requested-With: XMLHttpRequest`

Finché usi entrambi i tool: **Productive resta la fonte operativa del giorno**; **admin** è CRM + progetti + quote + fatture. Ogni nuovo cliente/deal su Productive va rispecchiato qui (o viceversa) con lo stesso modello.

---

## Mappa concetti

| In Productive | In admin (Invoice Ninja) | Note Square Studio |
|---|---|---|
| Company / client | **Client** | CRM |
| Project + budget | **Project** (Active) | Prima riga Public Notes: `BUDGET: … EUR` |
| Retainer a ore | Project con `budgeted_hours` + `task_rate` | Progress ore = solo questo caso (DSK, jemmic, MaPS) |
| Retainer / pacchetto forfait | Project con `budgeted_amount`, ore = 0 | Come KYIP, CMB, TP Quants, **Keetus** |
| Deal aperto / negoziazione | **Quote Draft** | Non mettere negoziazioni come progetto Active “pieno” |
| Deal vinto | Quote Approved + aggiorna Project/BUDGET | Poi fattura |
| Mese concluso / stop | Archive project **oppure** nota STOP | Active = solo lavoro corrente |

Invoice Ninja **non ha** un modulo budget Productive-like: il totale in euro si legge dalla riga `BUDGET:` nelle Public Notes (e da `budgeted_amount` via API).

---

## Caso Keetus (esempio reale, ago 2026)

Situazione:

- Nuovo cliente solo su Productive → va portato anche su admin
- **Agosto**: retainer forfait **4.000 EUR** (singolo mese confermato)
- **Settembre**: STOP
- **Ottobre+**: negoziazione verso **6.000 EUR/mese** (retainer, non ancora firmato)

### Cosa è stato creato su admin

1. **Client** `Keetus` — note private con timeline budget  
2. **Project** `Keetus` (Active) — `budgeted_amount = 4000`, ore 0, Public Notes `BUDGET: 4.000,00 EUR — forfait`  
3. **Quote Draft** `0024` — 6.000 EUR (pipeline negoziazione ottobre+)

Link utili (dopo create):

- Client: `https://admin.squarestudio.design/#/clients/l4zbqj2dpr`
- Project: `https://admin.squarestudio.design/#/projects/xYRdG7dDzO`
- Quote: `https://admin.squarestudio.design/#/quotes/z3YaOpbxql`

Script idempotente: `ops/keetus/add_keetus.py`  
Report: `ops/keetus/report_keetus_create.json`

```bash
export INVOICE_NINJA_TOKEN='…'   # Settings → API Tokens
python3 ops/keetus/add_keetus.py
```

### Come lo gestisci mese per mese

| Quando | Azione su admin |
|---|---|
| Agosto (ora) | Project Active a 4k. Quando fatturi: **nuova Invoice** con riga flat 4.000 (prodotto tipo `Framer website` / design services), **non** “Invoice Project” da timer |
| Fine agosto / settembre | Nessuna fattura. Lascia nota STOP; se non lavori più, **Archive** il project (o tienilo Active solo se serve come contenitore fino a ottobre) |
| Negoziazione ottobre | Lavora sulla **Quote Draft 6k**; aggiorna importo se chiudi a un altro numero |
| Se chiudi a 6k/mese | Approve quote → aggiorna Public Notes a `BUDGET: 6.000,00 EUR — forfait` e `budgeted_amount` → emetti fattura del mese |
| Se non chiude | Quote resta Draft (o la segni persa nelle private notes); Archive project se non c’è più lavoro |

---

## Checklist sync (copia per i prossimi clienti)

1. Esiste già il **Client** su admin? Se no → crealo (valuta, contatti se li hai).  
2. C’è lavoro **confermato questo mese**? → **Project Active** + riga `BUDGET:`.  
   - Forfait → `budgeted_amount`, ore 0  
   - A ore → `budgeted_hours` + `task_rate`  
3. C’è solo una **negoziazione / mese futuro**? → **Quote Draft**, non gonfiare il budget del project oltre il confermato.  
4. Mesi “STOP” → nota esplicita; niente ricorrenza automatica.  
5. Fattura forfait → riga invoice con prezzo impostato a mano.  
6. Non scrivere su Productive da script admin (solo lettura / sync manuale finché non fai lo switch).

---

## API minima (senza script)

```bash
export INVOICE_NINJA_TOKEN='…'
API=https://admin.squarestudio.design/api/v1
H=(-H "X-Api-Token: $INVOICE_NINJA_TOKEN" -H "X-Requested-With: XMLHttpRequest" \
   -H "Content-Type: application/json" -H "Accept: application/json")

# Client
curl -sS "${H[@]}" -X POST "$API/clients" -d '{"name":"Keetus","settings":{"currency_id":"3"},"contacts":[{"is_primary":true,"send_email":false}]}'

# Project forfait
curl -sS "${H[@]}" -X POST "$API/projects" -d '{"name":"Keetus","client_id":"…","budgeted_amount":4000,"budgeted_hours":0,"task_rate":0,"public_notes":"BUDGET: 4.000,00 EUR — forfait"}'

# Quote negoziazione
curl -sS "${H[@]}" -X POST "$API/quotes" -d '{"client_id":"…","status_id":"1","line_items":[{"notes":"Retainer Ott+","cost":6000,"quantity":1,"tax_name1":"EXO","tax_rate1":0,"type_id":"1"}]}'
```

---

## Regole fisse (non dimenticare)

- **Projects → Active** = lavoro corrente; finito → Archive  
- Prima riga Public Notes progetto = totale budget in EUR  
- Progress ore UI = solo retainer a ore  
- Tax tipiche: `LUX` 17%, `EXO` 0% (usata su Keetus quote in attesa di conferma paese/VAT cliente)  
- Token API: solo env / password manager — mai in git
