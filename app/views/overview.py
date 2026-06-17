"""Overview page: headline metrics + value breakdowns + cash."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from app.analytics import totals
from app.theme import BRAND


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _metric(col, label: str, value: str, delta: str | None = None, positive: bool = True) -> None:
    delta_html = ""
    if delta:
        color = BRAND["green"] if positive else BRAND["red"]
        arrow = "▲" if positive else "▼"
        delta_html = f"<div class='ko-metric-delta' style='color:{color}'>{arrow} {delta}</div>"
    col.markdown(
        f"<div class='ko-metric'>"
        f"<div class='ko-metric-label'>{label}</div>"
        f"<div class='ko-metric-value'>{value}</div>"
        f"{delta_html}</div>",
        unsafe_allow_html=True,
    )


def render(enriched: pd.DataFrame, balances: pd.DataFrame) -> None:
    st.subheader("Overview")

    if enriched.empty and balances.empty:
        st.info("No accounts yet. Import a CSV from the sidebar to get started.")
        return

    t = totals(enriched, balances)
    c1, c2, c3, c4 = st.columns(4)
    _metric(c1, "Net worth", _money(t["net_worth"]))
    _metric(c2, "Investments", _money(t["investments"]))
    _metric(c3, "Cash", _money(t["cash"]))
    _metric(
        c4,
        "Unrealized gain/loss",
        _money(t["unrealized"]),
        delta=f"{t['unrealized_pct']:+.2f}%" if t["cost_basis"] else None,
        positive=t["unrealized"] >= 0,
    )

    if not enriched.empty:
        unpriced = enriched[enriched["current_price"].isna()]["symbol"].tolist()
        if unpriced:
            st.warning(
                "No live price for: " + ", ".join(sorted(set(unpriced)))
                + ". These are excluded from investment value."
            )

    st.markdown("---")
    left, right = st.columns(2)

    with left:
        st.markdown("**Investment value by institution**")
        if not enriched.empty:
            by_inst = (
                enriched.groupby("institution")["market_value"].sum().reset_index().dropna()
            )
            if not by_inst.empty:
                fig = px.pie(by_inst, names="institution", values="market_value", hole=0.55)
                fig.update_traces(textinfo="label+percent")
                fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=320)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No holdings yet.")

    with right:
        st.markdown("**Value by account**")
        if not enriched.empty:
            by_acct = (
                enriched.assign(label=enriched["institution"] + " · " + enriched["name"])
                .groupby("label")["market_value"]
                .sum()
                .reset_index()
                .dropna()
                .sort_values("market_value")
            )
            if not by_acct.empty:
                fig = px.bar(by_acct, x="market_value", y="label", orientation="h")
                fig.update_traces(marker_color=BRAND["amber"])
                fig.update_layout(
                    margin=dict(t=10, b=10, l=10, r=10),
                    height=320,
                    xaxis_title="Market value ($)",
                    yaxis_title="",
                )
                st.plotly_chart(fig, use_container_width=True)

    if not balances.empty:
        st.markdown("---")
        st.markdown("**Cash & balances**")
        show = balances.copy()
        if "institution" in show.columns:
            show["Account"] = show["institution"].fillna("?") + " · " + show["name"].fillna("?")
        else:
            show["Account"] = show["account_id"]
        show = show.rename(columns={"balance": "Balance", "type": "Type"})
        cols = [c for c in ["Account", "Type", "Balance"] if c in show.columns]
        st.dataframe(
            show[cols].style.format({"Balance": "${:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )
