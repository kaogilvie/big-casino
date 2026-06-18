"""Plaid-backed source adapters.

Two entry points:

  create_link_token(client)
      Returns a link_token string to initialize Plaid Link in the browser.

  exchange_public_token(client, public_token) -> (item_id, access_token)
      Exchanges the public_token returned by Plaid Link for a persistent
      access_token. Store access_token in plaid_items; use it to refresh.

  PlaidItemSource(PortfolioSource)
      Fetches a stored Plaid item (access_token) into our model:
        * accounts_balance_get   → every account's metadata + cash/credit balance
        * investments_holdings_get → per-security positions for brokerages

      Plaid does NOT expose individual tax lots — investments_holdings_get returns
      one aggregated position per (account, security) with a single blended
      cost_basis. So holdings from Plaid are marked cost_basis_type="blended".
      For true per-lot data (e.g. Robinhood buys) use the manual grid instead.

      To avoid double-counting, an account that has investment holdings does NOT
      also emit its total-value balance; only its cash sleeve becomes a Balance.
"""
from __future__ import annotations

from typing import Optional

from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.liabilities_get_request import LiabilitiesGetRequest
from plaid.model.products import Products

from app.models import Account, Balance, CardDetail, Holding, ImportResult
from app.sources.base import PortfolioSource

# Plaid subtypes that map to retirement regardless of type.
_RETIREMENT_SUBTYPES = {"roth", "ira", "401k", "403b", "457b", "roth 401k", "sep ira", "simple ira"}

# Map Plaid account type → our account type (fallback when subtype doesn't match).
_TYPE_MAP = {
    "depository": "bank",
    "credit":     "credit_card",
    "investment": "brokerage",
    "loan":       "credit_card",
    "other":      "brokerage",
}


def create_link_token(client: plaid_api.PlaidApi, redirect_uri: Optional[str] = None) -> str:
    """Create a Plaid Link token. Pass to the browser to initialize Link.

    `transactions` is the required product (works for banks and credit cards).
    `investments` is optional so brokerages (Robinhood, E*TRADE) also return
    holdings, without failing for institutions that don't support it.
    """
    req = LinkTokenCreateRequest(
        products=[Products("transactions")],
        optional_products=[Products("investments"), Products("liabilities")],
        client_name="Big Casino",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id="local-user"),
        **({"redirect_uri": redirect_uri} if redirect_uri else {}),
    )
    resp = client.link_token_create(req)
    return resp["link_token"]


def exchange_public_token(
    client: plaid_api.PlaidApi, public_token: str
) -> tuple[str, str]:
    """Exchange a public_token for (item_id, access_token)."""
    resp = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    )
    return resp["item_id"], resp["access_token"]


def remove_item(client: plaid_api.PlaidApi, access_token: str) -> None:
    """Invalidate an item's access_token at Plaid (stops billing for it)."""
    client.item_remove(ItemRemoveRequest(access_token=access_token))


