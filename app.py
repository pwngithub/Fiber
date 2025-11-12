# app.py
import io
import re
import json
import datetime as dt
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

# Charts for the dashboard (interactive)
import altair as alt

# Static images for snapshot exports
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

# PDF export
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader  # <-- needed for drawImage

# =========================================================
# APP CONFIG + THEME
# =========================================================
st.set_page_config(page_title="Subscriber KPI Dashboard", page_icon="📶", layout="wide")
st.markdown("""
<style>
:root, .stApp { background-color: #0f1115; color: #e6e6e6; }
section[data-testid="stSidebar"] { background: #0c0e12; }
[data-testid="stMetric"] { background: #151924; border: 1px solid #1e2331; padding: 16px; border-radius: 14px; }
[data-testid="stMetricValue"] { color: #49d0ff; font-weight: 700; }
[data-testid="stMetricLabel"] { color: #b8c2cc; }
[data-testid="stMetricDelta"] { color: #a3ffd6; }
.stDataFrame, .stTable { background: #121620; }
</style>
""", unsafe_allow_html=True)

st.title("📶 Subscriber KPI Dashboard")
st.caption("Extracts ACT / COM / VIP counts & revenue from **Subscriber Counts v2** PDFs and visualizes KPIs. Upload one or multiple PDFs for trend lines.")

# =========================================================
# HELPERS
# =========================================================
def _clean_int(s: str) -> int:
    return int(s.replace(",", ""))

def _clean_amt(s: str) -> float:
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))

def _read_pdf_text(pdf_bytes: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)

def _extract_date_label(text: str, fallback_label: str) -> str:
    """Try to match 'Date: mm/dd/yyyy' in the PDF; return ISO date if found else fallback."""
    m = re.search(r"Date:\s*([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", text, flags=re.IGNORECASE)
    if m:
        m_, d_, y_ = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return dt.date(y_, m_, d_).isoformat()
        except Exception:
            pass
    return fallback_label

def parse_one_pdf(pdf_bytes: bytes):
    """
    Strategy (matches your file):
    - Find headers like: Customer Status ,"ACT","Active residential","3,727","3,727"
    - For each header, look BACKWARD ~300 chars to get the last $ amount before the header (status revenue)
    - Grand Total: "Total: <subs> <act> $<amt>"
    Returns: (grand, by_status, raw_text)
    """
    text = _read_pdf_text(pdf_bytes)
    compact = re.sub(r"\s+", " ", text)

    header_pat = re.compile(
        r'Customer Status\s*",\s*"(ACT|COM|VIP)"\s*,\s*"(Active residential|Active Commercial|VIP)"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"',
        re.IGNORECASE
    )
    starts = [(m.group(1).upper(), _clean_int(m.group(4)), m.start(), m.end())
              for m in header_pat.finditer(compact)]

    by_status = {"ACT": {"act": 0, "amt": 0.0}, "COM": {"act": 0, "amt": 0.0}, "VIP": {"act": 0, "amt": 0.0}}
    back_window = 300
    for status, act, s, e in starts:
        win = compact[max(0, s - back_window): s]
        dollars = list(re.finditer(r"\$([0-9][0-9,.\(\)-]*)", win))
        amt = _clean_amt(dollars[-1].group(1)) if dollars else 0.0
        by_status[status]["act"] += act
        by_status[status]["amt"] += amt

    grand = {"subs": None, "act": None, "amt": None}
    m_total = re.search(r"Total\s*:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)", compact, re.IGNORECASE)
    if m_total:
        grand["subs"] = _clean_int(m_total.group(1))
        grand["act"]  = _clean_int(m_total.group(2))
        grand["amt"]  = _clean_amt(m_total.group(3))
    else:
        grand["act"] = sum(v["act"] for v in by_status.values())
        grand["amt"] = sum(v["amt"] for v in by_status.values())

    return grand, by_status, text  # include raw text for date parse

