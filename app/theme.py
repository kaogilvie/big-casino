"""Brand theming — amber / black / white.

Colors sampled from the &KO logo (#FCA917 amber on #000000 black). The logo
itself is intentionally not used: this app holds personal financials and is not
an &KO product. Gains are green, losses red (finance convention).
"""
from __future__ import annotations

BRAND = {
    "amber": "#FCA917",
    "amber_soft": "#FFD37A",
    "black": "#000000",
    "near_black": "#0E0E0E",
    "panel": "#161616",
    "gray": "#3E3E3E",
    "muted": "#9A9A9A",
    "white": "#FFFFFF",
    "green": "#2ECC71",
    "red": "#FF5A4D",
    "blue": "#00B2FF",
}

_CSS = f"""
<style>
:root {{ --ko-amber: {BRAND['amber']}; }}
h1, h2, h3 {{ color: {BRAND['white']}; letter-spacing: 0.2px; }}
h1 span.ko-accent, .ko-accent {{ color: {BRAND['amber']}; }}
/* Custom metric cards (full control over sizing — Streamlit's st.metric
   truncates long currency values in narrow columns). */
.ko-metric {{
    background: {BRAND['panel']};
    border: 1px solid {BRAND['gray']};
    border-radius: 12px;
    padding: 14px 16px;
    height: 100%;
}}
.ko-metric-label {{ color: {BRAND['muted']}; font-size: 0.8rem; margin-bottom: 6px; }}
.ko-metric-value {{ color: {BRAND['white']}; font-weight: 700; font-size: 1.55rem; white-space: nowrap; }}
.ko-metric-delta {{ font-size: 0.85rem; margin-top: 6px; }}
section[data-testid="stSidebar"] {{ background: {BRAND['near_black']}; }}
hr {{ border-color: {BRAND['gray']}; }}
.stButton > button {{
    border: 1px solid {BRAND['amber']};
    color: {BRAND['amber']};
    background: transparent;
    font-weight: 600;
}}
.stButton > button:hover {{ background: {BRAND['amber']}; color: {BRAND['black']}; }}
</style>
"""


def install_plotly_template() -> None:
    import plotly.graph_objects as go
    import plotly.io as pio

    pio.templates["ko"] = go.layout.Template(
        layout=dict(
            paper_bgcolor=BRAND["black"],
            plot_bgcolor=BRAND["black"],
            font=dict(color=BRAND["white"]),
            colorway=[
                BRAND["amber"], BRAND["amber_soft"], BRAND["blue"],
                BRAND["green"], BRAND["red"], BRAND["muted"],
            ],
            xaxis=dict(gridcolor=BRAND["gray"], zerolinecolor=BRAND["gray"]),
            yaxis=dict(gridcolor=BRAND["gray"], zerolinecolor=BRAND["gray"]),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
        )
    )
    pio.templates.default = "ko"


def apply_theme(st) -> None:
    install_plotly_template()
    st.markdown(_CSS, unsafe_allow_html=True)
