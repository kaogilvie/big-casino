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


class AliasBody(BaseModel):
    alias: str | None = None


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
        # Decide the account namespace before importing. A brand-new login at an
        # already-connected bank (e.g. a 2nd Chase) gets a unique namespace
        # ("Chase (2)") so its accounts don't collide with the first.
        with services.locked() as con:
            existing = db.get_plaid_item(con, item_id)
            if existing:
                namespace = existing["alias"] or existing["institution"]
                db.upsert_plaid_item(con, item_id, access_token, existing["institution"])
            else:
                namespace = db.unique_institution(con, body.institution)
                db.upsert_plaid_item(con, item_id, access_token, namespace)
        result = PlaidItemSource(client, access_token, namespace).fetch()
        with services.locked() as con:
            summary = services.persist(con, result)
            db.tag_accounts_with_item(con, [a.account_id for a in result.accounts], item_id)
            db.touch_plaid_refresh(con)
        return {"item_id": item_id, "institution": namespace, "summary": summary}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Plaid connection failed: {exc}")


@router.get("/items")
def items():
    with services.locked() as con:
        return {"items": records(db.load_plaid_items(con))}


@router.patch("/items/{item_id}")
def set_alias(item_id: str, body: AliasBody):
    """Set/clear a connection alias. The alias is the account namespace, so
    changing it re-slugs every account belonging to this connection (e.g.
    'Chase (2)' -> 'Chase Business' -> chase_business__*)."""
    alias = (body.alias or "").strip() or None
    with services.locked() as con:
        item = db.get_plaid_item(con, item_id)
        if item is None:
            raise HTTPException(404, "Unknown item")
        old_ns = item["alias"] or item["institution"]
        new_ns = alias or item["institution"]
        db.set_plaid_alias(con, item_id, alias)
        renamed = db.renamespace_item_accounts(con, item_id, new_ns) if new_ns != old_ns else 0
    return {"ok": True, "alias": alias, "renamed": renamed}


@router.post("/items/{item_id}/refresh")
def refresh(item_id: str):
    with services.locked() as con:
        token = db.get_plaid_access_token(con, item_id)
        item = db.get_plaid_item(con, item_id)
        if token is None or item is None:
            raise HTTPException(404, "Unknown item")
        namespace = item["alias"] or item["institution"]
    try:
        client = plaid_cfg.get_client()
        result = PlaidItemSource(client, token, namespace).fetch()
        with services.locked() as con:
            summary = services.persist(con, result)
            db.tag_accounts_with_item(con, [a.account_id for a in result.accounts], item_id)
            db.touch_plaid_refresh(con)
        return {"institution": namespace, "summary": summary}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Refresh failed: {exc}")


@router.post("/refresh-all")
def refresh_all():
    """Refresh every connected Plaid item in sequence."""
    if not plaid_cfg.is_configured():
        raise HTTPException(400, "Plaid not configured")
    with services.locked() as con:
        items_df = db.load_plaid_items(con)
    if items_df.empty:
        return {"refreshed": 0, "errors": []}

    client = plaid_cfg.get_client()
    refreshed = 0
    errors = []
    for _, row in items_df.iterrows():
        item_id = row["item_id"]
        alias = row["alias"] if row["alias"] and str(row["alias"]) != "nan" else None
        with services.locked() as con:
            token = db.get_plaid_access_token(con, item_id)
            namespace = alias or row["institution"]
        if not token:
            continue
        try:
            result = PlaidItemSource(client, token, namespace).fetch()
            with services.locked() as con:
                services.persist(con, result)
                db.tag_accounts_with_item(con, [a.account_id for a in result.accounts], item_id)
            refreshed += 1
        except Exception as exc:
            errors.append({"item_id": item_id, "institution": namespace, "error": str(exc)})

    if refreshed > 0:
        with services.locked() as con:
            db.touch_plaid_refresh(con)

    return {"refreshed": refreshed, "errors": errors}


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
