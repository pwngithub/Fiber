# app.py
import io
import re
import json
import os
import base64
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
import requests

# =========================================================
# APP CONFIG + THEME
# =========================================================
st.set_page_config(page_title="FTTH Dashboard", page_icon="📶", layout="wide")
st.markdown("""
<style>
/* -------------------------------------------------
   1. CSS VARIABLES – dark by default
   ------------------------------------------------- */
:root {
    /* Backgrounds */
    --bg-app:        #0f1115;
    --bg-sidebar:    #0c0e12;
    --bg-card:       #151924;
    --border-card:   #1e2331;

    /* Text */
    --text-primary:  #e6e6e6;
    --text-muted:    #b8c2cc;

    /* Accents */
    --accent-blue:   #49d0ff;   /* bright cyan-blue */
    --accent-green:  #3ddc97;   /* vivid mint */
}

/* -------------------------------------------------
   2. LIGHT-MODE OVERRIDE (Streamlit adds .light)
   ------------------------------------------------- */
.stApp.light,
.light {
    /* Backgrounds – clean, soft white */
    --bg-app:        #fafafa;
    --bg-sidebar:    #f0f2f6;
    --bg-card:       #ffffff;
    --border-card:   #dee2e6;

    /* Text – high contrast */
    --text-primary:  #212529;
    --text-muted:    #6c757d;

    /* Accents – Bootstrap-inspired, but a touch more vibrant */
    --accent-blue:   #0d6efd;   /* Bootstrap primary */
    --accent-green:  #198754;   /* Bootstrap success */
}

/* -------------------------------------------------
   3. GLOBAL ELEMENTS
   ------------------------------------------------- */
.stApp,
section[data-testid="stSidebar"] {
    background: var(--bg-app);
    color:      var(--text-primary);
}
section[data-testid="stSidebar"] {
    background: var(--bg-sidebar);
}

/* -------------------------------------------------
   4. METRICS & CARDS
   ------------------------------------------------- */
[data-testid="stMetric"] {
    background: var(--bg-card);
    border: 1px solid var(--border-card);
    padding: 16px;
    border-radius: 14px;
}
[data-testid="stMetricValue"] { color: var(--accent-blue); font-weight: 700; }
[data-testid="stMetricLabel"] { color: var(--text-muted); }
[data-testid="stMetricDelta"] { color: var(--accent-green); }

.stDataFrame,
.stTable { background: var(--bg-card); }

/* -------------------------------------------------
   5. KPI BOXES (ACT / COM / VIP)
   ------------------------------------------------- */
.kpi-box {
    background: var(--bg-card);
    border: 1px solid var(--border-card);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 5px;
    text-align: center;
}
.kpi-title { margin:0; font-size:16px; color:var(--text-muted); }
.kpi-value { margin:0; font-size:28px; font-weight:700; color:var(--accent-blue); }
.kpi-sub   { margin:4px 0 0 0; font-size:14px; }
.kpi-sub span { color:var(--accent-green); }

/* -------------------------------------------------
   6. TOP KPI ROW (flex boxes)
   ------------------------------------------------- */
div[data-testid="column"] > div > div > div > div {
    background: var(--bg-card);
    border: 1px solid var(--border-card);
}

/* -------------------------------------------------
   7. ALTAIR / VEGA TEXT (readability in both modes)
   ------------------------------------------------- */
.vega-bind-name,
.vega-bind,
.vega-bind input,
.vega-bind select,
.vega-bind option,
text,
.mark-text,
.mark-label {
    fill: var(--text-primary) !important;
    color: var(--text-primary) !important;
}

/* -------------------------------------------------
   8. OPTIONAL: subtle shadow for cards in light mode
   ------------------------------------------------- */
.stApp.light .kpi-box,
.stApp.light [data-testid="stMetric"] {
    box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}
</style>
""", unsafe_allow_html=True)
st.title("📶 FTTH Dashboard")
st.caption("Extracts ACT / COM / VIP counts & revenue from **Subscriber Counts v2** PDFs and visualizes KPIs for FTTH services.")

# =========================================================
# HELPERS
# =========================================================
def _clean_int(s): 
    return int(s.replace(",", ""))

def _clean_amt(s): 
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))

def _read_pdf_text(pdf_bytes: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)

def _extract_date_label(text: str, fallback_label: str) -> str:
    m = re.search(r"Date:\s*([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", text)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
        except Exception:
            pass
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
        grand = {
            "act": sum(v["act"] for v in by_status.values()),
            "amt": sum(v["amt"] for v in by_status.values())
        }
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
# GITHUB HELPERS
# =========================================================
def get_github_config():
    try:
        gh_cfg = st.secrets["github"]
        token = gh_cfg["token"]
        repo = gh_cfg["repo"]          # e.g. "pwngithub/fiber"
        branch = gh_cfg.get("branch", "main")
        remote_prefix = gh_cfg.get("file_path", "fiber/")
        remote_prefix = remote_prefix.rstrip("/") + "/"
        return token, repo, branch, remote_prefix
    except Exception:
        st.warning("GitHub secrets not configured correctly under [github].")
        return None, None, None, None

