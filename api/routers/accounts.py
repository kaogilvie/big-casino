"""Account metadata edits — rename / re-type an account.

Renaming may change the slug account_id; db.rename_account migrates all FK
references (holdings, balances) and returns the new id.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db
from app.models import ACCOUNT_TYPES
from api import services

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class RenameBody(BaseModel):
    institution: str
    name: str
    type: str


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
