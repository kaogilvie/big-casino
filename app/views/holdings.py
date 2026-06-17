"""Holdings page: the detailed, sortable position table."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import db

DISPLAY_COLUMNS = {
    "symbol": "Symbol",
    "institution": "Institution",
    "name": "Account",
    "purchase_date": "Bought",
    "cost_basis_type": "Basis type",
    "quantity": "Qty",
    "cost_per_share": "Cost / share",
    "cost_basis": "Cost basis",
    "current_price": "Current price",
    "market_value": "Market value",
    "unrealized": "Unrealized $",
    "unrealized_pct": "Unrealized %",
}

_RED_BTN_CSS = """<style>
.st-key-remove_btn button, .st-key-cancel_remove button {
    background: #FF5A4D !important;
    border-color: #FF5A4D !important;
    color: #fff !important;
}
.st-key-remove_btn button:hover, .st-key-cancel_remove button:hover {
    background: #e04035 !important;
    border-color: #e04035 !important;
    color: #fff !important;
}
</style>"""


def _styled_table(enriched: pd.DataFrame) -> None:
    cols = [c for c in DISPLAY_COLUMNS if c in enriched.columns]
    table = enriched[cols].rename(columns=DISPLAY_COLUMNS).copy()

    if "Bought" in table.columns:
        table["Bought"] = (
            pd.to_datetime(table["Bought"], errors="coerce")
            .dt.strftime("%Y-%m-%d")
            .fillna("—")
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
                "Qty": "{:,.6g}",
                "Cost / share": "${:,.4f}",
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


def _remove_editor(enriched: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in DISPLAY_COLUMNS if c in enriched.columns]
    df = enriched[cols + ["lot_id"]].copy()

    if "purchase_date" in df.columns:
        df["purchase_date"] = (
            pd.to_datetime(df["purchase_date"], errors="coerce")
            .dt.strftime("%Y-%m-%d")
            .fillna("—")
        )

    df.insert(0, "Delete", False)

    col_cfg = {
        "Delete": st.column_config.CheckboxColumn("", default=False, width="small"),
        "lot_id": None,
        "symbol": st.column_config.TextColumn("Symbol", disabled=True),
        "institution": st.column_config.TextColumn("Institution", disabled=True),
        "name": st.column_config.TextColumn("Account", disabled=True),
        "purchase_date": st.column_config.TextColumn("Bought", disabled=True),
        "cost_basis_type": st.column_config.TextColumn("Basis type", disabled=True),
        "quantity": st.column_config.NumberColumn("Qty", format="%.6g", disabled=True),
        "cost_per_share": st.column_config.NumberColumn("Cost / share", format="$%.4f", disabled=True),
        "cost_basis": st.column_config.NumberColumn("Cost basis", format="$%.2f", disabled=True),
        "current_price": st.column_config.NumberColumn("Current price", format="$%.2f", disabled=True),
        "market_value": st.column_config.NumberColumn("Market value", format="$%.2f", disabled=True),
        "unrealized": st.column_config.NumberColumn("Unrealized $", format="$%.2f", disabled=True),
        "unrealized_pct": st.column_config.NumberColumn("Unrealized %", format="%.2f%%", disabled=True),
    }

    return st.data_editor(
        df,
        column_config=col_cfg,
        column_order=["Delete"] + cols,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="remove_editor",
    )


_SUMMARY_COLUMNS = {
    "symbol": "Symbol",
    "quantity": "Total Qty",
    "avg_cost_per_share": "Avg Cost / Share",
    "cost_basis": "Total Cost Basis",
    "current_price": "Current Price",
    "market_value": "Market Value",
    "unrealized": "Unrealized $",
    "unrealized_pct": "Unrealized %",
}


def _summary_table(enriched: pd.DataFrame) -> None:
    grp = enriched.groupby("symbol", sort=False)
    summary = pd.DataFrame({
        "symbol":           grp["symbol"].first(),
        "quantity":         grp["quantity"].sum(),
        "cost_basis":       grp["cost_basis"].sum(),
        "current_price":    grp["current_price"].first(),
        "market_value":     grp["market_value"].sum(),
        "unrealized":       grp["unrealized"].sum(),
    }).reset_index(drop=True)

    summary["avg_cost_per_share"] = summary["cost_basis"] / summary["quantity"]
    summary["unrealized_pct"] = (summary["unrealized"] / summary["cost_basis"] * 100).where(
        summary["cost_basis"] != 0
    )

    summary = summary.sort_values("market_value", ascending=False)

    total_qty        = summary["quantity"].sum()
    total_cost_basis = summary["cost_basis"].sum()
    total_market_val = summary["market_value"].sum()
    total_unrealized = summary["unrealized"].sum()
    totals = pd.DataFrame([{
        "symbol":            "TOTAL",
        "quantity":          total_qty,
        "avg_cost_per_share": total_cost_basis / total_qty if total_qty else float("nan"),
        "cost_basis":        total_cost_basis,
        "current_price":     float("nan"),
        "market_value":      total_market_val,
        "unrealized":        total_unrealized,
        "unrealized_pct":    (total_unrealized / total_cost_basis * 100) if total_cost_basis else float("nan"),
    }])
    summary = pd.concat([summary, totals], ignore_index=True)

    cols = [c for c in _SUMMARY_COLUMNS if c in summary.columns]
    table = summary[cols].rename(columns=_SUMMARY_COLUMNS).copy()

    def color_pl(val):
        if pd.isna(val):
            return "color: #9A9A9A"
        return "color: #2ECC71" if val >= 0 else "color: #FF5A4D"

    styled = (
        table.style
        .map(color_pl, subset=[c for c in ["Unrealized $", "Unrealized %"] if c in table.columns])
        .format(
            {
                "Total Qty":        "{:,.6g}",
                "Avg Cost / Share": "${:,.4f}",
                "Total Cost Basis": "${:,.2f}",
                "Current Price":    "${:,.2f}",
                "Market Value":     "${:,.2f}",
                "Unrealized $":     "${:,.2f}",
                "Unrealized %":     "{:+.2f}%",
            },
            na_rep="—",
        )
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def render(enriched: pd.DataFrame, con) -> None:
    st.markdown(_RED_BTN_CSS, unsafe_allow_html=True)

    if enriched.empty:
        st.info("No holdings yet. Import a CSV from the sidebar to get started.")
        return

    institutions = sorted(enriched["institution"].dropna().unique().tolist())
    if len(institutions) > 1:
        selected = st.pills(
            "Brokerages",
            options=institutions,
            default=institutions,
            selection_mode="multi",
            label_visibility="collapsed",
        )
        if selected:
            enriched = enriched[enriched["institution"].isin(selected)]
        else:
            enriched = enriched.iloc[0:0]  # nothing selected → empty

    st.subheader("Holdings Summary")
    _summary_table(enriched)

    st.subheader("All Individual Holdings")

    remove_mode = st.session_state.get("remove_mode", False)

    if remove_mode:
        edited = _remove_editor(enriched)

        _, col_cancel, col_confirm = st.columns([6, 1, 1])
        with col_cancel:
            if st.button("Cancel", key="cancel_remove", use_container_width=True):
                st.session_state["remove_mode"] = False
                st.rerun()
        with col_confirm:
            if st.button("Confirm", type="primary", key="confirm_remove", use_container_width=True):
                to_delete = edited[edited["Delete"] == True]["lot_id"].tolist()
                if not to_delete:
                    st.warning("Check at least one row to delete.")
                else:
                    db.delete_holdings(con, to_delete)
                    st.session_state["remove_mode"] = False
                    st.rerun()
    else:
        _styled_table(enriched)

        _, col_btn = st.columns([8, 2])
        with col_btn:
            if st.button("Remove a holding", key="remove_btn", use_container_width=True):
                st.session_state["remove_mode"] = True
                st.rerun()