def save_upload_to_local_and_github(filename: str, file_bytes: bytes):
    """Save uploaded file to local 'fiber' folder AND push to GitHub."""
    # 1) Save locally
    local_folder = "fiber"
    os.makedirs(local_folder, exist_ok=True)
    local_path = os.path.join(local_folder, filename)

    try:
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        st.success(f"Saved file locally: {local_path}")
    except Exception as e:
        st.error(f"Failed to save file locally: {e}")

    # 2) Push to GitHub
    token, repo, branch, remote_prefix = get_github_config()
    if not token or not repo:
        return

    remote_path = remote_prefix + filename
    api_url = f"https://api.github.com/repos/{repo}/contents/{remote_path}"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json"
    }
    content_b64 = base64.b64encode(file_bytes).decode("utf-8")

    # Check if file exists
    sha = None
    get_resp = requests.get(api_url, headers=headers)
    if get_resp.status_code == 200:
        sha = get_resp.json().get("sha")

    payload = {
        "message": f"Add/update {filename} via FTTH Dashboard",
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    put_resp = requests.put(api_url, headers=headers, json=payload)

    if put_resp.status_code in (200, 201):
        st.success(f"Pushed to GitHub: {repo}/{remote_path}")
    else:
        st.error(f"GitHub upload failed ({put_resp.status_code}): {put_resp.text}")

def list_github_files_in_fiber():
    """List files in the configured GitHub fiber/ directory."""
    token, repo, branch, remote_prefix = get_github_config()
    if not token or not repo:
        return []

    # remote_prefix like "fiber/"; for contents API, use just the path without trailing slash
    path = remote_prefix.rstrip("/")
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json"
    }
    resp = requests.get(api_url, headers=headers)
    if resp.status_code != 200:
        st.error(f"Failed to list GitHub files ({resp.status_code}): {resp.text}")
        return []

    items = resp.json()
    files = [item for item in items if item.get("type") == "file"]
    return files

def load_github_file_from_github(file_info) -> bytes:
    """Download a file from GitHub given an item from the contents API."""
    download_url = file_info.get("download_url")
    if not download_url:
        st.error("No download URL found for selected file.")
        return b""
    resp = requests.get(download_url)
    if resp.status_code != 200:
        st.error(f"Failed to download file from GitHub ({resp.status_code}): {resp.text}")
        return b""
    return resp.content

# =========================================================
# INPUT / PARSE
# =========================================================
source_choice = st.radio(
    "Choose data source",
    ["Upload new PDFs", "Pick from GitHub"],
    horizontal=True
)

records: List[Dict] = []

if source_choice == "Upload new PDFs":
    uploaded_files = st.file_uploader(
        "Upload 'Subscriber Counts v2' PDFs",
        type=["pdf"],
        accept_multiple_files=True
    )

    if not uploaded_files:
        st.info("Upload at least one PDF to view FTTH KPIs.")
        st.stop()

    for i, up in enumerate(uploaded_files, start=1):
        pdf_bytes = up.read()
        if not pdf_bytes:
            continue

        # Save this upload to local fiber/ and GitHub
        save_upload_to_local_and_github(up.name, pdf_bytes)

        # Parse as before
        grand, by_status, raw = parse_one_pdf(pdf_bytes)
        period = _extract_date_label(raw, fallback_label=up.name or f"File {i}")
        for s in ["ACT", "COM", "VIP"]:
            c_ = by_status[s]["act"]
            by_status[s]["rpc"] = (by_status[s]["amt"]/c_) if c_ else 0
        records.append({"period": period, "grand": grand, "by_status": by_status})

else:  # Pick from GitHub
    gh_files = list_github_files_in_fiber()
    if not gh_files:
        st.info("No files found in GitHub fiber/ directory.")
        st.stop()

    # Filter to PDFs only
    pdf_items = [f for f in gh_files if f.get("name", "").lower().endswith(".pdf")]
    if not pdf_items:
        st.info("No PDF files found in GitHub fiber/ directory.")
        st.stop()

    name_to_item = {f["name"]: f for f in pdf_items}
    options = list(name_to_item.keys())
    selected_names = st.multiselect(
        "Select one or more PDFs from GitHub fiber/ directory",
        options=options,
        default=options[:1] if options else None
    )

    if not selected_names:
        st.info("Select at least one PDF from GitHub to continue.")
        st.stop()

    for i, name in enumerate(selected_names, start=1):
        file_info = name_to_item[name]
        pdf_bytes = load_github_file_from_github(file_info)
        if not pdf_bytes:
            continue
        grand, by_status, raw = parse_one_pdf(pdf_bytes)
        period = _extract_date_label(raw, fallback_label=name)
        for s in ["ACT", "COM", "VIP"]:
            c_ = by_status[s]["act"]
            by_status[s]["rpc"] = (by_status[s]["amt"]/c_) if c_ else 0
        records.append({"period": period, "grand": grand, "by_status": by_status})

if not records:
    st.error("No valid records loaded from the selected source.")
    st.stop()

# Sort by period (string; ISO dates sort nicely)
records.sort(key=lambda r: r["period"])

# =========================================================
# CURRENT REPORT
# =========================================================
r = records[-1]
grand = r["grand"]
by_status = r["by_status"]
period_label = r["period"]
overall_arpu = (grand["amt"]/grand["act"]) if grand["act"] else 0

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

# --- KPI BOXES (ACT/COM/VIP) with green revenue + ARPU values ---
def metric_box(col, title, act, amt, rpc):
    html = f"""
    <div class='kpi-box'>
        <p class='kpi-title'>{title}</p>
        <p class='kpi-value'>{act:,}</p>
        <p class='kpi-sub'>
            <span style='color:#3ddc97;'>Rev ${amt:,.2f}</span> • 
            <span style='color:#3ddc97;'>ARPU ${rpc:,.2f}</span>
        </p>
    </div>
    """
    col.markdown(html, unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
metric_box(c1, "ACT — Active Residential", by_status["ACT"]["act"], by_status["ACT"]["amt"], by_status["ACT"]["rpc"])
metric_box(c2, "COM — Active Commercial", by_status["COM"]["act"], by_status["COM"]["amt"], by_status["COM"]["rpc"])
metric_box(c3, "VIP", by_status["VIP"]["act"], by_status["VIP"]["amt"], by_status["VIP"]["rpc"])

# =========================================================
# CHARTS
# =========================================================
st.subheader("📈 Visuals")

chart = pd.DataFrame([
    {"Status": s, "Revenue": by_status[s]["amt"], "Customers": by_status[s]["act"], "ARPU": by_status[s]["rpc"]}
    for s in ["ACT", "COM", "VIP"]
])

# Pioneer palette
color_scale = alt.Scale(
    domain=["ACT", "COM", "VIP"],
    range=["#49d0ff", "#3ddc97", "#b8c2cc"]
)

l, r2 = st.columns(2)

with l:
    st.markdown("**Revenue Share**")

    pie_base = (
        alt.Chart(chart)
        .transform_joinaggregate(total="sum(Revenue)")
        .transform_calculate(pct="datum.Revenue / datum.total")
        .properties(width=300, height=300)
    )

    pie_arcs = (
        pie_base
        .mark_arc(innerRadius=60)
        .encode(
            theta="Revenue:Q",
            color=alt.Color("Status:N", scale=color_scale, legend=None),
            tooltip=[
                alt.Tooltip("Status:N"),
                alt.Tooltip("Revenue:Q", format="$.2f"),
                alt.Tooltip("Customers:Q", format=",.0f"),
                alt.Tooltip("ARPU:Q", format="$.2f"),
                alt.Tooltip("pct:Q", format=".1%", title="Share")
            ]
        )
    )

    pie_labels = (
        pie_base
        .mark_text(radius=95, fontSize=12, fontWeight="bold", color="white")
        .encode(
            theta="Revenue:Q",
            text=alt.Text("label:N")
        )
        .transform_calculate(label="datum.Status + ' ' + format(datum.pct, '.1%')")
    )

    st.altair_chart(pie_arcs + pie_labels, use_container_width=True)

with r2:
    st.markdown("**Active Customers by Status**")

    base = alt.Chart(chart).properties(width=300, height=300)

    # Blue fill with green outline
    bars = (
        base
        .mark_bar(
            color="#49d0ff",
            stroke="#3ddc97",
            strokeWidth=2,
            cornerRadiusTopLeft=6,
            cornerRadiusTopRight=6
        )
        .encode(
            x=alt.X("Status:N", sort=["ACT", "COM", "VIP"]),
            y=alt.Y("Customers:Q"),
            tooltip=[
                alt.Tooltip("Status:N"),
                alt.Tooltip("Customers:Q", format=",.0f"),
                alt.Tooltip("Revenue:Q", format="$.2f"),
                alt.Tooltip("ARPU:Q", format="$.2f")
            ]
        )
    )

    # Value labels on top of bars
    labels = (
        base
        .mark_text(dy=-6, fontSize=12, color="#e6e6e6", fontWeight="bold")
        .encode(
            x=alt.X("Status:N", sort=["ACT", "COM", "VIP"]),
            y=alt.Y("Customers:Q"),
            text=alt.Text("Customers:Q", format=",.0f")
        )
    )

    st.altair_chart(bars + labels, use_container_width=True)

# =========================================================
# EXPORTS
# =========================================================
png_bytes = export_snapshot_png(period_label, grand, by_status)
pdf_bytes = export_snapshot_pdf(period_label, grand, by_status)
col1, col2 = st.columns(2)
col1.download_button("Download Snapshot (PNG)", png_bytes, f"ftth_snapshot_{period_label}.png", "image/png")
col2.download_button("Download Snapshot (PDF)", pdf_bytes, f"ftth_snapshot_{period_label}.pdf", "application/pdf")
st.caption("FTTH Dashboard snapshot includes KPIs and charts as a static image.")
