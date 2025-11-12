import io
import re
import json
import pandas as pd
import streamlit as st

# -------------------------------
# APP CONFIG
# -------------------------------
st.set_page_config(page_title="Subscriber KPI Dashboard", page_icon="📶", layout="wide")

# -------------------------------
# DARK THEME (subtle, clean)
# -------------------------------
st.markdown("""
<style>
/* App background & text */
:root, .stApp { background-color: #0f1115; color: #e6e6e6; }
section[data-testid="stSidebar"] { background: #0c0e12; }

/* Metric cards */
[data-testid="stMetric"] { background: #151924; border: 1px solid #1e2331; padding: 16px; border-radius: 14px; }
[data-testid="stMetricValue"] { color: #49d0ff; font-weight: 700; }
[data-testid="stMetricLabel"] { color: #b8c2cc; }
[data-testid="stMetricDelta"] { color: #a3ffd6; }

/* Dataframe */
.stDataFrame, .stTable { background: #121620; }
</style>
""", unsafe_allow_html=True)

st.title("📶 Subscriber KPI Dashboard")
st.caption("Extracts ACT / COM / VIP counts & revenue from the **Subscriber Counts v2** PDF and visualizes key KPIs.")

uploaded = st.file_uploader("Upload 'Subscriber Counts v2' PDF", type=["pdf"])

# -------------------------------
# UTILITIES
# -------------------------------
def _clean_int(s: str) -> int:
    return int(s.replace(",", ""))

def _clean_amt(s: str) -> float:
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))

def parse_pdf(pdf_bytes: bytes):
    """
    Strategy tuned for your file:
    - Find headers like: Customer Status ,"ACT","Active residential","3,727","3,727"
    - For each header, look BACKWARD ~300 chars to get the last $ amount before the header (that's the status revenue)
    - Grand Total: match "Total: <subs> <act> $<amt>"
    """
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    compact = re.sub(r"\s+", " ", text)

    # Match the 3 status headers with counts & positions
    header_pat = re.compile(
        r'Customer Status\s*",\s*"(ACT|COM|VIP)"\s*,\s*"(Active residential|Active Commercial|VIP)"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"',
        re.IGNORECASE
    )
    starts = [(m.group(1).upper(), _clean_int(m.group(4)), m.start(), m.end())
              for m in header_pat.finditer(compact)]

    # Read the $ immediately before each header
    by_status = {"ACT": {"act": 0, "amt": 0.0}, "COM": {"act": 0, "amt": 0.0}, "VIP": {"act": 0, "amt": 0.0}}
    back_window = 300
    for status, act, s, e in starts:
        win = compact[max(0, s - back_window): s]
        dollars = list(re.finditer(r"\$([0-9][0-9,.\(\)-]*)", win))
        amt = _clean_amt(dollars[-1].group(1)) if dollars else 0.0
        by_status[status]["act"] += act
        by_status[status]["amt"] += amt

    # Grand Total (this file uses "Total:")
    grand = {"subs": None, "act": None, "amt": None}
    m_total = re.search(r"Total\s*:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)", compact, re.IGNORECASE)
    if m_total:
        grand["subs"] = _clean_int(m_total.group(1))
        grand["act"]  = _clean_int(m_total.group(2))
        grand["amt"]  = _clean_amt(m_total.group(3))
    else:
        grand["act"] = sum(v["act"] for v in by_status.values())
        grand["amt"] = sum(v["amt"] for v in by_status.values())

    return grand, by_status

# -------------------------------
# UI
# -------------------------------
if not uploaded:
    st.info("Upload the PDF to see KPIs.")
    st.stop()

try:
    grand, by_status = parse_pdf(uploaded.read())
except Exception as e:
    st.error(f"Failed to parse PDF: {e}")
    st.stop()

# KPI CARDS (Status)
c1, c2, c3 = st.columns(3)
c1.metric("ACT — Active Residential", f"{by_status['ACT']['act']:,}", f"${by_status['ACT']['amt']:,.2f}")
c2.metric("COM — Active Commercial", f"{by_status['COM']['act']:,}", f"${by_status['COM']['amt']:,.2f}")
c3.metric("VIP", f"{by_status['VIP']['act']:,}", f"${by_status['VIP']['amt']:,.2f}")

# KPI CARDS (Overall)
o1, o2, o3 = st.columns(3)
avg_rev = (grand["amt"] / grand["act"]) if grand["act"] else 0
o1.metric("Grand Total Active", f"{grand['act']:,}")
o2.metric("Grand Total Revenue", f"${grand['amt']:,.2f}")
o3.metric("Avg Revenue / Active", f"${avg_rev:,.2f}")

st.divider()

# FILTERS
st.sidebar.header("Filters")
status_order = ["ACT", "COM", "VIP"]
selected = st.sidebar.multiselect("Statuses", status_order, default=status_order)

# TABLE
df = pd.DataFrame(
    [{"Status": s, "Active Sub Count": by_status[s]["act"], "Revenue": by_status[s]["amt"]} for s in status_order]
)
st.subheader("Totals by Status")
st.dataframe(df.style.format({"Revenue": "${:,.2f}"}), use_container_width=True)

# FILTERED KPIs
filt_act = sum(by_status[s]["act"] for s in selected)
filt_amt = sum(by_status[s]["amt"] for s in selected)
ff1, ff2 = st.columns(2)
ff1.metric("Filtered Active Sub Count", f"{filt_act:,}")
ff2.metric("Filtered Revenue", f"${filt_amt:,.2f}")

# -------------------------------
# CHARTS
# -------------------------------
st.divider()
st.subheader("📈 Visuals")

# Use Altair for clean charts
import altair as alt

chart_data = pd.DataFrame(
    [{"Status": s, "Revenue": by_status[s]["amt"], "Customers": by_status[s]["act"]} for s in status_order]
)

# Revenue donut
left, right = st.columns([1,1])
with left:
    st.markdown("**Revenue Share**")
    rev_chart = (
        alt.Chart(chart_data)
        .mark_arc(innerRadius=60)
        .encode(
            theta=alt.Theta("Revenue:Q", stack=True),
            color=alt.Color("Status:N"),
            tooltip=[alt.Tooltip("Status:N"), alt.Tooltip("Revenue:Q", format="$.2f")]
        )
        .properties(height=320)
    )
    st.altair_chart(rev_chart, use_container_width=True)

# Customers bar
with right:
    st.markdown("**Active Customers by Status**")
    cust_chart = (
        alt.Chart(chart_data)
        .mark_bar()
        .encode(
            x=alt.X("Status:N", sort=status_order),
            y=alt.Y("Customers:Q"),
            tooltip=[alt.Tooltip("Status:N"), alt.Tooltip("Customers:Q", format=",.0f")]
        )
        .properties(height=320)
    )
    st.altair_chart(cust_chart, use_container_width=True)

# -------------------------------
# EXPORTS
# -------------------------------
st.divider()
st.subheader("Export")
colx, coly = st.columns(2)
colx.download_button(
    "Download CSV", df.to_csv(index=False).encode("utf-8"), "status_totals.csv", "text/csv"
)
coly.download_button(
    "Download JSON", json.dumps(df.to_dict(orient="records"), indent=2), "status_totals.json", "application/json"
)

# FOOTNOTE
st.caption("Tip: If your report template changes, this parser can be switched to look after headers or widened. The current file prints $ amounts *before* each status header.")
