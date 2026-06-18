"""Import endpoints — file uploads and manual entry.

Each wraps an existing source adapter, persists the result, and returns a summary.
Uploaded files are passed straight to the adapters (pdfplumber / pandas accept the
file-like object).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.sources.betterment_csv import BettermentCSVSource
from app.sources.betterment_pdf import BettermentStatementPDFSource
from app.sources.chase_cc_pdf import ChaseCCPDFSource
from app.sources.etrade_csv import EtradeCSVSource
from app.sources.normalized_csv import NormalizedCSVSource, parse_normalized_df
from api import services

router = APIRouter(prefix="/api/import", tags=["import"])


def _run(source) -> dict:
    try:
        result = source.fetch()
        with services.locked() as con:
            summary = services.persist(con, result)
        return {"summary": summary}
    except Exception as exc:
        raise HTTPException(400, f"Import failed: {exc}")


@router.post("/betterment-pdf")
def betterment_pdf(file: UploadFile = File(...)):
    return _run(BettermentStatementPDFSource(file.file))


@router.post("/betterment-csv")
def betterment_csv(file: UploadFile = File(...)):
    return _run(BettermentCSVSource(file.file))


@router.post("/etrade")
def etrade(file: UploadFile = File(...), account: str = Form("Individual")):
    return _run(EtradeCSVSource(file.file, account=account))


@router.post("/robinhood-csv")
def robinhood_csv(file: UploadFile = File(...)):
    return _run(NormalizedCSVSource(file.file))


@router.post("/chase-pdf")
def chase_pdf(file: UploadFile = File(...), label: Optional[str] = Form(None)):
    return _run(ChaseCCPDFSource(file.file, account_label=(label or None)))


@router.post("/manual")
def manual(rows: list[dict]):
    """Append manually-entered lots/cash. Expects normalized-row dicts."""
    df = pd.DataFrame(rows)
    if df.empty:
        raise HTTPException(400, "No rows provided.")
    try:
        result = parse_normalized_df(df)
        if not (result.holdings or result.balances):
            raise HTTPException(400, "Nothing to save — add at least one row with a symbol.")
        with services.locked() as con:
            summary = services.persist_append(con, result)
        return {"summary": summary}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Save failed: {exc}")
