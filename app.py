# =========================================================
# SAVE TO GITHUB (folder = "fiber") – Streamlit Cloud version
# =========================================================
import base64
import httpx
from pathlib import Path

# ---- CONFIG (read from Streamlit secrets) ----
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
GITHUB_REPO  = st.secrets["GITHUB_REPO"]      # e.g. "john/ftth-reports"
FOLDER       = "fiber"
API_ROOT     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FOLDER}"
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
# ----------------------------------------------

def _ensure_folder():
    """Create the folder if it does not exist (by adding a .gitkeep)."""
    try:
        httpx.get(API_ROOT, headers=HEADERS, timeout=10).raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            raise
        # Folder missing → create .gitkeep
        dummy = base64.b64encode(b"").decode()
        payload = {
            "message": "init fiber folder",
            "content": dummy,
            "branch": "main",
        }
        httpx.put(f"{API_ROOT}/.gitkeep", headers=HEADERS, json=payload, timeout=20).raise_for_status()
        st.toast("Created GitHub folder `fiber/`", icon="Folder")

def _upload(name: str, data: bytes):
    """Upload a single file (create or overwrite)."""
    b64 = base64.b64encode(data).decode()
    payload = {
        "message": f"Add FTTH report {name}",
        "content": b64,
        "branch": "main",
    }
    r = httpx.put(f"{API_ROOT}/{name}", headers=HEADERS, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()["content"]["html_url"]

# -----------------------------------------------------------------
# 1. Ensure folder exists
# -----------------------------------------------------------------
_ensure_folder()

# -----------------------------------------------------------------
# 2. Upload original PDFs (reset pointer because we already read them)
# -----------------------------------------------------------------
uploaded_links = []

for up in uploaded_files:
    up.seek(0)                                     # reset after parse_one_pdf
    period = _extract_date_label(_read_pdf_text(up.read()), fallback_label="unknown")
    up.seek(0)                                     # reset again for upload
    safe_name = Path(up.name).name
    gh_name = f"{period}_{safe_name}"
    try:
        url = _upload(gh_name, up.read())
        uploaded_links.append(f"[{gh_name}]({url})")
    except Exception as exc:
        st.error(f"Failed to upload **{safe_name}**: {exc}")

# -----------------------------------------------------------------
# 3. Upload generated snapshot PNG & PDF (latest period)
# -----------------------------------------------------------------
latest_period = records[-1]["period"]
for kind, data in [("png", png_bytes), ("pdf", pdf_bytes)]:
    gh_name = f"{latest_period}_snapshot.{kind}"
    try:
        url = _upload(gh_name, data)
        uploaded_links.append(f"[{gh_name}]({url})")
    except Exception as exc:
        st.error(f"Failed to upload snapshot **{kind}**: {exc}")

# -----------------------------------------------------------------
# 4. Show results
# -----------------------------------------------------------------
if uploaded_links:
    st.success("All files saved to GitHub `fiber/` folder")
    st.markdown("**Uploaded files:**\n" + "\n".join(f"- {link}" for link in uploaded_links),
                unsafe_allow_html=True)
else:
    st.warning("No files were uploaded (check token/permissions).")
