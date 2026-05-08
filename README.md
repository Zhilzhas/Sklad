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

## Koyeb Deploy (GitHub)

1. Push this project to GitHub.
2. In Koyeb: `Create Web Service` -> `GitHub`.
3. Select repository and branch.
4. Builder: `Buildpack`.
5. Run command: leave default from `Procfile` (already included), or set:
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6. Port: `8000` (HTTP).
7. Deploy and copy resulting `https://...koyeb.app` URL.
8. In `@BotFather`, set this URL as your Mini App URL.

## Important for Free Tier

Koyeb free instance is suitable for testing/demo.
Your current CSV/PDF storage is local; for production use PostgreSQL + object storage.