def build_snapshot_figure(period_label: str, grand: Dict, by_status: Dict) -> Figure:
    """Static matplotlib figure (for PNG/PDF snapshot)."""
    fig: Figure = plt.figure(figsize=(10, 6), dpi=150)
    ax_title = fig.add_axes([0.05, 0.82, 0.9, 0.15]); ax_title.axis("off")
    ax_left = fig.add_axes([0.07, 0.15, 0.42, 0.60])
    ax_right = fig.add_axes([0.57, 0.15, 0.36, 0.60])

    avg_rev = (grand["amt"] / grand["act"]) if grand["act"] else 0.0
    act_rpc = by_status["ACT"]["amt"] / by_status["ACT"]["act"] if by_status["ACT"]["act"] else 0.0
    com_rpc = by_status["COM"]["amt"] / by_status["COM"]["act"] if by_status["COM"]["act"] else 0.0
    vip_rpc = by_status["VIP"]["amt"] / by_status["VIP"]["act"] if by_status["VIP"]["act"] else 0.0

    lines = [
        f"Subscriber KPI Snapshot — {period_label}",
        f"Grand Active: {grand['act']:,}   |   Grand Revenue: ${grand['amt']:,.2f}   |   Avg Rev / Active: ${avg_rev:,.2f}",
        (f"ACT: {by_status['ACT']['act']:,}  Rev ${by_status['ACT']['amt']:,.2f}  ARPU ${act_rpc:,.2f}   "
         f"COM: {by_status['COM']['act']:,}  Rev ${by_status['COM']['amt']:,.2f}  ARPU ${com_rpc:,.2f}   "
         f"VIP: {by_status['VIP']['act']:,}  Rev ${by_status['VIP']['amt']:,.2f}  ARPU ${vip_rpc:,.2f}")
    ]
    ax_title.text(0.01, 0.90, lines[0], fontsize=16, weight="bold")
    ax_title.text(0.01, 0.60, lines[1], fontsize=11)
    ax_title.text(0.01, 0.35, lines[2], fontsize=11)

    statuses = ["ACT", "COM", "VIP"]
    customers = [by_status[s]["act"] for s in statuses]
    ax_left.bar(statuses, customers)
    ax_left.set_title("Active Customers by Status")
    ax_left.set_ylabel("Customers")

    revs = [by_status[s]["amt"] for s in statuses]
    ax_right.pie(revs, labels=statuses, autopct="%1.1f%%", startangle=90)
    ax_right.set_title("Revenue Share")

    return fig

def export_snapshot_png(period_label: str, grand: Dict, by_status: Dict) -> bytes:
    fig = build_snapshot_figure(period_label, grand, by_status)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()

