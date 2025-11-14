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
# APP CONFIG + BLACK THEME
# =========================================================
st.set_page_config(page_title="FTTH Dashboard", page_icon="signal_cellular_alt", layout="wide")

st.markdown("""
<style>
/* -------------------------------------------------
   1. CSS VARIABLES - BLACK theme (forced)
   ------------------------------------------------- */
:root, .stApp, .stApp * {
    --bg-app: #000000 !important;
    --bg-sidebar: #0a0a0a !important;
    --bg-card: #111111 !important;
    --border-card: #222222 !important;
    --text-primary: #e6e6e6 !important;
    --text-muted: #aaaaaa !important;
    --accent-blue: #49d0ff !important;
    --accent-green: #3ddc97 !important;
}
/* -------------------------------------------------
   2. FORCE BLACK EVEN IN LIGHT MODE
   ------------------------------------------------- */
.stApp.light, .light, .light * {
    --bg-app: #000000 !important;
    --bg-sidebar: #0a0a0a !important;
    --bg-card: #111111 !important;
    --border-card: #222222 !important;
    --text-primary: #e6e6e6 !important;
    --text-muted: #aaaaaa !important;
}
/* -------------------------------------------------
   3. GLOBAL BACKGROUND & TEXT
   ------------------------------------------------- */
.stApp, body, .main, section, .block-container {
    background: #000000 !important;
    color: #e6e6e6 !important;
}
section[data-testid="stSidebar"] {
    background: #0a0a0a !important;
}
/* -------------------------------------------------
   4. CARDS & KPI BOXES
   ------------------------------------------------- */
[data-testid="stMetric"],
.stDataFrame,
.stTable {
    background: #111111 !important;
    border: 1px solid #222222 !important;
    color: #e6e6e6 !important;
}
/* -------------------------------------------------
   5. ALTAIR / VEGA - FORCE BLACK CANVAS
   ------------------------------------------------- */
.vega-bind,
.vega-visualization,
.vega-embed,
.vega-container,
.vega-view,
.vega-plot,
.vega-scenegraph,
.vega-canvas,
.vega-background,
text,
.mark-text,
.mark-label,
.vega-title,
.vega-axis-label,
.vega-axis-title {
    background: #111111 !important;
    fill: #e6e6e6 !important;
    color: #e6e6e6 !important;
    stroke: #e6e6e6 !important;
}
.vega-embed > div,
.vega-embed svg,
.vega-embed canvas {
    background: #111111 !important;
}
/* -------------------------------------------------
   6. DOWNLOAD BUTTON AREA
   ------------------------------------------------- */
.css-1y0t6ff,
.css-1v0mbdj {
    background: #111111 !important;
    border: 1px solid #222222 !important;
}
</style>
""", unsafe_allow_html=True)

st.title("FTTH Dashboard")
st.caption("Extracts ACT / COM / VIP counts & revenue from PDFs and visualizes KPIs for FTTH services.")

# =========================================================
# ALTAIR BLACK THEME (GLOBAL)
# =========================================================
def black_theme():
    return {
        'config': {
            'background': '#111111',
            'title': {'color': '#e6e6e6'},
            'axis': {
                'labelColor': '#e6e6e6',
                'titleColor': '#e6e6e6',
                'gridColor': '#222222',
                'domainColor': '#222222'
            },
            'legend': {'labelColor': '#e6e6e6', 'titleColor': '#e6e6e6'},
            'view': {'stroke': '#222222'}
        }
    }
alt.themes.register('black_theme', black_theme)
alt.themes.enable('black_theme')

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

