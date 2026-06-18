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

    show_retirement = st.session_state.get("show_retirement", False)

    _, btn_col = st.columns([8, 2])
    with btn_col:
        label = "Hide retirement" if show_retirement else "View retirement"
        if st.button(label, key="toggle_retirement", use_container_width=True):
            st.session_state["show_retirement"] = not show_retirement
            st.rerun()

    if not show_retirement:
        if not enriched.empty and "type" in enriched.columns:
            enriched = enriched[enriched["type"] != "retirement"]
        if not balances.empty and "type" in balances.columns:
            balances = balances[balances["type"] != "retirement"]

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
        st.markdown("**Value by institution**")
        inst_rows = []
        if not enriched.empty:
            for inst, grp in enriched.dropna(subset=["institution"]).groupby("institution"):
                mv = grp["market_value"].sum(skipna=True)
                if mv and mv > 0:
                    inst_rows.append({"institution": inst, "value": mv})
        if not balances.empty:
            for _, row in balances.dropna(subset=["balance"]).iterrows():
                if row["balance"] and row["balance"] > 0:
                    inst = row.get("institution") or "?"
                    inst_rows.append({"institution": inst, "value": float(row["balance"])})
        if inst_rows:
            inst_df = (
                pd.DataFrame(inst_rows)
                .groupby("institution")["value"].sum()
                .reset_index()
            )
            fig = px.pie(inst_df, names="institution", values="value", hole=0.55)
            fig.update_traces(textinfo="label+percent")
            fig.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                height=320,
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No data yet.")

    with right:
        st.markdown("**Value by account**")
        rows = []
        if not enriched.empty:
            for (inst, name), grp in enriched.dropna(subset=["institution", "name"]).groupby(
                ["institution", "name"], sort=False
            ):
                mv = grp["market_value"].sum(skipna=True)
                if mv and mv > 0:
                    rows.append({"label": f"{inst} · {name}", "value": mv, "category": "Holdings"})
        if not balances.empty:
            for _, row in balances.dropna(subset=["balance"]).iterrows():
                if not row["balance"]:
                    continue
                inst = row.get("institution") or "?"
                name = row.get("name") or row["account_id"]
                acct_type = row.get("type") or "brokerage"
                is_liability = acct_type == "credit_card"
                value = -abs(float(row["balance"])) if is_liability else float(row["balance"])
                category = "Liability" if is_liability else "Cash"
                rows.append({"label": f"{inst} · {name}", "value": value, "category": category})
        if rows:
            bar_df = (
                pd.DataFrame(rows)
                .groupby(["label", "category"], sort=False)["value"].sum()
                .reset_index()
            )
            total_by_label = bar_df.groupby("label")["value"].sum()
            bar_df["total"] = bar_df["label"].map(total_by_label)
            # Sort ascending so largest positive accounts sit at top;
            # liabilities (negative totals) fall to the bottom.
            bar_df = bar_df.sort_values("total", ascending=True).reset_index(drop=True)
            fig = px.bar(
                bar_df,
                x="value",
                y="label",
                color="category",
                orientation="h",
                color_discrete_map={"Holdings": BRAND["amber"], "Cash": BRAND["blue"], "Liability": BRAND["red"]},
                barmode="stack",
            )
            n_accts = len(bar_df["label"].unique())
            fig.update_layout(
                margin=dict(t=10, b=40, l=10, r=10),
                height=max(300, n_accts * 36 + 60),
                xaxis_title="Value ($)",
                yaxis_title="",
                legend=dict(orientation="h", y=-0.12, x=0, xanchor="left"),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No data yet.")

    if not balances.empty:
        st.markdown("---")
        st.markdown("**Cash & balances**")
        show = balances.copy()
        if "institution" in show.columns:
            show["Account"] = show["institution"].fillna("?") + " · " + show["name"].fillna("?")
        else:
            show["Account"] = show["account_id"]
        show = show.rename(columns={"balance": "Balance", "type": "Type"})

        # Format liabilities (credit cards) in accounting parentheses, e.g.
        # ($877.33), to signify money owed rather than money held.
        def _fmt_balance(row) -> str:
            amt = row["Balance"]
            if pd.isna(amt):
                return ""
            if row.get("Type") in ("credit_card",):
                return f"(${abs(amt):,.2f})"
            return f"${amt:,.2f}"

        if "Type" in show.columns:
            show["Balance"] = show.apply(_fmt_balance, axis=1)
        else:
            show["Balance"] = show["Balance"].map(lambda a: "" if pd.isna(a) else f"${a:,.2f}")

        cols = [c for c in ["Account", "Type", "Balance"] if c in show.columns]
        st.dataframe(
            show[cols],
            use_container_width=True,
            hide_index=True,
        )
