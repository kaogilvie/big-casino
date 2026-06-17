"""Betterment monthly-statement PDF parser -> ImportResult.

Reads the PDF Betterment generates at Documents → Monthly Statement.

Structure (from pdfplumber text extraction):

  Cash Reserve section (page 2):
    "Cash Reserve Account #<num>"
    Monthly Overview block (skip)
    "ACTIVITY"
    "Cash Reserve"           ← bucket sub-heading
    "Date Description Amount"
    "May 1 2026 Beginning Balance $X"
    "May 31 2026 Ending Balance $X"   ← capture
    "Taxes"                  ← next bucket
    ...
    "TOTAL HOLDINGS"         ← end of buckets

  Investing accounts (one per page group):
    "AccountName Account #<num>"
    "HOLDINGS"
    "Starting Change Ending2"
    "Type Description Ticker Shares Value Shares Value Shares Value"
    "ETFs Full Name AGG 10.5 $X 0.5 $X 11.0 $X"
    ...
    "Total $X $X $X"         ← end of holdings
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

import pdfplumber

from app.models import Account, Balance, Holding, ImportResult
from app.sources.base import PortfolioSource, to_float

INSTITUTION = "Betterment"

# Stable mapping of account numbers to canonical names + types.
# Long account names in the PDF can wrap across lines, so we key by number.
_ACCOUNT_NUMBER_MAP: dict[str, tuple[str, str]] = {
    "8400124716956":   ("Retirement - Tax-Coordinated Portfolio", "brokerage"),
    "8400139953610":   ("Safety Net - Automated Investing",       "brokerage"),
    "8400146880350":   ("Climate Investing - Automated Investing","brokerage"),
    "268011229047166": ("Roth IRA",                               "retirement"),
    "268011245128164": ("Traditional IRA",                        "retirement"),
    # 268011233201270 is the member-level ID shared by Cash Reserve and
    # Taxable Investing Account — resolved by the inline name on the line.
}

# Rollup accounts whose holdings are the aggregate of sub-goals.
_ROLLUP_ACCOUNTS = {"Taxable Investing Account"}

_CASH_RESERVE = "Cash Reserve"

# Finds "Account #<10+ digits>" anywhere on a line.
_ACCT_NUMBER_RE = re.compile(r'Account\s+#(\d{10,})')

# Greedy: captures everything before the last "Account #..." on a line.
# Greedy (.+) correctly captures "Taxable Investing Account" from
# "Taxable Investing Account Account #123...".
_ACCT_INLINE_RE = re.compile(r'^(.+)\s+Account\s+#\d{10,}')

# Cash Reserve bucket ending balance row: "May 31 2026 Ending Balance $52,101.43"
# The monthly overview uses "Ending Balance (May 31 2026) $X" — parentheses after
# "Ending Balance" — so this regex (which requires no open-paren) skips it.
_BUCKET_ENDING_RE = re.compile(r'Ending Balance\s+\$([\d,]+\.?\d*)')

# Investment account holdings row:
#   [ETFs] Full ETF Name TICKER start_shares $start_val change_shares [-]$change_val end_shares $end_val
_ROW_RE = re.compile(
    r'\b([A-Z]{2,5})\s+'    # ticker (all-caps 2–5 letters)
    r'([\d.]+)\s+'           # starting shares (discard)
    r'\$[\d,.]+\s+'          # starting value (discard)
    r'-?[\d.]+\s+'           # change shares (discard, may be negative)
    r'-?\$[\d,.]+\s+'        # change value (discard, may be negative)
    r'([\d.]+)\s+'           # ENDING shares (keep)
    r'\$[\d,.]+'             # ending value (discard)
)


def _account_type(name: str) -> str:
    low = name.lower()
    if "roth" in low or "traditional" in low or "sep ira" in low or "ira" in low:
        return "retirement"
    if name == _CASH_RESERVE:
        return "bank"
    return "brokerage"


def _resolve_account(number: str, inline_name: str) -> tuple[str, str]:
    """Return (canonical_name, type) for an account number."""
    if number in _ACCOUNT_NUMBER_MAP:
        return _ACCOUNT_NUMBER_MAP[number]
    name = inline_name.strip() if inline_name else f"Account #{number}"
    return name, _account_type(name)


class BettermentStatementPDFSource(PortfolioSource):
    name = "betterment_pdf"

    def __init__(self, file):
        self.file = file

    def fetch(self) -> ImportResult:
        with pdfplumber.open(self.file) as pdf:
            pages_text = [p.extract_text() or "" for p in pdf.pages]

        accounts: dict[str, Account] = {}
        holdings_rows: dict[str, list[tuple[str, float]]] = defaultdict(list)
        cash_buckets: list[tuple[str, float]] = []

        current_acct: Optional[str] = None
        in_holdings = False
        in_cash_reserve = False
        in_cr_activity = False  # True once we've passed "ACTIVITY" in Cash Reserve
        current_bucket: Optional[str] = None

        for text in pages_text:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                # ── Account section header ────────────────────────────────
                m = _ACCT_NUMBER_RE.search(line)
                if m:
                    number = m.group(1)
                    inline_m = _ACCT_INLINE_RE.match(line)
                    inline_name = inline_m.group(1) if inline_m else ""
                    acct_name, acct_type = _resolve_account(number, inline_name)

                    current_acct = acct_name
                    in_holdings = False
                    in_cash_reserve = (acct_name == _CASH_RESERVE)
                    in_cr_activity = False
                    current_bucket = None

                    if acct_name not in _ROLLUP_ACCOUNTS and not in_cash_reserve:
                        acct = Account(institution=INSTITUTION, name=acct_name, type=acct_type)
                        accounts.setdefault(acct.account_id, acct)
                    continue

                if current_acct is None:
                    continue

                # ── Cash Reserve section ──────────────────────────────────
                if in_cash_reserve:
                    if line == 'ACTIVITY':
                        in_cr_activity = True
                        continue
                    if not in_cr_activity:
                        continue  # skip monthly overview block
                    # 'TOTAL HOLDINGS' marks end of per-bucket activity
                    if line.startswith('TOTAL HOLDINGS') or line.startswith('Program bank'):
                        in_cash_reserve = False
                        in_cr_activity = False
                        continue
                    # Bucket sub-heading: short line, no $, no digits, not a table header.
                    # Only set when we're not already inside a bucket.
                    if (
                        current_bucket is None
                        and not re.search(r'[\$\d]', line)
                        and line not in ('Date Description Amount',)
                        and not line.isupper()
                    ):
                        current_bucket = line
                    elif current_bucket:
                        # Capture this bucket's ending balance.
                        # Format: "May 31 2026 Ending Balance $52,101.43"
                        m2 = _BUCKET_ENDING_RE.search(line)
                        if m2:
                            amount = to_float(m2.group(1).replace(',', ''))
                            if amount > 0:
                                cash_buckets.append((current_bucket, amount))
                            current_bucket = None  # ready for next bucket
                    continue

                # ── Skip rollup accounts ──────────────────────────────────
                if current_acct in _ROLLUP_ACCOUNTS:
                    continue

                # ── Holdings section boundary ─────────────────────────────
                if line.startswith('HOLDINGS'):
                    in_holdings = True
                    continue
                if in_holdings and (
                    line.startswith('DIVIDEND')
                    or line.startswith('MONTHLY ACTIVITY')
                    or line.startswith('SWEEP')
                    or line.startswith('Total ')
                    or line == 'No holdings'
                ):
                    in_holdings = False
                    continue

                if not in_holdings:
                    continue

                # ── Parse ETF holding row ─────────────────────────────────
                m = _ROW_RE.search(line)
                if m:
                    ticker = m.group(1)
                    end_shares = float(m.group(3))
                    if end_shares >= 0.0001:
                        holdings_rows[current_acct].append((ticker, end_shares))

        # ── Assemble ImportResult ─────────────────────────────────────────
        holdings = []
        for acct_name, rows in holdings_rows.items():
            key = Account(institution=INSTITUTION, name=acct_name,
                          type=_account_type(acct_name)).account_id
            acct = accounts.get(key)
            if acct is None:
                acct = Account(institution=INSTITUTION, name=acct_name,
                               type=_account_type(acct_name))
                accounts[acct.account_id] = acct
            for ticker, shares in rows:
                holdings.append(Holding(
                    account_id=acct.account_id,
                    symbol=ticker,
                    quantity=shares,
                    cost_per_share=0.0,
                    source=self.name,
                    cost_basis_type="blended",
                ))

        balances = []
        for bucket_name, amount in cash_buckets:
            acct = Account(institution=INSTITUTION, name=bucket_name, type="bank")
            accounts.setdefault(acct.account_id, acct)
            balances.append(Balance(
                account_id=acct.account_id,
                balance=amount,
                source=self.name,
            ))

        return ImportResult(
            accounts=list(accounts.values()),
            holdings=holdings,
            balances=balances,
        )
