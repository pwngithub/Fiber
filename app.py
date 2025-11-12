import io
import re
import json
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Subscriber Totals (robust PDF parser)", page_icon="📄", layout="wide")
st.title("📄 Subscriber Totals (robust PDF parser)")

uploaded = st.file_uploader("Upload 'Subscriber Counts v2' PDF", type=["pdf"])

def _clean_amt(s: str) -> float:
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))

def _clean_int(s: str) -> int:
    return int(s.replace(",", ""))

def parse_pdf_bytes(pdf_bytes: bytes):
    """
    Parse per-status rows from PDFs that look like:
      Customer Status ,"ACT","Active residential","3,727","3,727"$308,445.88
    but also tolerate variations:
      Customer Status ACT Active Residential 3727 3727 $308,445.88
      Customer Status,"ACT","Active Residential",3727,3727,$308,445.88
    and spacing/linebreak weirdness.
    Also reads the 'Grand Total' if present.
    """
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    # Normalize whitespace, but keep commas/$/quotes
    compact = re.sub(r"[ \t\r\f]+", " ", text)  # keep \n out of this replace
    compact = compact.replace("\n", " ")

    # ---------- GRAND TOTAL ----------
    grand = {"subs": None, "act": None, "amt": None}

    # A) Grand Total: <subs> <act> $<amt>
    m_a = re.search(r"Grand\s*Total\s*:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)", compact, re.IGNORECASE)
    # B) $<amt> <subs> <act> Total:
    m_b = re.search(r"\$([0-9,.\(\)-]+)\s*([0-9,]+)\s+([0-9,]+)\s*Total\s*:", compact, re.IGNORECASE)

    if m_a:
        grand["subs"] = _clean_int(m_a.group(1))
        grand["act"]  = _clean_int(m_a.group(2))
        grand["amt"]  = _clean_amt(m_a.group(3))
    elif m_b:
        grand["amt"]  = _clean_amt(m_b.group(1))
        grand["subs"] = _clean_int(m_b.group(2))
        grand["act"]  = _clean_int(m_b.group(3))

    # ---------- PER-STATUS ROWS ----------
    # We’ll search for a tolerant pattern:
    # Customer Status   (optional commas/quotes)   <STATUS>   <label ~Active Residential/Commercial/VIP>   subs   act   $amount
    # Capture groups:
    #   1=status, 2=label, 3=subs, 4=act, 5=$
    status_row = re.compile(
        r"""
        Customer\ Status      # literal anchor
        [\s,"']*              # optional spaces/commas/quotes
        (ACT|COM|VIP)         # status
        [\s,"']+              # sep
        (Active\ ?Residential|Active\ ?Commercial|VIP)  # label (tolerate missing case/space later)
        [\s,"']+              # sep
        ([0-9,]+)             # subs count
        [\s,"']+              # sep
        ([0-9,]+)             # act count
        [\s,"']*              # optional sep
        \$([0-9,.\(\)-]+)     # amount
        """,
        re.IGNORECASE | re.VERBOSE
    )

    matches = list(status_row.finditer(compact))

    # If we didn’t get any, try a looser fallback where amount could come before counts
    if not matches:
        status_row_fallback = re.compile(
            r"""
            Customer\ Status
            [\s,"']*
            (ACT|COM|VIP)
            [\s,"']+
            (Active\ ?Residential|Active\ ?Commercial|VIP)
            (?:
                [\s,"']+\$([0-9,.\(\)-]+)[\s,"']+([0-9,]+)[\s,"']+([0-9,]+)   # $ amt before counts
              | [\s,"']+([0-9,]+)[\s,"']+([0-9,]+)[\s,"']+\$([0-9,.\(\)-]+) # counts before $ amt
            )
            """,
            re.IGNORECASE | re.VERBOSE
        )
        fb = list(status_row_fallback.finditer(compact))
        # Normalize to the same tuple positions (status, label, subs, act, amt)
        norm = []
        for m in fb:
            status = m.group(1).upper()
            label  = m.group(2)
            # figure out which branch matched
            if m.group(3) and m.group(4) and m.group(5):
                amt  = m.group(3)
                subs = m.group(4)
                act  = m.group(5)
            else:
                subs = m.group(6)
                act  = m.group(7)
                amt  = m.group(8)
            # Build a fake Match-like tuple
            norm.append((status, label, subs, act, amt))
        matches = norm  # special handling below

    # Aggregate by status
    by_status = {"ACT": {"act": 0, "amt": 0.0}, "COM": {"act": 0, "amt": 0.0}, "VIP": {"act": 0, "amt": 0.0}}

    debug_rows = []
    if matches and isinstance(matches[0], re.Match):
        # From the first (strict) pattern
        for m in matches:
            status = m.group(1).upper()
            label  = m.group(2)
            subs   = _clean_int(m.group(3))
            act    = _clean_int(m.group(4))
            amt    = _clean_amt(m.group(5))
            by_status[status]["act"] += act
            by_status[status]["amt"] += amt
            debug_rows.append((status, label, subs, act, amt))
    else:
        # From fallback normalized tuples
        for status, label, subs, act, amt in matches:
            s = status.upper()
            subs_i = _clean_int(subs)
            act_i  = _clean_int(act)
            amt_f  = _clean_amt(amt)
            by_status[s]["act"] += act_i
            by_status[s]["amt"] += amt_f
            debug_rows.append((s, label, subs_i, act_i, amt_f))

    # Fallback grand if missing
    if grand["act"] is None:
        grand["act"] = sum(v["act"] for v in by_status.values())
    if grand["amt"] is None:
        grand["amt"] = sum(v["amt"] for v in by_status.values())

    return grand, by_status, debug_rows

