import io, re, json
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Subscriber Totals (PDF → Counts & $)", page_icon="📄", layout="wide")
st.title("📄 Subscriber Totals (PDF → Counts & $)")
st.caption("Upload **Subscriber Counts v2** PDF. Counts come from status headers; revenue can be computed or manually overridden.")

uploaded = st.file_uploader("Upload PDF", type=["pdf"])

def _clean_amt(s: str) -> float:
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))

def parse_counts_from_pdf(pdf_bytes: bytes):
    """Return (grand_act:int, grand_amt:float|None, per_status: dict[status]->act_count)."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    compact = re.sub(r"\s+", " ", full_text)

    # Grand totals (for display): "Grand Total: 4,309 4,309 $381,475.84"
    grand_act = None
    grand_amt = None
    m_gt = re.search(r"Grand\s*Total\s*:\s*([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.\(\)-]+)", compact, re.IGNORECASE)
    if m_gt:
        grand_act = int(m_gt.group(2).replace(",", ""))
        grand_amt = _clean_amt(m_gt.group(3))

    # Parse counts per status strictly from header lines (robust)
    # ACT counts
    pat_act = re.compile(
        r'Customer Status\s*",\s*"ACT"\s*,\s*"Active residential"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"',
        re.IGNORECASE
    )
    # COM counts
    pat_com = re.compile(
        r'Customer Status\s*",\s*"COM"\s*,\s*"Active Commercial"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"',
        re.IGNORECASE
    )
    # VIP counts
    pat_vip = re.compile(
        r'Customer Status\s*",\s*"VIP"\s*,\s*"VIP"\s*,\s*"([0-9,]+)"\s*,\s*"([0-9,]+)"',
        re.IGNORECASE
    )

    # Use the second quoted number = Active Sub Count
    act_count = sum(int(p[1].replace(",", "")) for p in pat_act.findall(compact))
    com_count = sum(int(p[1].replace(",", "")) for p in pat_com.findall(compact))
    vip_count = sum(int(p[1].replace(",", "")) for p in pat_vip.findall(compact))

    per_status_counts = {"ACT": act_count, "COM": com_count, "VIP": vip_count}

    # If grand_act missing, fill from sum
    if grand_act is None:
        grand_act = sum(per_status_counts.values())

    return grand_act, grand_amt, per_status_counts

if uploaded:
    try:
        grand_act, grand_amt_from_pdf, per_status_counts = parse_counts_from_pdf(uploaded.read())

        st.subheader("Counts (parsed from PDF)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ACT (Active Sub Count)", f"{per_status_counts['ACT']:,}")
        c2.metric("COM (Active Sub Count)", f"{per_status_counts['COM']:,}")
        c3.metric("VIP (Active Sub Count)", f"{per_status_counts['VIP']:,}")
        c4.metric("Grand Total Active", f"{grand_act:,}")

        # Revenue controls
        st.subheader("Revenue by Status")
        use_override = st.checkbox(
            "Override revenue per status (recommended if the PDF doesn’t carry clean per-status $)",
            value=True
        )

        # Defaults (computed unknown -> 0.0). You can set your official numbers here.
        default_rev = {"ACT": 0.0, "COM": 0.0, "VIP": 0.0}
        if use_override:
            # Pre-fill with your provided values
            act_rev = st.number_input("ACT Revenue ($)", value=308_445.88, step=0.01, format="%.2f")
            com_rev = st.number_input("COM Revenue ($)", value=70_996.16, step=0.01, format="%.2f")
            vip_rev = st.number_input("VIP Revenue ($)", value=1_994.18, step=0.01, format="%.2f")
        else:
            # If you later want to experiment with a computed method, leave placeholders = 0
            act_rev = default_rev["ACT"]
            com_rev = default_rev["COM"]
            vip_rev = default_rev["VIP"]
            st.info("Revenue left at 0.00 for now (no reliable per-status $ signals in the PDF text). Use the override toggle to set values.")

        per_status_rev = {"ACT": act_rev, "COM": com_rev, "VIP": vip_rev}

        # Final table
        df = pd.DataFrame([
            {"Status": s, "Active Sub Count": per_status_counts[s], "Revenue": per_status_rev[s]}
            for s in ["ACT", "COM", "VIP"]
        ])

        st.dataframe(df.style.format({"Revenue": "${:,.2f}"}), use_container_width=True)

        # Filter
        st.subheader("Filter")
        chosen = st.multiselect("Statuses", ["ACT", "COM", "VIP"], default=["ACT", "COM", "VIP"])
        filt_count = sum(per_status_counts[s] for s in chosen)
        filt_rev = sum(per_status_rev[s] for s in chosen)

        f1, f2, f3 = st.columns(3)
        f1.metric("Filtered Active Sub Count", f"{filt_count:,}")
        f2.metric("Filtered Revenue", f"${filt_rev:,.2f}")
        if grand_amt_from_pdf is not None:
            f3.metric("PDF Grand Total $ (for reference)", f"${grand_amt_from_pdf:,.2f}")

        # Downloads
        st.subheader("Export")
        left, right = st.columns(2)
        left.download_button(
            "Download CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name="status_totals.csv",
            mime="text/csv",
        )
        right.download_button(
            "Download JSON",
            json.dumps(df.to_dict(orient="records"), indent=2),
            file_name="status_totals.json",
            mime="application/json",
        )

        st.success("Done.")
        st.caption("Counts come from status headers in the PDF. Revenue per status is best set via override if the report template doesn’t print those dollars on each status row.")
    except Exception as e:
        st.error(f"Failed to parse the PDF: {e}")
else:
    st.info("Upload your PDF to begin.")
