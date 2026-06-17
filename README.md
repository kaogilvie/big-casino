# Portfolio · 360°

A **local-only** dashboard for a single view of your investments. Phase 1 pulls
**E\*TRADE** and **Robinhood** stock holdings from CSV into one place and shows
quantity, cost basis, live price, and unrealized return.

> Personal financials. Runs entirely on your machine — nothing is sent anywhere
> except the (read-only) price lookups to Yahoo Finance. The DuckDB data file is
> gitignored and never committed. Uses the &KO brand colors but not the logo;
> this is not an &KO product.

## Stack
- **Streamlit** UI (brand-themed: amber `#FCA917` on black)
- **DuckDB** local file store (`data/portfolio.duckdb`) — the source of truth
- **yfinance** for live prices (persisted in the `prices` table, refresh on demand)
- Pluggable **source adapters** so APIs / Plaid can be added later without
  touching the dashboard

## Data model

Four tables, each a distinct entity (see [app/db.py](app/db.py)):

| table | what it holds | key |
|---|---|---|
| `accounts` | account metadata: institution, name, type (`brokerage`/`bank`/`credit_card`/`retirement`), currency | `account_id` (slug, e.g. `robinhood__individual`) |
| `holdings` | purchase **lots** — one row per buy (multiple lots per symbol allowed), each with its own cost & date | `lot_id` |
| `balances` | cash / bank / card balance per account | `account_id` |
| `prices` | latest quote per symbol, with `as_of` | `symbol` |

Holdings and balances reference an account by `account_id`. **Prices are decoupled
from holdings** — a price refresh never rewrites a position. Market value and
return are computed at read time ([app/analytics.py](app/analytics.py)), never
stored. Cash is *not* a holding: a `CASH` row in a CSV becomes a `balances` row.
Liability accounts (credit cards) subtract from net worth.

## Setup
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run
```bash
.venv/bin/streamlit run app/main.py
```
Then open the URL it prints (default http://localhost:8501).

## Importing holdings

Use the **Import tab**. Two file types are supported:

### 1. Normalized template (use this for Robinhood)
Robinhood has no clean holdings export, so enter holdings yourself. Two ways:

- **In-app editor (no file needed):** the Import tab has an *"Or enter rows
  manually"* grid — type rows one at a time or paste several, then **Save
  entries**. Use `CASH` as the symbol for a cash balance.
- **CSV:** **Download blank template** in the Import tab (or copy
  [`data/templates/normalized_holdings_template.csv`](data/templates/normalized_holdings_template.csv)),
  fill it, and upload.

Both paths use the same columns and parser:

| column | required | notes |
|---|---|---|
| `broker` | yes | institution, e.g. `robinhood`, `chase` |
| `account` | yes | your nickname for the account, e.g. `Individual` |
| `type` | optional | `brokerage` (default), `bank`, `credit_card`, `retirement` |
| `symbol` | yes | ticker; use `CASH` for an uninvested cash balance (→ `balances`) |
| `quantity` | yes | shares (or dollars, for a `CASH` row) |
| `cost_per_share` | one of | average price paid per share |
| `total_cost` | these two | alternative to `cost_per_share`; per-share is derived |
| `purchase_date` | optional | `YYYY-MM-DD` |

A pure cash/bank account is just one `CASH` row with `type` set (e.g.
`chase,Checking,bank,CASH,5000,1.00,`).

### 2. E\*TRADE export
On E\*TRADE: **Portfolios → Download** (CSV). Upload it with the **E\*TRADE
export** file type selected. The parser finds the header row containing `Symbol`
and `Qty`, reads the positions, and skips the cash/total/disclaimer rows.

> The parser is written against the standard export format and is tolerant of
> small variations. If your export uses different column names, drop a redacted
> copy in `samples/` and the parser can be tightened to match.

### Import behavior
Holdings are stored as **lots** (one row per purchase), so multiple buys of the
same stock keep their exact cost and date — total and per-lot return are precise.
An import or manual save is **authoritative for the accounts it touches**: it
replaces those accounts' lots (idempotent re-import, no duplicates) and leaves
other accounts alone. The manual grid preloads existing lots so adding one doesn't
wipe the rest. **Clear data** wipes the store; **Refresh prices** drops the cache.

> Note: the E*TRADE portfolio export carries only *average* cost (one row per
> symbol), so per-lot detail there is limited to that blended figure. Use E*TRADE's
> tax-lot export or the manual grid for exact lots.

## Project layout
```
app/
  main.py            Streamlit entry (sidebar, import, tabs, price persistence)
  models.py          Account / Holding / Balance + ImportResult; account_id slug
  db.py              DuckDB: accounts/holdings/balances/prices + upsert/load
  prices.py          yfinance batch quotes (+ per-ticker fallback)
  analytics.py       enrich() + totals(): market value, return, cash, net worth
  theme.py           brand palette, CSS, Plotly template
  sources/           pluggable adapters (CSV now; API/Plaid later)
    base.py          PortfolioSource ABC + parsing helpers
    normalized_csv.py   routes CASH -> balances
    etrade_csv.py       captures positions + CASH&ALT value as a balance
  views/             overview (metrics + charts + cash), holdings (table)
data/                portfolio.duckdb (gitignored) + blank template
samples/             synthetic CSVs for testing
tests/               offline pipeline tests (no network)
```

## Tests
```bash
.venv/bin/python tests/test_pipeline.py
```
Covers both CSV adapters, the enrich/totals math, and a DuckDB upsert round-trip.
No network required (prices are stubbed).

## Roadmap (next phases)
- Bank & credit-card accounts (Capital One, Chase, Wells Fargo, Citi, Betterment, Fidelity)
- **Tagging + "hold X"**: actual balance vs. effective balance without moving money
- Historical value-over-time tracking
- Live ingestion via broker APIs (E\*TRADE OAuth) or Plaid — slots in as new
  `PortfolioSource` adapters; the store and UI stay the same.
