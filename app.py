import io
import re
import json
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Subscriber Totals Extractor", page_icon="📄", layout="wide")
st.title("📄 Subscriber Totals Extractor")
st.caption("Upload your **Subscriber Counts v2** PDF to extract Grand Totals and filter by ACT / VIP / COM.")

uploaded = st.file_uploader("Upload PDF", type=["pdf"])

def clean_amount(s: str) -> float:
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))

def parse_pdf_bytes(pdf_bytes: bytes):
    """
    Returns:
      grand = {"subs": int, "act": int, "amt": float}
      by_status = dict like {"ACT": {"subs": int, "act": int, "amt": float}, ...}
    """
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    # Normalize whitespace for regexes
    compact = re.sub(r"\s+", " ", full_text)

    # 1) GRAND TOTAL: "Grand Total: 4,309 4,309 $381,475.84"
    grand = {"subs": None, "act": None, "amt": None}
    m_gt = re.search(
        r"Grand\s*Total\s*:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)",
        compact, flags=re.IGNORECASE
    )
    if m_gt:
        grand["subs"] = int(m_gt.group(1).replace(",", ""))
        grand["act"]  = int(m_gt.group(2).replace(",", ""))
        grand["amt"]  = clean_amount(m_gt.group(3))
    else:
        # Fallback: use the largest $ as revenue and leave counts None if not found
        dollars = [m.group(0) for m in re.finditer(r"\$[0-9][0-9,.\(\)-]*", compact)]
        if dollars:
            grand["amt"] = max(clean_amount(d[1:]) for d in dollars)

    # 2) STATUS TOTALS: find "Customer Status ","ACT|VIP|COM" ... then nearest "Total: X Y $Z"
    by_status = {"ACT": {"subs": 0, "act": 0, "amt": 0.0},
                 "VIP": {"subs": 0, "act": 0, "amt": 0.0},
                 "COM": {"subs": 0, "act": 0, "amt": 0.0}}
    for m in re.finditer(
        r'Customer Status\s*",\s*"(ACT|VIP|COM)".{0,160}?Total:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)',
        compact, flags=re.IGNORECASE
    ):
        status = m.group(1).upper()
        subs   = int(m.group(2).replace(",", ""))
        act    = int(m.group(3).replace(",", ""))
        amt    = clean_amount(m.group(4))
        by_status[status]["subs"] += subs
        by_status[status]["act"]  += act
        by_status[status]["amt"]  += amt

    # If grand counts not found, try to sum statuses (should match)
    if (grand["subs"] is None or grand["act"] is None) and any(by_status.values()):
        grand["subs"] = sum(v["subs"] for v in by_status.values())
        grand["act"]  = sum(v["act"] for v in by_status.values())
    if grand["amt"] is None and any(by_status.values()):
        grand["amt"] = sum(v["amt"] for v in by_status.values())

    return grand, by_status

if uploaded:
    try:
        grand, by_status = parse_pdf_bytes(uploaded.read())

        # Sidebar filter
        st.sidebar.subheader("Filter by Status")
        statuses = ["ACT", "VIP", "COM"]
        selected = st.sidebar.multiselect("Statuses", statuses, default=statuses)

        # Compute filtered totals
        filt_counts = {"subs": 0, "act": 0, "amt": 0.0}
        for s in selected:
            v = by_status.get(s, {"subs": 0, "act": 0, "amt": 0.0})
            filt_counts["subs"] += v["subs"]
            filt_counts["act"]  += v["act"]
            filt_counts["amt"]  += v["amt"]

        # Metrics row
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Grand Total Active Customers", f"{grand['act']:,}" if grand["act"] is not None else "—")
        with col2:
            st.metric("Grand Total Revenue", f"${grand['amt']:,.2f}" if grand["amt"] is not None else "—")
        with col3:
            st.metric("Filtered Revenue", f"${filt_counts['amt']:,.2f}")

        # Status table
        df = pd.DataFrame([
            {"Status": s,
             "Subs Count": by_status[s]["subs"],
             "Active Sub Count": by_status[s]["act"],
             "Revenue": by_status[s]["amt"]}
            for s in statuses
        ])
        st.subheader("Totals by Status")
        st.dataframe(df.style.format({"Revenue": "${:,.2f}"}), use_container_width=True)

        # Filtered totals card
        st.subheader("Filtered Totals")
        st.write(
            pd.DataFrame([{
                "Selected Statuses": ", ".join(selected) if selected else "(none)",
                "Active Sub Count": filt_counts["act"],
                "Revenue": filt_counts["amt"],
            }]).style.format({"Revenue": "${:,.2f}"})
        )

        # Downloads
        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "Download Status Totals (CSV)",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="status_totals.csv",
                mime="text/csv",
            )
        with c2:
            st.download_button(
                "Download Status Totals (JSON)",
                data=json.dumps(df.to_dict(orient="records"), indent=2),
                file_name="status_totals.json",
                mime="application/json",
            )

        st.success("Extraction complete.")
        st.caption("Tip: If your PDF layout changes, the regex windows can be widened in the code.")
    except Exception as e:
        st.error(f"Failed to parse PDF: {e}")
else:
    st.info("Upload your PDF to begin.")
