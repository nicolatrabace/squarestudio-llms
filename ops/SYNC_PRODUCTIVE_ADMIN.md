# Sync Productive ↔ admin (Invoice Ninja)

Istanza: https://admin.squarestudio.design  
API: `https://admin.squarestudio.design/api/v1`  
Header: `X-Api-Token` + `X-Requested-With: XMLHttpRequest`

**Regola:** usa i campi delle tab Ninja. Le Notes non sono un database.

---

## Dove va ogni informazione

| Info | Tab / campo Ninja | Non fare |
|------|-------------------|----------|
| Cliente legale / P.IVA | Client → Details (`name`, `vat_number`) | Mettere il brand come client se non ha P.IVA |
| Brand (es. Keetus) | Client + Project → **Custom Fields → Brand** | Romanzo in Notes |
| Budget euro forfait | Project → **Overview → Budgeted Amount** + 1 riga Public Notes `BUDGET: … EUR — forfait` | Timeline mesi nelle Notes |
| Cap ore / tariffa | Overview → Budgeted Hours + Task Rate | — |
| Fine mese / deadline | Overview → **Due Date** | “agosto confermato” solo come testo |
| Tipo engagement | Custom Fields → Type / Engagement | — |
| STOP / mese status | Custom Fields → Month status | Paragrafi in Private Notes |
| Negoziazione futura | **Quote** (Draft), con `project_id` + Due Date | Gonfiare il budget del project |
| Productive ID | Custom Fields → Productive ID (`custom_value1`) | — |

Label custom fields (company): Productive ID / Brand / Engagement|Type / Month status|Pipeline.

---

## Caso Shonga / Keetus

| Pezzo | Valore |
|-------|--------|
| Client | **Shonga** — Brand=`Keetus`, Engagement=`Retainer` |
| Project | **Keetus** — Budgeted Amount **4000**, Hours **0**, Due **2026-08-31**, Type=`Retainer forfait`, Month status=`2026-08 confirmed; 2026-09 STOP` |
| Public Notes progetto | solo `BUDGET: 4.000,00 EUR — forfait` |
| Quote Draft 0024 | 6000 €, project linked, Due **2026-10-31**, Pipeline=`Oct+ negotiation` |
| Invoice Draft **2026-29** | 4000 € agosto, collegata al project, data 31/08/2026 |

> Numerazione: il contatore interno Ninja è a `0002` (padding 4) mentre le fatture reali usano `2026-XX`.
> Ogni fattura nuova va rinumerata a mano (o si sistema il pattern nei settings).
> `2026-29` era il numero provvisorio annotato per la DSK mai importata: se serve a DSK, rinumerare questa.

Link edit:

- Client: https://admin.squarestudio.design/#/clients/l4zbqj2dpr/edit  
- Project: https://admin.squarestudio.design/#/projects/xYRdG7dDzO/edit  
- Quote: https://admin.squarestudio.design/#/quotes/z3YaOpbxql/edit  

Script: `ops/keetus/add_keetus.py`

```bash
export INVOICE_NINJA_TOKEN='…'
python3 ops/keetus/add_keetus.py
```

### Mese per mese

1. **Agosto** — Project Active 4k, Due 31/08. Fattura Draft `2026-29` già pronta: controlla e manda.  
2. **Settembre** — Month status già STOP; Archive project se non serve.  
3. **Ottobre+** — Quote Draft 6k; se vinci → Approve, aggiorna Budgeted Amount + `BUDGET:` + Due Date.

---

## Checklist sync

1. Client corretto (anagrafica / P.IVA), brand in **Custom Fields**  
2. Project Active solo per lavoro confermato → Overview (amount/hours/due/rate)  
3. Negoziazione → Quote Draft collegata al project  
4. Notes = una riga `BUDGET:` (forfait) o dettaglio ore; niente timeline  
5. Non scrivere su Productive da script admin
