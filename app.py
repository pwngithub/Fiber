# app.py
import io
import re
import json
import datetime as dt
from typing import Dict, List

import pandas as pd
import streamlit as st
import altair as alt
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader

# =========================================================
# APP CONFIG + THEME
# =========================================================
st.set_page_config(page_title="FTTH Dashboard", page_icon="📶", layout="wide")
st.markdown("""
<style>
:root, .stApp { background-color: #0f1115; color: #e6e6e6; }
section[data-testid="stSidebar"] { background: #0c0e12; }
[data-testid="stMetric"] { background: #151924; border: 1px solid #1e2331; padding: 16px; border-radius: 14px; }
[data-testid="stMetricValue"] { color: #49d0ff; font-weight: 700; }
[data-testid="stMetricLabel"] { color: #b8c2cc; }
[data-testid="stMetricDelta"] { color: #a3ffd6; }
.stDataFrame, .stTable { background: #121620; }
.kpi-box {background-color:#151924;border:1px solid #1e2331;border-radius:14px;
          padding:16px;margin-bottom:5px;text-align:center;}
.kpi-title {margin:0;font-size:16px;color:#b8c2cc;}
.kpi-value {margin:0;font-size:28px;font-weight:700;color:#49d0ff;}
.kpi-sub {margin:4px 0 0 0;font-size:14px;color:#a3ffd6;}
</style>
""", unsafe_allow_html=True)

st.title("📶 FTTH Dashboard")
st.caption("Extracts ACT / COM / VIP counts & revenue from **Subscriber Counts v2** PDFs and visualizes KPIs for FTTH services.")

# =========================================================
# HELPERS
# =========================================================
def _clean_int(s): return int(s.replace(",", ""))
def _clean_amt(s): return float(s.replace(",", "").replace("(", "-").replace(")", ""))

def _read_pdf_text(pdf_bytes: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)

def _extract_date_label(text: str, fallback_label: str) -> str:
    m = re.search(r"Date:\s*([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", text)
    if m:
        try: return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
        except: pass
    return fallback_label

def parse_one_pdf(pdf_bytes: bytes):
    text = _read_pdf_text(pdf_bytes)
    compact = re.sub(r"\s+", " ", text)
    header_pat = re.compile(
        r'Customer Status\s*",\s*"(ACT|COM|VIP)"\s*,\s*"(Active residential|Active Commercial|VIP)"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"',
        re.IGNORECASE)
    starts = [(m.group(1).upper(), _clean_int(m.group(4)), m.start(), m.end())
              for m in header_pat.finditer(compact)]

    by_status = {"ACT": {"act": 0, "amt": 0.0}, "COM": {"act": 0, "amt": 0.0}, "VIP": {"act": 0, "amt": 0.0}}
    for status, act, s, e in starts:
        win = compact[max(0, s - 300): s]
        dollars = list(re.finditer(r"\$([0-9][0-9,.\(\)-]*)", win))
        amt = _clean_amt(dollars[-1].group(1)) if dollars else 0.0
        by_status[status]["act"] += act
        by_status[status]["amt"] += amt

    m_total = re.search(r"Total\s*:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)", compact)
    if m_total:
        grand = {
            "subs": _clean_int(m_total.group(1)),
            "act": _clean_int(m_total.group(2)),
            "amt": _clean_amt(m_total.group(3))
        }
    else:
        grand = {"act": sum(v["act"] for v in by_status.values()),
                 "amt": sum(v["amt"] for v in by_status.values())}
    return grand, by_status, text

def build_snapshot_figure(period_label, grand, by_status):
    fig: Figure = plt.figure(figsize=(10, 6), dpi=150)
    ax_title = fig.add_axes([0.05, 0.82, 0.9, 0.15]); ax_title.axis("off")
    ax_left = fig.add_axes([0.07, 0.15, 0.42, 0.60])
    ax_right = fig.add_axes([0.57, 0.15, 0.36, 0.60])

    overall_arpu = (grand["amt"]/grand["act"]) if grand["act"] else 0
    act_rpc = by_status["ACT"]["amt"]/by_status["ACT"]["act"] if by_status["ACT"]["act"] else 0
    com_rpc = by_status["COM"]["amt"]/by_status["COM"]["act"] if by_status["COM"]["act"] else 0
    vip_rpc = by_status["VIP"]["amt"]/by_status["VIP"]["act"] if by_status["VIP"]["act"] else 0

    lines = [
        f"FTTH Dashboard — {period_label}",
        f"FTTH Customers: {grand['act']:,}   |   Total Revenue: ${grand['amt']:,.2f}   |   ARPU: ${overall_arpu:,.2f}",
        (f"ACT: {by_status['ACT']['act']:,} Rev ${by_status['ACT']['amt']:,.2f} ARPU ${act_rpc:,.2f}   "
         f"COM: {by_status['COM']['act']:,} Rev ${by_status['COM']['amt']:,.2f} ARPU ${com_rpc:,.2f}   "
         f"VIP: {by_status['VIP']['act']:,} Rev ${by_status['VIP']['amt']:,.2f} ARPU ${vip_rpc:,.2f}")
    ]
    ax_title.text(0.01, 0.9, lines[0], fontsize=16, weight="bold")
    ax_title.text(0.01, 0.6, lines[1], fontsize=11)
    ax_title.text(0.01, 0.35, lines[2], fontsize=11)

    statuses = ["ACT","COM","VIP"]
    ax_left.bar(statuses, [by_status[s]["act"] for s in statuses])
    ax_left.set_title("Active Customers by Status"); ax_left.set_ylabel("Customers")
    ax_right.pie([by_status[s]["amt"] for s in statuses], labels=statuses, autopct="%1.1f%%")
    ax_right.set_title("Revenue Share")
    return fig

