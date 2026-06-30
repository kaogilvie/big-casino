# Big Casino (by &KO)

A **local-only** 360° personal finance dashboard — investments, cash, credit cards, and net worth in one place. Live bank/brokerage data via Plaid; CSV imports for brokers Plaid doesn't cover well.

> Runs entirely on your machine. Nothing is sent anywhere except read-only price lookups to Yahoo Finance. The DuckDB data file is gitignored and never committed.

## Stack

| layer | tech |
|---|---|
| Frontend | React + Vite + TypeScript + Tailwind v3 + shadcn-style components |
| Backend | FastAPI (Python), wrapping the core `app/` library as a JSON API |
| Store | DuckDB local file (`data/portfolio.duckdb`) |
| Prices | yfinance (cached in `prices` table, refresh on demand) |
| Bank/brokerage data | Plaid (Link via `react-plaid-link`) |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd web && npm install
```

Copy `.env.example` to `.env` and fill in your Plaid credentials (optional — the app runs without them, Plaid features just won't appear).

## Run

```bash
cd web && npm run dev
```

This starts both servers via `concurrently`:
- FastAPI/uvicorn on `http://localhost:8000`
- Vite dev server on `http://localhost:5173` (proxies `/api` to 8000)

Open **http://localhost:5173**.

## Data model

| table | what it holds | key |
|---|---|---|
| `accounts` | institution, name, type, Plaid item link | `account_id` (slug, e.g. `chase_personal__checking`) |
| `account_settings` | per-account exclude flag and personal/&KO category | `account_id` |
| `holdings` | purchase lots — one row per buy | `lot_id` |
| `balances` | cash / bank balance per account | `account_id` |
| `card_details` | statement balance, due date, minimum payment | `account_id` |
| `prices` | latest quote per symbol | `symbol` |
| `plaid_items` | Plaid access tokens + optional display alias | `item_id` |

Market value and return are computed at read time (`app/analytics.py`), never stored. Liability accounts subtract from net worth.

## Features

**Overview** — net worth summary, allocation pie, institution bar chart (liabilities in red), and account balances table.

**Holdings** — all investment lots with live price, cost basis, and unrealized return.

**Accounts** — read-only view of account balances.

**Credit Cards** — current balance, statement balance, due date, minimum payment.

**Configuration** — everything that changes your data:
- **Plaid connections** — connect, refresh, delete, and alias each bank/brokerage connection. Connecting the same bank twice auto-disambiguates the namespace (e.g. "Chase" vs "Chase (2)") so accounts don't collide. Aliases let you rename connections to something meaningful (e.g. "Chase Personal" / "Chase Business").
- **Manage accounts** — rename, retype, set personal vs &KO category, or exclude any account (e.g. unsupported crypto accounts).
- **File imports** — E\*TRADE CSV, Betterment CSV, normalized CSV template.
- **Manual entry** — enter lots directly without a file.

**All / Personal / &KO filter** — global header toggle filters every view to a single ownership context.

## Project layout

```
app/                   Core Python library (no UI code)
  db.py                DuckDB schema + all read/write functions
  models.py            Account / Holding / Balance / ImportResult
  analytics.py         enrich() + totals(): market value, return, net worth
  prices.py            yfinance batch quotes
  plaid_client.py      Plaid SDK setup (reads .env)
  sources/             Pluggable import adapters
    plaid.py           PlaidItemSource — fetches accounts, holdings, balances, liabilities
    betterment_csv.py
    etrade_csv.py
    normalized_csv.py
api/                   FastAPI app
  main.py              App factory, CORS, router registration
  services.py          Shared DuckDB connection + threading lock
  routers/
    portfolio.py       GET /api/portfolio (summary, holdings, balances, cards)
    accounts.py        GET/PATCH /api/accounts (rename, settings)
    plaid.py           Plaid link-token / exchange / refresh / delete
    import_.py         File + manual import endpoints
    prices.py          POST /api/refresh-prices
web/                   React frontend
  src/
    App.tsx            Shell: tabs, global filter, retirement toggle
    views/             Overview, Holdings, Accounts, CreditCards, Import (Configuration)
    lib/
      api.ts           Typed fetch client for the FastAPI backend
      utils.ts         money(), typeLabel(), cn()
    components/ui/     Button, Table, Badge, Collapsible, etc.
data/                  portfolio.duckdb (gitignored) + CSV templates
samples/               Synthetic CSVs for testing
tests/                 Offline pipeline tests (no network)
```

## Importing holdings

### Plaid (recommended)
Connect via **Configuration → Plaid connections**. Supported: most US banks, brokerages, and credit cards. Refresh any time to pull the latest data.

### E\*TRADE CSV
**Portfolios → Download** on E\*TRADE, then upload via Configuration → E\*TRADE export.

### Betterment CSV
Download from Betterment, upload via Configuration → Betterment export.

### Normalized CSV / manual entry
Use the blank template or the in-app manual entry grid. Columns:

| column | notes |
|---|---|
| `broker` | institution name |
| `account` | your nickname for the account |
| `type` | `brokerage`, `bank`, `credit_card`, or `retirement` |
| `symbol` | ticker; use `CASH` for uninvested cash (→ balances) |
| `quantity` | shares (or dollars for `CASH`) |
| `cost_per_share` | average price paid per share |
| `purchase_date` | `YYYY-MM-DD` (optional) |

## Tests

```bash
.venv/bin/python tests/test_pipeline.py
```

Covers CSV adapters, analytics math, and DuckDB upsert round-trips. No network required.
