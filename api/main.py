"""Big Casino API — FastAPI backend for the React frontend.

Run from the project root:
    uvicorn api.main:app --reload --port 8000

Wraps the existing `app` package (parsers, Plaid adapters, DuckDB store,
analytics) as a JSON API. The React app in web/ is the only consumer.
"""
from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI

from app import db
from app.prices import fetch_prices
from api import services
from api.routers import accounts, imports, plaid, portfolio

app = FastAPI(title="Big Casino API")

# Vite dev server origins. Local-only app, so this is intentionally permissive.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

admin = APIRouter(prefix="/api", tags=["admin"])


@admin.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def root():
    return {
        "app": "Big Casino API",
        "docs": "/docs",
        "endpoints": ["/api/health", "/api/portfolio", "/api/plaid/items", "/api/import/*"],
    }


@admin.post("/refresh-prices")
def refresh_prices():
    with services.locked() as con:
        symbols = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM holdings").fetchall()]
        if symbols:
            db.upsert_prices(con, fetch_prices(symbols))
    return {"refreshed": len(symbols)}


@admin.post("/clear")
def clear():
    with services.locked() as con:
        db.clear_all(con)
    return {"ok": True}


app.include_router(admin)
app.include_router(portfolio.router)
app.include_router(imports.router)
app.include_router(plaid.router)
app.include_router(accounts.router)