# =========================================================
# SNAPSHOT FIGURE - FIXED: NO CRASH ON ZERO REVENUE
# =========================================================
def build_snapshot_figure(period_label, grand, by_status):
    fig = plt.figure(figsize=(10, 6), dpi=150, facecolor='#111111')
    fig.patch.set_facecolor('#111111')

    ax_title = fig.add_axes([0.05, 0.82, 0.9, 0.15]); ax_title.axis("off")
    ax_left  = fig.add_axes([0.07, 0.15, 0.42, 0.60])
    ax_right = fig.add_axes([0.57, 0.15, 0.36, 0.60])

    for ax in (ax_left, ax_right):
        ax.set_facecolor('#111111')
        ax.tick_params(colors='#e6e6e6')
        ax.xaxis.label.set_color('#e6e6e6')
        ax.yaxis.label.set_color('#e6e6e6')
        for spine in ax.spines.values():
            spine.set_color('#222222')

    overall_arpu = (grand["amt"]/grand["act"]) if grand["act"] else 0
    act_rpc = by_status["ACT"]["amt"]/by_status["ACT"]["act"] if by_status["ACT"]["act"] else 0
    com_rpc = by_status["COM"]["amt"]/by_status["COM"]["act"] if by_status["COM"]["act"] else 0
    vip_rpc = by_status["VIP"]["amt"]/by_status["VIP"]["act"] if by_status["VIP"]["act"] else 0

    lines = [
        f"FTTH Dashboard — {period_label}",
        f"FTTH Customers: {grand['act']:,} | Total Revenue: ${grand['amt']:,.2f} | ARPU: ${overall_arpu:,.2f}",
        f"ACT: {by_status['ACT']['act']:,} Rev ${by_status['ACT']['amt']:,.2f} ARPU ${act_rpc:,.2f} "
        f"COM: {by_status['COM']['act']:,} Rev ${by_status['COM']['amt']:,.2f} ARPU ${com_rpc:,.2f} "
        f"VIP: {by_status['VIP']['act']:,} Rev ${by_status['VIP']['amt']:,.2f} ARPU ${vip_rpc:,.2f}"
    ]

    ax_title.text(0.01, 0.9, lines[0], fontsize=16, weight="bold", color='#e6e6e6')
    ax_title.text(0.01, 0.6, lines[1], fontsize=11, color='#e6e6e6')
    ax_title.text(0.01, 0.35, lines[2], fontsize=11, color='#e6e6e6')

    statuses = ["ACT", "COM", "VIP"]
    ax_left.bar(statuses, [by_status[s]["act"] for s in statuses], color='#49d0ff')
    ax_left.set_title("Active Customers by Status", color='#e6e6e6')
    ax_left.set_ylabel("Customers", color='#e6e6e6')

    rev_values = [by_status[s]["amt"] for s in statuses]
    labels = statuses
    colors = ['#49d0ff', '#3ddc97', '#aaaaaa']

    filtered = [(r, l, c) for r, l, c in zip(rev_values, labels, colors) if r > 0]
    if filtered:
        rev_filtered, labels_filtered, colors_filtered = zip(*filtered)
        wedges, texts, autotexts = ax_right.pie(
            rev_filtered,
            labels=labels_filtered,
            autopct="%1.1f%%",
            colors=colors_filtered,
            textprops={'color': '#e6e6e6', 'weight': 'normal', 'size': 11}
        )
        for autotext in autotexts:
            autotext.set_color('#000000')
    else:
        ax_right.text(0.5, 0.5, "No Revenue", transform=ax_right.transAxes,
                      ha='center', va='center', color='#666666', fontsize=12)

    ax_right.set_title("Revenue Share", color='#e6e6e6')

    return fig

# =========================================================
# EXPORT FUNCTIONS - BLACK PNG & PDF
# =========================================================
def export_snapshot_png(period_label, grand, by_status):
    fig = build_snapshot_figure(period_label, grand, by_status)
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        bbox_inches="tight",
        facecolor='#111111',
        edgecolor='none',
        dpi=150
    )
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()

def export_snapshot_pdf(period_label, grand, by_status):
    png_bytes = export_snapshot_png(period_label, grand, by_status)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    c.setFillColorRGB(0, 0, 0)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    c.setTitle(f"FTTH Dashboard - {period_label}")
    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0.9, 0.9, 0.9)
    c.drawString(0.75*inch, height - 1.0*inch, f"FTTH Dashboard — {period_label}")

    img_reader = ImageReader(io.BytesIO(png_bytes))
    img_w = width - 1.5*inch
    img_h = img_w * 0.55
    c.drawImage(
        img_reader,
        0.75*inch,
        height - 1.0*inch - img_h - 0.25*inch,
        width=img_w,
        height=img_h,
        preserveAspectRatio=True,
        mask='auto'
    )

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()

# =========================================================
# GITHUB HELPERS
# =========================================================
def get_github_config():
    try:
        gh_cfg = st.secrets["github"]
        token = gh_cfg["token"]
        repo = gh_cfg["repo"]
        branch = gh_cfg.get("branch", "main")
        remote_prefix = gh_cfg.get("file_path", "fiber/")
        remote_prefix = remote_prefix.rstrip("/") + "/"
        return token, repo, branch, remote_prefix
    except Exception:
        st.warning("GitHub secrets not configured correctly under [github].")
        return None, None, None, None

