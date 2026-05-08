# Sklad Logistics Telegram Mini App

MVP for warehouse logistics workflow in Telegram Mini App:

- create invoices with cargo items
- save data to CSV (test storage)
- apply tariff to selected invoice only
- calculate item totals and invoice total in tenge (`₸`)
- generate PDF in 3 copies only after tariff is set
- assign invoice cargo to wagon (full or partial with remainder invoice)

## Stack

- Python 3.11+
- FastAPI
- ReportLab
- HTML/CSS/JS (mobile-first)

## Local Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open: `http://localhost:8000`

## CSV Tables

Inside `data/`:

- `invoices.csv`
- `invoice_items.csv`
- `wagons.csv`
- `wagon_allocations.csv`

## Vercel Deploy (GitHub)

1. Push this project to GitHub.
2. In Vercel: `Add New Project` -> import your GitHub repository.
3. Framework preset: `Other` (or auto-detected Python/FastAPI).
4. Root directory: project root.
5. Deploy.
6. Copy resulting URL `https://<project>.vercel.app`.
7. In `@BotFather`, set this URL as your Mini App URL.

### Vercel notes

- FastAPI entrypoint is `app/app.py` (already added).
- `vercel.json` includes `static/**` files for the function bundle.
- Vercel Functions filesystem is read-only except `/tmp`; app is configured to write CSV/PDF into `/tmp/sklad`.
- `/tmp` is ephemeral, so data is not persistent between cold starts/redeploys.