def export_snapshot_pdf(period_label: str, grand: Dict, by_status: Dict) -> bytes:
    """PDF: header + embedded PNG snapshot (ImageReader wrapper for drawImage)."""
    png_bytes = export_snapshot_png(period_label, grand, by_status)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    c.setTitle(f"Subscriber KPI Snapshot - {period_label}")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.75*inch, height - 1.0*inch, f"Subscriber KPI Snapshot — {period_label}")

    img_reader = ImageReader(io.BytesIO(png_bytes))
    img_w = width - 1.5*inch
    img_h = img_w * 0.55
    x = 0.75*inch
    y = height - 1.0*inch - img_h - 0.25*inch
    c.drawImage(img_reader, x, y, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()

# =========================================================
# INPUT (MULTI-FILE SUPPORT FOR TRENDS)
# =========================================================
uploaded_files = st.file_uploader(
    "Upload one or more 'Subscriber Counts v2' PDFs",
    type=["pdf"],
    accept_multiple_files=True
)

if not uploaded_files:
    st.info("Upload at least one PDF to see KPIs.")
    st.stop()

# Parse all files
records: List[Dict] = []
for i, up in enumerate(uploaded_files, start=1):
    try:
        grand, by_status, raw_text = parse_one_pdf(up.read())
        period = _extract_date_label(raw_text, fallback_label=up.name or f"File {i}")
        # Revenue per customer (per status)
        for s in ["ACT", "COM", "VIP"]:
            customers = by_status[s]["act"]
            by_status[s]["rpc"] = (by_status[s]["amt"] / customers) if customers else 0.0
        records.append({"period": period, "grand": grand, "by_status": by_status})
    except Exception as e:
        st.error(f"Failed to parse {up.name}: {e}")

# Sort by period if date-like
def _period_key(p: str):
    try:
        return dt.datetime.fromisoformat(p)
    except Exception:
        return p
records.sort(key=lambda r: _period_key(r["period"]))

# =========================================================
# CURRENT (LAST) REPORT — KPIs
# =========================================================
current = records[-1]
period_label = current["period"]
grand = current["grand"]
by_status = current["by_status"]

# --- KPI CARDS (Status) with ARPU inside each box
def metric_block(col, title, act, amt, rpc):
    # Value = Active subs; Delta line shows both Revenue and ARPU in one box
    col.metric(title, f"{act:,}", delta=f"Rev ${amt:,.2f} • ARPU ${rpc:,.2f}")

c1, c2, c3 = st.columns(3)
metric_block(c1, "ACT — Active Residential",
             by_status["ACT"]["act"], by_status["ACT"]["amt"], by_status["ACT"]["rpc"])
metric_block(c2, "COM — Active Commercial",
             by_status["COM"]["act"], by_status["COM"]["amt"], by_status["COM"]["rpc"])
metric_block(c3, "VIP",
             by_status["VIP"]["act"], by_status["VIP"]["amt"], by_status["VIP"]["rpc"])

# --- KPI CARDS (Overall)
o1, o2, o3 = st.columns(3)
avg_rev = (grand["amt"] / grand["act"]) if grand["act"] else 0
o1.metric("Grand Total Active", f"{grand['act']:,}")
o2.metric("Grand Total Revenue", f"${grand['amt']:,.2f}")
o3.metric("Avg Revenue / Active", f"${avg_rev:,.2f}")

st.divider()

# =========================================================
# CHARTS (CURRENT)
# =========================================================
st.subheader("📈 Visuals")
status_order = ["ACT", "COM", "VIP"]
chart_data = pd.DataFrame(
    [{"Status": s, "Revenue": by_status[s]["amt"], "Customers": by_status[s]["act"],
      "RPC": by_status[s]["rpc"]} for s in status_order]
)

left, right = st.columns([1, 1])
with left:
    st.markdown("**Revenue Share**")
    rev_chart = (
        alt.Chart(chart_data)
        .mark_arc(innerRadius=60)
        .encode(
            theta=alt.Theta("Revenue:Q", stack=True),
            color=alt.Color("Status:N"),
            tooltip=[alt.Tooltip("Status:N"),
                     alt.Tooltip("Revenue:Q", format="$.2f"),
                     alt.Tooltip("Customers:Q", format=",.0f"),
                     alt.Tooltip("RPC:Q", title="ARPU", format="$.2f")]
        )
        .properties(height=320)
    )
    st.altair_chart(rev_chart, use_container_width=True)

with right:
    st.markdown("**Active Customers by Status**")
    cust_chart = (
        alt.Chart(chart_data)
        .mark_bar()
        .encode(
            x=alt.X("Status:N", sort=status_order),
            y=alt.Y("Customers:Q"),
            tooltip=[alt.Tooltip("Status:N"),
                     alt.Tooltip("Customers:Q", format=",.0f"),
                     alt.Tooltip("Revenue:Q", format="$.2f"),
                     alt.Tooltip("RPC:Q", title="ARPU", format="$.2f")]
        )
        .properties(height=320)
    )
    st.altair_chart(cust_chart, use_container_width=True)

# =========================================================
# TRENDS (if multiple PDFs)
# =========================================================
if len(records) > 1:
    st.divider()
    st.subheader("📅 Trends (across uploaded PDFs)")
    trend_rows = []
    for r in records:
        p = r["period"]
        trend_rows.append({"Period": p, "Metric": "Grand Active", "Value": r["grand"]["act"]})
        trend_rows.append({"Period": p, "Metric": "Grand Revenue", "Value": r["grand"]["amt"]})
    trend_df = pd.DataFrame(trend_rows)

    colA, colB = st.columns(2)
    with colA:
        st.markdown("**Grand Active Over Time**")
        active_line = (
            alt.Chart(trend_df[trend_df["Metric"] == "Grand Active"])
            .mark_line(point=True)
            .encode(
                x=alt.X("Period:N", sort=None),
                y=alt.Y("Value:Q"),
                tooltip=["Period", alt.Tooltip("Value:Q", format=",.0f")]
            )
            .properties(height=300)
        )
        st.altair_chart(active_line, use_container_width=True)

    with colB:
        st.markdown("**Grand Revenue Over Time**")
        revenue_line = (
            alt.Chart(trend_df[trend_df["Metric"] == "Grand Revenue"])
            .mark_line(point=True)
            .encode(
                x=alt.X("Period:N", sort=None),
                y=alt.Y("Value:Q"),
                tooltip=["Period", alt.Tooltip("Value:Q", format="$.2f")]
            )
            .properties(height=300)
        )
        st.altair_chart(revenue_line, use_container_width=True)

# =========================================================
# TABLE (COLLAPSED) + EXPORTS
# =========================================================
with st.expander("Totals by Status (collapsed)", expanded=False):
    df = pd.DataFrame(
        [{"Status": s,
          "Active Sub Count": by_status[s]["act"],
          "Revenue": by_status[s]["amt"],
          "ARPU": by_status[s]["rpc"]} for s in status_order]
    )
    st.dataframe(df.style.format({"Revenue": "${:,.2f}", "ARPU": "${:,.2f}"}), use_container_width=True)

st.subheader("Export")
colx, coly, colz = st.columns(3)
colx.download_button(
    "Download CSV",
    df.to_csv(index=False).encode("utf-8"),
    "status_totals.csv",
    "text/csv"
)
coly.download_button(
    "Download JSON",
    json.dumps(df.to_dict(orient="records"), indent=2),
    "status_totals.json",
    "application/json"
)

# Snapshot (PNG / PDF)
png_bytes = export_snapshot_png(period_label, grand, by_status)
pdf_bytes = export_snapshot_pdf(period_label, grand, by_status)
colz.download_button(
    "Download KPI Snapshot (PNG)",
    data=png_bytes,
    file_name=f"kpi_snapshot_{period_label}.png",
    mime="image/png"
)
st.download_button(
    "Download KPI Snapshot (PDF)",
    data=pdf_bytes,
    file_name=f"kpi_snapshot_{period_label}.pdf",
    mime="application/pdf"
)

st.caption("Note: PDF snapshot includes the same KPIs and mini charts rendered as a static image.")
