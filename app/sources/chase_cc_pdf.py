"""Chase credit-card statement PDF parser -> ImportResult.

Extracts from the Account Summary page:
  * Account (institution=Chase, name derived from last-4 digits, type=credit_card)
  * Balance (New Balance = current amount owed)

Only the current balance is imported — no transaction history.

When Plaid comes online, replace this with ChaseePlaidSource implementing the same
fetch() -> ImportResult signature; the store and UI need no changes.
"""
from __future__ import annotations

import re
from typing import Optional

import pdfplumber

from app.models import Account, Balance, ImportResult
from app.sources.base import PortfolioSource, to_float

INSTITUTION = "Chase"

# "Account Number:  XXXX XXXX XXXX 7626"
_ACCT_NUM_RE = re.compile(r'Account\s+Number[:\s]+.*?(\d{4})\s*$', re.IGNORECASE)

# "New Balance  $877.33" — may be on one line or split across two
_NEW_BAL_RE = re.compile(r'New\s+Balance[\s\$]+([\d,]+\.?\d*)', re.IGNORECASE)
# Fallback: "New Balance" on its own line, amount on the next
_NEW_BAL_LABEL_RE = re.compile(r'^\s*New\s+Balance\s*$', re.IGNORECASE)
_AMOUNT_RE = re.compile(r'^\s*\$?([\d,]+\.\d{2})\s*$')


class ChaseCCPDFSource(PortfolioSource):
    name = "chase_cc_pdf"

    def __init__(self, file, account_label: Optional[str] = None):
        self.file = file
        self.account_label = account_label  # optional override; default = "Chase ••••XXXX"

    def fetch(self) -> ImportResult:
        with pdfplumber.open(self.file) as pdf:
            pages_text = [p.extract_text() or "" for p in pdf.pages]

        last_four: Optional[str] = None
        new_balance: Optional[float] = None

        for text in pages_text:
            lines = text.splitlines()
            for i, line in enumerate(lines):
                # Account number
                if last_four is None:
                    m = _ACCT_NUM_RE.search(line)
                    if m:
                        last_four = m.group(1)

                # New Balance — same line
                if new_balance is None:
                    m = _NEW_BAL_RE.search(line)
                    if m:
                        new_balance = to_float(m.group(1).replace(",", ""))
                        continue

                # New Balance — label on this line, amount on next
                if new_balance is None and _NEW_BAL_LABEL_RE.match(line):
                    if i + 1 < len(lines):
                        m = _AMOUNT_RE.match(lines[i + 1])
                        if m:
                            new_balance = to_float(m.group(1).replace(",", ""))

            if last_four and new_balance is not None:
                break  # got everything we need

        if new_balance is None:
            raise ValueError(
                "Could not find 'New Balance' in this PDF. "
                "Is this a Chase credit card statement?"
            )

        name = self.account_label or (
            f"Chase ••••{last_four}" if last_four else "Chase Card"
        )
        account = Account(institution=INSTITUTION, name=name, type="credit_card")

        return ImportResult(
            accounts=[account],
            holdings=[],
            balances=[Balance(
                account_id=account.account_id,
                balance=new_balance,
                source=self.name,
            )],
        )
