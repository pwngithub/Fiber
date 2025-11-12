import io
import re
import json
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Subscriber Totals (PDF parser)", page_icon="📄", layout="wide")
st.title("📄 Subscriber Totals (PDF parser)")

uploaded = st.file_uploader("Upload 'Subscriber Counts v2' PDF", type=["pdf"])

def _clean_int(s: str) -> int:
    return int(s.replace(",", ""))

def _clean_amt(s: str) -> float:
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))

def parse_pdf(pdf_bytes: bytes):
    """
    Strategy:
    - Find status headers like:
        Customer Status ,"ACT","Active residential","3,727","3,727"
      Capture (STATUS, Active count, position).
    - For each header, look BACKWARD ~300 chars for the last $ amount: that's the status revenue.
    - Grand Total: match "Total: <subs> <act> $<amt>" (this file uses 'Total:' without 'Grand').
    """
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    compact = re.sub(r"\s+", " ", text)

    # Status header matcher (captures status & counts)
    header_pat = re.compile(
        r'Customer Status\s*",\s*"(ACT|COM|VIP)"\s*,\s*"(Active residential|Active Commercial|VIP)"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"',
        re.IGNORECASE
    )

    # Collect headers with positions
    starts = []
    for m in header_pat.finditer(compact):
        status = m.group(1).upper()
        # subs = _clean_int(m.group(3))  # not used
        act   = _clean_int(m.group(4))
        starts.append((status, act, m.start(), m.end()))

    # For each header: scan BACKWARDS ~300 chars and take the LAST $ amount before the header
    by_status = {"ACT": {"act": 0, "amt": 0.0}, "COM": {"act": 0, "amt": 0.0}, "VIP": {"act": 0, "amt": 0.0}}
    back_window = 300
    for status, act, s, e in starts:
        window = compact[max(0, s - back_window): s]
        dollars = list(re.finditer(r"\$([0-9][0-9,.\(\)-]*)", window))
        amt = _clean_amt(dollars[-1].group(1)) if dollars else 0.0
        # This file has exactly one header per status; if multiple, we’d sum
        by_status[status]["act"] += act
        by_status[status]["amt"] += amt

    # Grand Total (this file shows 'Total:' line)
    grand = {"subs": None, "act": None, "amt": None}
    m_total = re.search(r"Total\s*:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)", compact, re.IGNORECASE)
    if m_total:
        grand["subs"] = _clean_int(m_total.group(1))
        grand["act"]  = _clean_int(m_total.group(2))
        grand["amt"]  = _clean_amt(m_total.group(3))
    else:
        # Fallbacks if ever needed
        grand["act"] = sum(v["act"] for v in by_status.values())
        grand["amt"] = sum(v["amt"] for v in by_status.values())

    return grand, by_status

if uploaded:
    try:
        grand, by_status = parse_pdf(uploaded.read())

        # Metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("Grand Total Active Customers", f"{grand['act']:,}")
        c2.metric("Grand Total Subs", f"{grand['subs']:,}" if grand["subs"] is not None else "—")
        c3.metric("Grand Total Revenue", f"${grand['amt']:,.2f}")

        # Table by status
        order = ["ACT", "COM", "VIP"]
        df = pd.DataFrame(
            [{"Status": s, "Active Sub Count": by_status[s]["act"], "Revenue": by_status[s]["amt"]} for s in order]
        )
        st.subheader("Totals by Status")
        st.dataframe(df.style.format({"Revenue": "${:,.2f}"}), use_container_width=True)

        # Filter
        st.subheader("Filter")
        selected = st.multiselect("Statuses", order, default=order)
        filt_act = sum(by_status[s]["act"] for s in selected)
        filt_amt = sum(by_status[s]["amt"] for s in selected)
        f1, f2 = st.columns(2)
        f1.metric("Filtered Active Sub Count", f"{filt_act:,}")
        f2.metric("Filtered Revenue", f"${filt_amt:,.2f}")

        # Export
        a, b = st.columns(2)
        a.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), "status_totals.csv", "text/csv")
        b.download_button("Download JSON", json.dumps(df.to_dict(orient="records"), indent=2), "status_totals.json", "application/json")

        st.success("Extraction complete.")
        st.caption("Note: This report prints the $ amount BEFORE each status header; the parser captures the last $ before each header.")
    except Exception as e:
        st.error(f"Failed to parse PDF: {e}")
else:
    st.info("Upload your PDF to begin.")
