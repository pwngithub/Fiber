# app.py
import io
import re
import json
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Subscriber Totals Extractor", page_icon="📄", layout="wide")
st.title("📄 Subscriber Totals Extractor")
st.caption("Upload your 'Subscriber Counts v2' PDF to extract Grand Totals and per-status counts & revenue (ACT / VIP / COM).")

uploaded = st.file_uploader("Upload PDF", type=["pdf"])

def _clean_amt(s: str) -> float:
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))

def _sum_status_counts(compact: str, status: str) -> int:
    # STRICT patterns: read the two quoted numbers right after the status label
    if status == "ACT":
        pat = re.compile(r'Customer Status\s*",\s*"ACT"\s*,\s*"Active residential"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"', re.IGNORECASE)
    elif status == "COM":
        pat = re.compile(r'Customer Status\s*",\s*"COM"\s*,\s*"Active Commercial"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"', re.IGNORECASE)
    else:  # VIP
        pat = re.compile(r'Customer Status\s*",\s*"VIP"\s*,\s*"VIP"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"', re.IGNORECASE)
    pairs = pat.findall(compact)
    # Use the second number = Active Sub Count
    return sum(int(p[1].replace(",", "")) for p in pairs)

def _sum_status_revenue(compact: str):
    # Tempered regex: within each status block, pick the first "Total: X Y $Z"
    pat = re.compile(
        r'Customer Status\s*",\s*"(ACT|VIP|COM)"(?:(?!Customer Status).)*?Total:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)',
        re.IGNORECASE
    )
    res = {"ACT": 0.0, "VIP": 0.0, "COM": 0.0}
    for m in pat.finditer(compact):
        status = m.group(1).upper()
        amt = _clean_amt(m.group(4))
        res[status] += amt
    return res

def parse_pdf(pdf_bytes: bytes):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    compact = re.sub(r"\s+", " ", full_text)

    # Grand Total: "Grand Total: 4,309 4,309 $381,475.84"
    grand = {"subs": None, "act": None, "amt": None}
    m_gt = re.search(r"Grand\s*Total\s*:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)", compact, re.IGNORECASE)
    if m_gt:
        grand["subs"] = int(m_gt.group(1).replace(",", ""))
        grand["act"]  = int(m_gt.group(2).replace(",", ""))
        grand["amt"]  = _clean_amt(m_gt.group(3))

    # Per-status counts (robust against layout noise)
    act_count = _sum_status_counts(compact, "ACT")
    com_count = _sum_status_counts(compact, "COM")
    vip_count = _sum_status_counts(compact, "VIP")

    # Per-status revenue (sums of $ in status blocks)
    rev = _sum_status_revenue(compact)

    # Build results
    by_status = {
        "ACT": {"act": act_count, "amt": rev.get("ACT", 0.0)},
        "COM": {"act": com_count, "amt": rev.get("COM", 0.0)},
        "VIP": {"act": vip_count, "amt": rev.get("VIP", 0.0)},
    }

    # Safety: if any totals are missing, fill from sums
    if grand["act"] is None:
        grand["act"] = act_count + com_count + vip_count
    if grand["amt"] is None:
        grand["amt"] = sum(v["amt"] for v in by_status.values())

    return grand, by_status

if uploaded:
    try:
        grand, by_status = parse_pdf(uploaded.read())

        # Sidebar filter
        st.sidebar.subheader("Filter by Status")
        statuses = ["ACT", "COM", "VIP"]
        selected = st.sidebar.multiselect("Statuses", statuses, default=statuses)

        # Metrics: Grand totals
        c1, c2 = st.columns(2)
        c1.metric("Grand Total Active Customers", f"{grand['act']:,}")
        c2.metric("Grand Total Revenue", f"${grand['amt']:,.2f}")

        # Per-status table
        df = pd.DataFrame([
            {"Status": s, "Active Sub Count": by_status[s]["act"], "Revenue": by_status[s]["amt"]}
            for s in statuses
        ])
        st.subheader("Totals by Status")
        st.dataframe(df.style.format({"Revenue": "${:,.2f}"}), use_container_width=True)

        # Filtered totals (by status)
        filt_act = sum(by_status[s]["act"] for s in selected)
        filt_amt = sum(by_status[s]["amt"] for s in selected)

        st.subheader("Filtered Totals")
        st.metric("Active Sub Count (Filtered)", f"{filt_act:,}")
        st.metric("Revenue (Filtered)", f"${filt_amt:,.2f}")

        # Downloads
        a, b = st.columns(2)
        with a:
            st.download_button(
                "Download Status Totals (CSV)",
                df.to_csv(index=False).encode("utf-8"),
                "status_totals.csv",
                "text/csv"
            )
        with b:
            st.download_button(
                "Download Status Totals (JSON)",
                json.dumps(df.to_dict(orient="records"), indent=2),
                "status_totals.json",
                "application/json"
            )

        st.success("Extraction complete.")
        st.caption("Note: Counts are read from status headers; revenue comes from each status block’s Total line.")
    except Exception as e:
        st.error(f"Failed to parse PDF: {e}")
else:
    st.info("Upload your PDF to begin.")