class PlaidItemSource(PortfolioSource):
    """Fetch live balances for all accounts in a Plaid item."""
    name = "plaid"

    def __init__(self, client: plaid_api.PlaidApi, access_token: str, institution: str):
        self.client = client
        self.access_token = access_token
        self.institution = institution

    def _account_type(self, acct) -> str:
        plaid_type = str(acct["type"]).lower()
        plaid_subtype = str(acct.get("subtype") or "").lower()
        name = (acct["name"] or acct.get("official_name") or "").lower()
        if plaid_subtype in _RETIREMENT_SUBTYPES or name.startswith("retirement"):
            return "retirement"
        return _TYPE_MAP.get(plaid_type, "brokerage")

    def _make_account(self, acct) -> Account:
        """Build our Account from a Plaid account dict, with consistent naming.

        Credit cards get a "••••<mask>" suffix so two cards at one issuer don't
        slug to the same account_id (matches the PDF importer's style).
        """
        acct_type = self._account_type(acct)
        name = acct["name"] or acct.get("official_name") or acct["account_id"]
        mask = acct.get("mask")
        if acct_type == "credit_card" and mask and str(mask) not in name:
            name = f"{name} ••••{mask}"
        return Account(institution=self.institution, name=name, type=acct_type)

    def _fetch_liabilities(self) -> dict:
        """Return {account_id: CardDetail} for credit-card liabilities.

        Empty if the item has no liabilities product / no credit cards.
        """
        try:
            resp = self.client.liabilities_get(
                LiabilitiesGetRequest(access_token=self.access_token)
            )
        except Exception:
            return {}

        acct_meta = {a["account_id"]: self._make_account(a) for a in resp["accounts"]}
        liabilities = resp.get("liabilities") or {}
        cards: dict = {}
        for c in (liabilities.get("credit") or []):
            acct = acct_meta.get(c["account_id"])
            if acct is None:
                continue

            def _num(v):
                return float(v) if v is not None else None

            def _date(v):
                return str(v)[:10] if v is not None else None

            cards[acct.account_id] = CardDetail(
                account_id=acct.account_id,
                statement_balance=_num(c.get("last_statement_balance")),
                statement_date=_date(c.get("last_statement_issue_date")),
                due_date=_date(c.get("next_payment_due_date")),
                minimum_payment=_num(c.get("minimum_payment_amount")),
                source=self.name,
            )
        return cards

    def _fetch_investments(self):
        """Return (holdings_by_account, cash_by_account, invested_account_ids).

        Returns empty maps if the item has no investments product / accounts.
        holdings_by_account: account_id -> list[Holding]
        cash_by_account:     account_id -> float (uninvested cash sleeve)
        invested_account_ids: set of our account_ids that had investment data
        """
        try:
            resp = self.client.investments_holdings_get(
                InvestmentsHoldingsGetRequest(access_token=self.access_token)
            )
        except Exception:
            # Item not linked with investments, or institution doesn't support it.
            return {}, {}, set()

        # security_id -> security dict
        secs = {s["security_id"]: s for s in resp["securities"]}
        # plaid account_id -> our account (for slug + type)
        acct_meta = {a["account_id"]: self._make_account(a) for a in resp["accounts"]}

        holdings_by_account: dict[str, list] = {}
        cash_by_account: dict[str, float] = {}
        invested: set[str] = set()

        for h in resp["holdings"]:
            acct = acct_meta.get(h["account_id"])
            if acct is None:
                continue
            aid = acct.account_id
            invested.add(aid)

            sec = secs.get(h["security_id"], {})
            sec_type = str(sec.get("type") or "").lower()
            ticker = sec.get("ticker_symbol")
            quantity = float(h.get("quantity") or 0.0)

            # The uninvested-cash position inside a brokerage shows up as a
            # security of type "cash" (often with no ticker). Route it to a
            # Balance rather than a Holding.
            if sec_type == "cash" or (not ticker and sec_type in ("", "cash")):
                cash_by_account[aid] = cash_by_account.get(aid, 0.0) + float(
                    h.get("institution_value") or 0.0
                )
                continue

            symbol = ticker or sec.get("name") or h["security_id"]
            if quantity <= 0:
                continue

            # Plaid `cost_basis` is the TOTAL cost basis of the position. Derive
            # per-share; if absent, fall back to current price so we don't invent
            # a gain/loss. Marked "blended" — Plaid gives no per-lot detail.
            total_cost = h.get("cost_basis")
            if total_cost is not None and quantity:
                cost_per_share = float(total_cost) / quantity
            else:
                cost_per_share = float(h.get("institution_price") or 0.0)

            holdings_by_account.setdefault(aid, []).append(
                Holding(
                    account_id=aid,
                    symbol=symbol,
                    quantity=quantity,
                    cost_per_share=cost_per_share,
                    source=self.name,
                    cost_basis_type="blended",
                )
            )

        return holdings_by_account, cash_by_account, invested

    def fetch(self) -> ImportResult:
        resp = self.client.accounts_balance_get(
            AccountsBalanceGetRequest(access_token=self.access_token)
        )

        holdings_by_account, cash_by_account, invested = self._fetch_investments()
        cards_by_account = self._fetch_liabilities()

        accounts = []
        holdings = []
        balances = []

        for acct in resp["accounts"]:
            account = self._make_account(acct)
            acct_type = account.type
            accounts.append(account)
            aid = account.account_id

            if aid in invested:
                # Investment account: emit its per-security holdings, plus a cash
                # Balance for the uninvested sleeve. Suppress the total-value
                # balance so we don't double-count holdings + cash.
                holdings.extend(holdings_by_account.get(aid, []))
                balances.append(Balance(
                    account_id=aid,
                    balance=float(cash_by_account.get(aid, 0.0)),
                    source=self.name,
                ))
                continue

            # Non-investment account (bank, credit card, or a brokerage with no
            # holdings data): record its balance directly.
            bal_obj = acct.get("balances", {})
            if acct_type == "credit_card":
                amount = bal_obj.get("current")
            else:
                amount = bal_obj.get("available") or bal_obj.get("current")

            if amount is not None:
                balances.append(Balance(
                    account_id=aid,
                    balance=float(amount),
                    source=self.name,
                ))

        cards = list(cards_by_account.values())
        return ImportResult(
            accounts=accounts, holdings=holdings, balances=balances, cards=cards
        )