def export_snapshot_png(period_label, grand, by_status):
    fig = build_snapshot_figure(period_label, grand, by_status)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()

def export_snapshot_pdf(period_label, grand, by_status):
    png_bytes = export_snapshot_png(period_label, grand, by_status)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    c.setTitle(f"FTTH Dashboard - {period_label}")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.75*inch, height-1.0*inch, f"FTTH Dashboard — {period_label}")
    img_reader = ImageReader(io.BytesIO(png_bytes))
    img_w = width-1.5*inch; img_h = img_w*0.55
    c.drawImage(img_reader, 0.75*inch, height-1.0*inch-img_h-0.25*inch,
                width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
    c.showPage(); c.save(); buf.seek(0)
    return buf.getvalue()

# =========================================================
# INPUT / PARSE
# =========================================================
uploaded_files = st.file_uploader("Upload 'Subscriber Counts v2' PDFs", type=["pdf"], accept_multiple_files=True)
if not uploaded_files:
    st.info("Upload at least one PDF to view FTTH KPIs."); st.stop()

records=[]
for i, up in enumerate(uploaded_files, start=1):
    grand, by_status, raw = parse_one_pdf(up.read())
    period=_extract_date_label(raw, fallback_label=up.name or f"File {i}")
    for s in ["ACT","COM","VIP"]:
        c_=by_status[s]["act"]
        by_status[s]["rpc"]=(by_status[s]["amt"]/c_) if c_ else 0
    records.append({"period":period,"grand":grand,"by_status":by_status})
records.sort(key=lambda r: r["period"])

# =========================================================
# CURRENT REPORT
# =========================================================
r=records[-1]; grand=r["grand"]; by_status=r["by_status"]; period_label=r["period"]
overall_arpu=(grand["amt"]/grand["act"]) if grand["act"] else 0

# --- TOP KPI ROW (Blue for Customers, Green for Revenue & ARPU values) ---
html_top = f"""
<div style="display:flex;gap:20px;justify-content:space-between;margin-bottom:10px;">
    <div style="flex:1;background-color:#151924;border:1px solid #1e2331;
                border-radius:14px;padding:16px;text-align:center;">
        <p style="margin:0;font-size:16px;color:#b8c2cc;">FTTH Customers</p>
        <p style="margin:0;font-size:28px;font-weight:700;color:#49d0ff;">{grand['act']:,}</p>
    </div>
    <div style="flex:1;background-color:#151924;border:1px solid #1e2331;
                border-radius:14px;padding:16px;text-align:center;">
        <p style="margin:0;font-size:16px;color:#b8c2cc;">Total Revenue</p>
        <p style="margin:0;font-size:28px;font-weight:700;color:#3ddc97;">${grand['amt']:,.2f}</p>
    </div>
    <div style="flex:1;background-color:#151924;border:1px solid #1e2331;
                border-radius:14px;padding:16px;text-align:center;">
        <p style="margin:0;font-size:16px;color:#b8c2cc;">ARPU</p>
        <p style="margin:0;font-size:28px;font-weight:700;color:#3ddc97;">${overall_arpu:,.2f}</p>
    </div>
</div>
"""
st.markdown(html_top, unsafe_allow_html=True)
st.divider()

# --- KPI BOXES (ACT/COM/VIP) ---
def metric_box(col,title,act,amt,rpc):
    html=f"""<div class='kpi-box'>
        <p class='kpi-title'>{title}</p>
        <p class='kpi-value'>{act:,}</p>
        <p class='kpi-sub'>Rev ${amt:,.2f} • ARPU ${rpc:,.2f}</p></div>"""
    col.markdown(html,unsafe_allow_html=True)

c1,c2,c3=st.columns(3)
metric_box(c1,"ACT — Active Residential",by_status["ACT"]["act"],by_status["ACT"]["amt"],by_status["ACT"]["rpc"])
metric_box(c2,"COM — Active Commercial",by_status["COM"]["act"],by_status["COM"]["amt"],by_status["COM"]["rpc"])
metric_box(c3,"VIP",by_status["VIP"]["act"],by_status["VIP"]["amt"],by_status["VIP"]["rpc"])

# =========================================================
# CHARTS
# =========================================================
st.subheader("📈 Visuals")
chart=pd.DataFrame([{"Status":s,"Revenue":by_status[s]["amt"],"Customers":by_status[s]["act"],"ARPU":by_status[s]["rpc"]}
                    for s in ["ACT","COM","VIP"]])
l,r2=st.columns(2)
with l:
    st.markdown("**Revenue Share**")
    st.altair_chart(alt.Chart(chart).mark_arc(innerRadius=60)
                    .encode(theta="Revenue:Q",color="Status:N",
                            tooltip=["Status","Revenue","Customers","ARPU"]),
                    use_container_width=True)
with r2:
    st.markdown("**Active Customers by Status**")
    st.altair_chart(alt.Chart(chart).mark_bar()
                    .encode(x="Status:N",y="Customers:Q",tooltip=["Status","Customers","Revenue","ARPU"]),
                    use_container_width=True)

# =========================================================
# EXPORTS
# =========================================================
png_bytes=export_snapshot_png(period_label,grand,by_status)
pdf_bytes=export_snapshot_pdf(period_label,grand,by_status)
col1,col2=st.columns(2)
col1.download_button("Download Snapshot (PNG)",png_bytes,f"ftth_snapshot_{period_label}.png","image/png")
col2.download_button("Download Snapshot (PDF)",pdf_bytes,f"ftth_snapshot_{period_label}.pdf","application/pdf")
st.caption("FTTH Dashboard snapshot includes KPIs and charts as a static image.")
