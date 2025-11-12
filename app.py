import io
import re
import json
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Subscriber Totals (Status-Grouped PDF)", page_icon="📄", layout="wide")
st.title("📄 Subscriber Totals (Status-Grouped PDF)")

uploaded = st.file_uploader("Upload the new 'Subscriber Counts v2' PDF (grouped by Customer Status)", type=["pdf"])

def _clean_amt(s: str) -> float:
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))

def parse_pdf(pdf_bytes: bytes):
    """
    Returns:
      grand = {"act": int|None, "subs": int|None, "amt": float|None}
      by_status = {"ACT": {"act": int, "amt": float}, "COM": {...}, "VIP": {...}}
    Works for both:
      - 'Grand Total: <subs> <act> $<amt>'
      - '$<amt> <subs> <act> Total:'
    and reads per-status rows like:
      Customer Status ,"ACT","Active residential","3,727","3,727"$308,445.88
    """
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    compact = re.sub(r"\s+", " ", text)

    # --- Per-status rows (direct) ---
    by_status = {"ACT": {"act": 0, "amt": 0.0}, "COM": {"act": 0, "amt": 0.0}, "VIP": {"act": 0, "amt": 0.0}}
    # Pattern: Customer Status ,"ACT","Active residential","3,727","3,727"$308,445.88
    status_row = re.compile(
        r'Customer Status\s*",\s*"(ACT|COM|VIP)"\s*,\s*"[A-Za-z ]+"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"\s*\$([0-9,.\(\)-]+)',
        re.IGNORECASE
    )
    for m in status_row.finditer(compact):
        status = m.group(1).upper()
        # subs = m.group(2)  # not used; active = m.group(3)
        act = int(m.group(3).replace(",", ""))
        amt = _clean_amt(m.group(4))
        by_status[status]["act"] += act
        by_status[status]["amt"] += amt

    # --- Grand Total: support both layouts ---
    grand = {"subs": None, "act": None, "amt": None}

    # Layout A: Grand Total: <subs> <act> $<amt>
    m_a = re.search(r"Grand\s*Total\s*:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)", compact, re.IGNORECASE)
    # Layout B: $<amt> <subs> <act> Total:
    m_b = re.search(r"\$([0-9,.\(\)-]+)\s*([0-9,]+)\s+([0-9,]+)\s*Total\s*:", compact, re.IGNORECASE)

    if m_a:
        grand["subs"] = int(m_a.group(1).replace(",", ""))
        grand["act"]  = int(m_a.group(2).replace(",", ""))
        grand["amt"]  = _clean_amt(m_a.group(3))
    elif m_b:
        grand["amt"]  = _clean_amt(m_b.group(1))
        grand["subs"] = int(m_b.group(2).replace(",", ""))
        grand["act"]  = int(m_b.group(3).replace(",", ""))

    # Fallbacks if needed
    if grand["act"] is None:
        grand["act"] = sum(v["act"] for v in by_status.values())
    if grand["amt"] is None:
        grand["amt"] = sum(v["amt"] for v in by_status.values())

    return grand, by_status

if uploaded:
    try:
        grand, by_status = parse_pdf(uploaded.read())

        # Top-level metrics
        top1, top2, top3 = st.columns(3)
        top1.metric("Grand Total Active Customers", f"{grand['act']:,}")
        top2.metric("Grand Total Subs (if present)", f"{grand['subs']:,}" if grand["subs"] is not None else "—")
        top3.metric("Grand Total Revenue", f"${grand['amt']:,.2f}")

        # Status filter
        st.sidebar.subheader("Filter by Status")
        statuses = ["ACT", "COM", "VIP"]
        selected = st.sidebar.multiselect("Statuses", statuses, default=statuses)

        # Status table
        df = pd.DataFrame(
            [{"Status": s, "Active Sub Count": by_status[s]["act"], "Revenue": by_status[s]["amt"]} for s in statuses]
        )
        st.subheader("Totals by Status")
        st.dataframe(df.style.format({"Revenue": "${:,.2f}"}), use_container_width=True)

        # Filtered totals
        filt_act = sum(by_status[s]["act"] for s in selected)
        filt_amt = sum(by_status[s]["amt"] for s in selected)

        f1, f2 = st.columns(2)
        f1.metric("Filtered Active Sub Count", f"{filt_act:,}")
        f2.metric("Filtered Revenue", f"${filt_amt:,.2f}")

        # Exports
        c1, c2 = st.columns(2)
        c1.download_button(
            "Download CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name="status_totals.csv",
            mime="text/csv"
        )
        c2.download_button(
            "Download JSON",
            json.dumps(df.to_dict(orient="records"), indent=2),
            file_name="status_totals.json",
            mime="application/json"
        )
        st.success("Extraction complete.")
    except Exception as e:
        st.error(f"Failed to parse PDF: {e}")
else:
    st.info("Upload your PDF to begin.")
