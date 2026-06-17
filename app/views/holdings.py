"""Holdings page: the detailed, sortable position table."""
from __future__ import annotations

import pandas as pd
import streamlit as st

DISPLAY_COLUMNS = {
    "symbol": "Symbol",
    "institution": "Institution",
    "name": "Account",
    "purchase_date": "Bought",
    "quantity": "Qty",
    "cost_per_share": "Cost / share",
    "cost_basis": "Cost basis",
    "current_price": "Current price",
    "market_value": "Market value",
    "unrealized": "Unrealized $",
    "unrealized_pct": "Unrealized %",
}


def render(enriched: pd.DataFrame) -> None:
    st.subheader("Holdings")

    if enriched.empty:
        st.info("No holdings yet. Import a CSV from the sidebar to get started.")
        return

    cols = [c for c in DISPLAY_COLUMNS if c in enriched.columns]
    table = enriched[cols].rename(columns=DISPLAY_COLUMNS).copy()

    if "Bought" in table.columns:
        table["Bought"] = (
            pd.to_datetime(table["Bought"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("—")
        )

    def color_pl(val):
        if pd.isna(val):
            return "color: #9A9A9A"
        return "color: #2ECC71" if val >= 0 else "color: #FF5A4D"

    styled = (
        table.style
        .map(color_pl, subset=[c for c in ["Unrealized $", "Unrealized %"] if c in table.columns])
        .format(
            {
                "Qty": "{:,.4g}",
                "Cost / share": "${:,.2f}",
                "Cost basis": "${:,.2f}",
                "Current price": "${:,.2f}",
                "Market value": "${:,.2f}",
                "Unrealized $": "${:,.2f}",
                "Unrealized %": "{:+.2f}%",
            },
            na_rep="—",
        )
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)