def save_upload_to_local_and_github(filename: str, file_bytes: bytes):
    local_folder = "fiber"
    os.makedirs(local_folder, exist_ok=True)
    local_path = os.path.join(local_folder, filename)
    try:
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        st.success(f"Saved file locally: {local_path}")
    except Exception as e:
        st.error(f"Failed to save file locally: {e}")

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
    token, repo, branch, remote_prefix = get_github_config()
    if not token or not repo:
        return []
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
        save_upload_to_local_and_github(up.name, pdf_bytes)
        grand, by_status, raw = parse_one_pdf(pdf_bytes)
        period = _extract_date_label(raw, fallback_label=up.name or f"File {i}")
        for s in ["ACT", "COM", "VIP"]:
            c_ = by_status[s]["act"]
            by_status[s]["rpc"] = (by_status[s]["amt"]/c_) if c_ else 0
        records.append({"period": period, "grand": grand, "by_status": by_status})
else:
    gh_files = list_github_files_in_fiber()
    if not gh_files:
        st.info("No files found in GitHub fiber/ directory.")
        st.stop()
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

records.sort(key=lambda r: r["period"])

# =========================================================
# CURRENT REPORT
# =========================================================
r = records[-1]
grand = r["grand"]
by_status = r["by_status"]
period_label = r["period"]
overall_arpu = (grand["amt"]/grand["act"]) if grand["act"] else 0

# --- TOP KPI ROW ---
html_top = f"""
<div style="display:flex;gap:20px;justify-content:space-between;margin-bottom:10px;">
    <div style="flex:1;background-color:#111111;border:1px solid #222222;
                border-radius:14px;padding:16px;text-align:center;">
        <p style="margin:0;font-size:16px;color:#aaaaaa;">FTTH Customers</p>
        <p style="margin:0;font-size:28px;font-weight:700;color:#49d0ff;">{grand['act']:,}</p>
    </div>
    <div style="flex:1;background-color:#111111;border:1px solid #222222;
                border-radius:14px;padding:16px;text-align:center;">
        <p style="margin:0;font-size:16px;color:#aaaaaa;">Total Revenue</p>
        <p style="margin:0;font-size:28px;font-weight:700;color:#3ddc97;">${grand['amt']:,.2f}</p>
    </div>
    <div style="flex:1;background-color:#111111;border:1px solid #222222;
                border-radius:14px;padding:16px;text-align:center;">
        <p style="margin:0;font-size:16px;color:#aaaaaa;">ARPU</p>
        <p style="margin:0;font-size:28px;font-weight:700;color:#3ddc97;">${overall_arpu:,.2f}</p>
    </div>
</div>
"""
st.markdown(html_top, unsafe_allow_html=True)
st.divider()

# --- KPI BOXES (SAME STYLE AS TOP ROW) ---
def metric_box(col, title, value, subtitle1, subtitle2):
    html = f"""
    <div style="background-color:#111111;border:1px solid #222222;
                border-radius:14px;padding:16px;text-align:center;">
        <p style="margin:0;font-size:16px;color:#aaaaaa;">{title}</p>
        <p style="margin:0;font-size:28px;font-weight:700;color:#49d0ff;">{value:,}</p>
        <p style="margin:0;font-size:14px;color:#3ddc97;">
            {subtitle1} • {subtitle2}
        </p>
    </div>
    """
    col.markdown(html, unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)

metric_box(
    c1,
    "ACT — Active Residential",
    by_status["ACT"]["act"],
    f"Rev ${by_status['ACT']['amt']:,.2f}",
    f"ARPU ${by_status['ACT']['rpc']:,.2f}"
)

metric_box(
    c2,
    "COM — Active Commercial",
    by_status["COM"]["act"],
    f"Rev ${by_status['COM']['amt']:,.2f}",
    f"ARPU ${by_status['COM']['rpc']:,.2f}"
)

metric_box(
    c3,
    "VIP",
    by_status["VIP"]["act"],
    f"Rev ${by_status['VIP']['amt']:,.2f}",
    f"ARPU ${by_status['VIP']['rpc']:,.2f}"
)

