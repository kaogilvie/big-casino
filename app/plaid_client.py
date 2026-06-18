"""Plaid API client factory.

Reads credentials from environment (or .env file):
  PLAID_CLIENT_ID
  PLAID_SECRET
  PLAID_ENV   — sandbox | development | production  (default: production)
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from plaid.api import plaid_api
from plaid.api_client import ApiClient
from plaid.configuration import Configuration

_HOSTS = {
    "sandbox":     "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production":  "https://production.plaid.com",
}


def get_client() -> plaid_api.PlaidApi:
    load_dotenv()
    client_id = os.environ.get("PLAID_CLIENT_ID", "")
    secret = os.environ.get("PLAID_SECRET", "")
    env = os.environ.get("PLAID_ENV", "production")

    if not client_id or not secret:
        raise RuntimeError(
            "Plaid credentials not found. "
            "Copy .env.example to .env and fill in PLAID_CLIENT_ID and PLAID_SECRET."
        )

    config = Configuration(
        host=_HOSTS.get(env, _HOSTS["production"]),
        api_key={"clientId": client_id, "secret": secret},
    )
    return plaid_api.PlaidApi(ApiClient(config))


def is_configured() -> bool:
    load_dotenv()
    return bool(os.environ.get("PLAID_CLIENT_ID")) and bool(os.environ.get("PLAID_SECRET"))
