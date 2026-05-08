# Sklad Logistics Telegram Mini App

MVP for warehouse logistics workflow in Telegram Mini App:

- create invoices with cargo items
- save data to CSV (test storage)
- apply tariff to a selected invoice (inside the create invoice tab)
- calculate item totals and invoice total in tenge (`₸`)
- generate one PDF copy only after tariff is set
- assign invoice cargo to wagon (full or partial with remainder invoice)
- set estimated cargo release date during wagon assignment
- browse all invoices in Archive tab with search and filters

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

## Database Mode

The app now supports SQL database storage through `DATABASE_URL`.

- If `DATABASE_URL` is set, the app uses SQL tables (`invoices`, `invoice_items`, `wagons`, `wagon_allocations`).
- If `DATABASE_URL` is not set, it falls back to CSV files in `data/`.

Example local SQLite:

```bash
set DATABASE_URL=sqlite:///./sklad.db
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Example PostgreSQL:

```bash
set DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Vercel Deploy (GitHub)

1. Push this project to GitHub.
2. In Vercel: `Add New Project` -> import your GitHub repository.
3. Framework preset: `FastAPI` (or `Other` if FastAPI is not shown).
4. Root directory: project root.
5. Deploy.
6. Copy resulting URL `https://<project>.vercel.app`.
7. In `@BotFather`, set this URL as your Mini App URL.

### Vercel notes

- FastAPI entrypoint is `app/app.py`.
- Recommended for production: set `DATABASE_URL` in Vercel Project Settings (Environment Variables).
- Vercel Functions filesystem is read-only except `/tmp`; only PDF files are written there temporarily.
