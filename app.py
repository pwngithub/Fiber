import io
import re
import json
import pandas as pd
import streamlit as st

# Optional but nice: wide layout
st.set_page_config(page_title="Subscriber Snapshot", page_icon="📄", layout="wide")

st.title("📄 Subscriber Snapshot")
st.caption("Upload your 'Subscriber Counts v2' PDF to extract Total Active Customers and Revenue.")

uploaded = st.file_uploader("Upload PDF", type=["pdf"])

def parse_totals_from_text(text: str):
    """
    The file's 'Grand Total' line looks like:
        '4,309 4,309Grand Total: $381,475.84'
    We'll capture the last count before 'Grand Total:' and the $ amount.
    """
    # Collapse whitespace to make regex more resilient across line breaks
    compact = re.sub(r"\s+", " ", text)

    # Pattern: <count> <count> Grand Total: $<amount>
    m = re.search(r"([\d,]+)\s+([\d,]+)\s*Grand Total:\s*\$([0-9,.\(\)-]+)", compact, re.IGNORECASE)
    if not m:
        # Fallback: just find the $ amount, and the last number before 'Grand Total'
        amt = re.search(r"Grand Total:\s*\$([0-9,.,\(\)-]+)", compact, re.IGNORECASE)
        count_before = re.search(r"([\d,]+)\s*Grand Total:", compact, re.IGNORECASE)
        if not amt or not count_before:
            return None, None
        active_count = count_before.group(1)
        revenue = amt.group(1)
    else:
        # Use the second count (Act Sub Count) by convention in this report
        active_count = m.group(2)
        revenue = m.group(3)

    # Normalize
    active_count_int = int(active_count.replace(",", ""))
    # Handle $ with commas and potential negatives in parentheses
    revenue_clean = revenue.replace(",", "").replace("(", "-").replace(")", "")
    revenue_float = float(revenue_clean)

    return active_count_int, revenue_float

if uploaded:
    try:
        # Lazy import so the app boots even if no PDF uploaded yet
        import pdfplumber

        with pdfplumber.open(io.BytesIO(uploaded.read())) as pdf:
            full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        active_customers, revenue = parse_totals_from_text(full_text)

        if active_customers is None or revenue is None:
            st.error("Sorry, I couldn't find the 'Grand Total' line in this PDF.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Active Customers", f"{active_customers:,}")
            with col2:
                st.metric("Revenue (Grand Total)", f"${revenue:,.2f}")

            # Show a small table + downloads
            df = pd.DataFrame(
                [{"total_active_customers": active_customers, "revenue": revenue}]
            )
            st.dataframe(df, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "Download CSV",
                    data=df.to_csv(index=False).encode("utf-8"),
                    file_name="subscriber_snapshot.csv",
                    mime="text/csv",
                )
            with c2:
                st.download_button(
                    "Download JSON",
                    data=json.dumps(df.to_dict(orient="records"), indent=2),
                    file_name="subscriber_snapshot.json",
                    mime="application/json",
                )

            st.success("Done! Values extracted successfully.")
    except Exception as e:
        st.exception(e)
else:
    st.info("Upload a PDF to begin.")