if uploaded:
    try:
        grand, by_status, debug_rows = parse_pdf_bytes(uploaded.read())

        # Metrics
        t1, t2, t3 = st.columns(3)
        t1.metric("Grand Total Active Customers", f"{grand['act']:,}")
        t2.metric("Grand Total Revenue", f"${grand['amt']:,.2f}")
        t3.metric("Statuses Found", f"{sum(1 for v in by_status.values() if v['act']>0)} / 3")

        # Status table
        order = ["ACT", "COM", "VIP"]
        df = pd.DataFrame(
            [{"Status": s, "Active Sub Count": by_status[s]["act"], "Revenue": by_status[s]["amt"]} for s in order]
        )
        st.subheader("Totals by Status")
        st.dataframe(df.style.format({"Revenue": "${:,.2f}"}), use_container_width=True)

        # Filter
        st.subheader("Filter")
        chosen = st.multiselect("Statuses", order, default=order)
        filt_act = sum(by_status[s]["act"] for s in chosen)
        filt_amt = sum(by_status[s]["amt"] for s in chosen)

        c1, c2 = st.columns(2)
        c1.metric("Filtered Active Sub Count", f"{filt_act:,}")
        c2.metric("Filtered Revenue", f"${filt_amt:,.2f}")

        # Debug: show what got matched
        with st.expander("Show matched status header rows (debug)"):
            dbg = pd.DataFrame(debug_rows, columns=["Status", "Label", "Subs", "Act", "Amount"])
            st.dataframe(dbg.style.format({"Amount": "${:,.2f}"}), use_container_width=True)

        # Downloads
        st.subheader("Export")
        a, b = st.columns(2)
        a.download_button(
            "Download CSV",
            df.to_csv(index=False).encode("utf-8"),
            "status_totals.csv",
            "text/csv",
        )
        b.download_button(
            "Download JSON",
            json.dumps(df.to_dict(orient="records"), indent=2),
            "status_totals.json",
            "application/json",
        )

        st.success("Extraction complete.")
        st.caption("Tip: If your report changes format, this parser is resilient to quotes/commas/case, but we can widen the match windows more if needed.")
    except Exception as e:
        st.error(f"Failed to parse PDF: {e}")
else:
    st.info("Upload your PDF to begin.")