# =========================================================
# CHARTS – REVENUE SHARE: BLACK LABELS | BAR: WHITE LABELS
# =========================================================
st.subheader("Visuals")

chart = pd.DataFrame([
    {"Status": s, "Revenue": by_status[s]["amt"], "Customers": by_status[s]["act"], "ARPU": by_status[s]["rpc"]}
    for s in ["ACT", "COM", "VIP"]
])

act_color = "#49d0ff"
com_color = "#3ddc97"
vip_color = "#aaaaaa"

l, r2 = st.columns(2)

# ---------- Revenue Share (Pie) – BLACK TEXT ----------
with l:
    st.markdown("**Revenue Share**")
    chart_f = chart[chart["Revenue"] > 0]
    if not chart_f.empty:
        base = (
            alt.Chart(chart_f)
            .transform_joinaggregate(total="sum(Revenue)")
            .transform_calculate(pct="datum.Revenue / datum.total")
            .properties(width=300, height=300)
        )
        arcs = base.mark_arc(innerRadius=60).encode(
            theta="Revenue:Q",
            color=alt.Color(
                "Status:N",
                scale=alt.Scale(domain=["ACT","COM","VIP"], range=[act_color, com_color, vip_color]),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("Status:N"),
                alt.Tooltip("Revenue:Q", format="$.2f"),
                alt.Tooltip("Customers:Q", format=",.0f"),
                alt.Tooltip("ARPU:Q", format="$.2f"),
                alt.Tooltip("pct:Q", format=".1%", title="Share"),
            ],
        )
        labels = base.mark_text(
            radius=95,
            fontSize=15,
            fontWeight="normal",
            color="#000000"  # BLACK TEXT
        ).encode(
            theta="Revenue:Q",
            text=alt.Text("label:N")
        ).transform_calculate(
            label="datum.Status + ' ' + format(datum.pct, '.1%')"
        )
        st.altair_chart(
            (arcs + labels).configure_view(strokeWidth=0)
            .configure_axis(labelColor="#ffffff", titleColor="#ffffff", gridColor="#222222", domainColor="#222222"),
            use_container_width=True,
        )
    else:
        st.write("No revenue data to display.")

# ---------- Active Customers by Status (Bar) – WHITE TEXT ----------
with r2:
    st.markdown("**Active Customers by Status**")
    base = alt.Chart(chart).properties(width=300, height=300)
    bars = base.mark_bar(
        color=act_color,
        stroke=com_color,
        strokeWidth=2,
        cornerRadiusTopLeft=6,
        cornerRadiusTopRight=6,
    ).encode(
        x=alt.X("Status:N", sort=["ACT","COM","VIP"], axis=alt.Axis(labelColor="#ffffff", titleColor="#ffffff")),
        y=alt.Y("Customers:Q", axis=alt.Axis(labelColor="#ffffff", titleColor="#ffffff", gridColor="#222222")),
        tooltip=[
            alt.Tooltip("Status:N"),
            alt.Tooltip("Customers:Q", format=",.0f"),
            alt.Tooltip("Revenue:Q", format="$.2f"),
            alt.Tooltip("ARPU:Q", format="$.2f"),
        ],
    )
    labels = base.mark_text(
        dy=-10,
        fontSize=15,
        fontWeight="normal",
        color="#ffffff"  # WHITE TEXT
    ).encode(
        x=alt.X("Status:N", sort=["ACT","COM","VIP"]),
        y=alt.Y("Customers:Q"),
        text=alt.Text("Customers:Q", format=",.0f"),
    )
    st.altair_chart(
        (bars + labels).configure_view(strokeWidth=0)
        .configure_axis(labelColor="#ffffff", titleColor="#ffffff", gridColor="#222222", domainColor="#222222"),
        use_container_width=True,
    )

# =========================================================
# EXPORTS - PERFECT BLACK
# =========================================================
png_bytes = export_snapshot_png(period_label, grand, by_status)
pdf_bytes = export_snapshot_pdf(period_label, grand, by_status)

col1, col2 = st.columns(2)
col1.download_button("Download Snapshot (PNG)", png_bytes, f"ftth_snapshot_{period_label}.png", "image/png")
col2.download_button("Download Snapshot (PDF)", pdf_bytes, f"ftth_snapshot_{period_label}.pdf", "application/pdf")

st.caption("FTTH Dashboard snapshot includes KPIs and charts as a static image.")
