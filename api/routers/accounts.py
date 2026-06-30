"""Account metadata edits — rename / re-type an account.

Renaming may change the slug account_id; db.rename_account migrates all FK
references (holdings, balances) and returns the new id.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db
from app.models import ACCOUNT_TYPES
from api import services
from api.serializers import records

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class RenameBody(BaseModel):
    institution: str
    name: str
    type: str


class SettingsBody(BaseModel):
    excluded: Optional[bool] = None
    category: Optional[str] = None  # "personal" | "ko"


@router.get("")
def list_accounts():
    """Every account with its settings — unfiltered, for the management UI."""
    with services.locked() as con:
        accounts = db.load_accounts_df(con)
        settings = db.load_account_settings_df(con)
    if accounts.empty:
        return {"accounts": []}
    if not settings.empty:
        accounts = accounts.merge(settings, on="account_id", how="left")
    else:
        accounts["excluded"] = False
        accounts["category"] = "personal"
    accounts["excluded"] = accounts["excluded"].fillna(False).astype(bool)
    accounts["category"] = accounts["category"].fillna("personal")
    return {"accounts": records(accounts)}


@router.patch("/{account_id}/settings")
def update_settings(account_id: str, body: SettingsBody):
    if body.category is not None and body.category not in ("personal", "ko"):
        raise HTTPException(400, "category must be 'personal' or 'ko'")
    with services.locked() as con:
        db.upsert_account_settings(con, account_id, excluded=body.excluded, category=body.category)
    return {"ok": True}


@router.patch("/{account_id}")
def rename(account_id: str, body: RenameBody):
    acct_type = body.type if body.type in ACCOUNT_TYPES else "brokerage"
    try:
        with services.locked() as con:
            new_id = db.rename_account(
                con,
                old_account_id=account_id,
                institution=body.institution.strip(),
                name=body.name.strip(),
                account_type=acct_type,
            )
        return {"account_id": new_id}
    except Exception as exc:
        raise HTTPException(400, f"Rename failed: {exc}")
