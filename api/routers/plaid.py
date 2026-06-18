"""Plaid endpoints — replaces the standalone Express server.

The React frontend runs Plaid Link natively (react-plaid-link), so there's no
iframe sandbox to work around: Link hands the public_token straight to
/api/plaid/exchange.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db, plaid_client as plaid_cfg
from app.sources.plaid import (
    PlaidItemSource,
    create_link_token,
    exchange_public_token,
    remove_item,
)
from api import services
from api.serializers import records

router = APIRouter(prefix="/api/plaid", tags=["plaid"])


class ExchangeBody(BaseModel):
    public_token: str
    institution: str = "Unknown"


@router.get("/status")
def status():
    return {"configured": plaid_cfg.is_configured()}


@router.post("/link-token")
def link_token():
    if not plaid_cfg.is_configured():
        raise HTTPException(400, "Plaid not configured — set PLAID_CLIENT_ID/PLAID_SECRET in .env")
    try:
        client = plaid_cfg.get_client()
        return {"link_token": create_link_token(client)}
    except Exception as exc:
        raise HTTPException(502, f"Could not create link token: {exc}")


@router.post("/exchange")
def exchange(body: ExchangeBody):
    try:
        client = plaid_cfg.get_client()
        item_id, access_token = exchange_public_token(client, body.public_token)
        result = PlaidItemSource(client, access_token, body.institution).fetch()
        with services.locked() as con:
            db.upsert_plaid_item(con, item_id, access_token, body.institution)
            summary = services.persist(con, result)
        return {"item_id": item_id, "institution": body.institution, "summary": summary}
    except Exception as exc:
        raise HTTPException(502, f"Plaid connection failed: {exc}")


@router.get("/items")
def items():
    with services.locked() as con:
        return {"items": records(db.load_plaid_items(con))}


@router.post("/items/{item_id}/refresh")
def refresh(item_id: str):
    with services.locked() as con:
        token = db.get_plaid_access_token(con, item_id)
        row = db.load_plaid_items(con)
        if token is None:
            raise HTTPException(404, "Unknown item")
        institution = "Unknown"
        match = row[row["item_id"] == item_id]
        if not match.empty:
            institution = match.iloc[0]["institution"]
    try:
        client = plaid_cfg.get_client()
        result = PlaidItemSource(client, token, institution).fetch()
        with services.locked() as con:
            summary = services.persist(con, result)
        return {"institution": institution, "summary": summary}
    except Exception as exc:
        raise HTTPException(502, f"Refresh failed: {exc}")


@router.delete("/items/{item_id}")
def delete(item_id: str):
    with services.locked() as con:
        token = db.get_plaid_access_token(con, item_id)
        row = db.load_plaid_items(con)
        match = row[row["item_id"] == item_id]
        institution = match.iloc[0]["institution"] if not match.empty else "Unknown"
    # Best-effort token invalidation at Plaid (stops billing).
    try:
        if token:
            remove_item(plaid_cfg.get_client(), token)
    except Exception:
        pass
    with services.locked() as con:
        db.delete_plaid_connection(con, item_id, institution)
    return {"ok": True, "institution": institution}
