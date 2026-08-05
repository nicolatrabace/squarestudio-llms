# Riepilogo migrazione Productive → Invoice Ninja

Istanza: `https://admin.squarestudio.design`

## Completato

| Entità | Risultato |
|--------|----------|
| Clienti | 35 |
| Fornitori | 20 (+ DEUUX come cliente) |
| Fatture Productive | 32/33 (skip `2026-29` DSK fittizia) |
| Fatture Esch (da PO) | 5, tutte Paid |
| Progetti | ~16 (+ KYIP, Orange Week manuali); esclusi test/internal/TINKR/Design system |
| Spese | 186 attive (dopo dedupe); PDF allegati non presenti nel JSON |
| Task | importati poi **eliminati tutti** (non servono) |
| Budget → note cliente | **15** clienti aggiornati; TINKR skip |
| Quote / deal | **23** (10 Approved vinte, 13 Draft aperte/perse) |
| Prodotti / tariffe | pulizia: **12 attivi** (solo clienti con progetto Active); 29 archiviati; 6 doppioni eliminati |

## Come usi i progetti (promemoria)

1. **Projects → Active** = lavoro corrente; finito → Archive  
2. Prima riga **Public Notes** = `BUDGET: … EUR` (forfait o a ore)  
3. Barra Progress ore = solo per retainer a ore (DSK, jemmic, MaPS)

## Note importanti

- **DSK:** 38.016 € / 384 h = totale **biennale** 2025–2026 (non annuale).  
- **Spese:** allegati PDF assenti nell’export — serve nuovo extract se li vuoi.  
- **Fattura DSK `2026-29`:** ancora in attesa del numero reale.  
- **Fatture aperte Unpaid:** MaPS `2026-28`, jemmic `2026-27`, Michael Jennings `2026-26`.  
- Budget Impulse AI → note su cliente **Seadog Design** (nessun progetto Seadog).  
- Vendor non abbinati su alcune spese: Google, Kate Huynh, Square Studio.

## Script / report

- `import_*.py` — import idempotenti (`custom_value1` / note `productive_id:`)  
- `report_*.json` — esiti per stage  

## Non toccato

Productive.io: **solo lettura** dai JSON locali. Nessuna scrittura su Productive.
