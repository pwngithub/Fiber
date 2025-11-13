st.markdown("""
<style>

/* Streamlit automatically sets these based on light/dark mode: */
:root {
    --bg: var(--background-color);
    --text: var(--text-color);
    --primary: var(--primary-color);
}

/* App background */
.stApp {
    background-color: var(--bg);
    color: var(--text);
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: var(--bg);
    color: var(--text);
}

/* KPI Boxes */
.kpi-box {
    background-color: rgba(21, 25, 36, 0.85);  /* adaptive (dark) */
    border: 1px solid #1e2331;
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 5px;
    text-align: center;
}

@media (prefers-color-scheme: light) {
    .kpi-box {
        background-color: #ffffff;
        border: 1px solid #cccccc;
    }
}

/* KPI text */
.kpi-title { color: var(--text); }
.kpi-value { font-size: 28px; font-weight: 700; color: #49d0ff; }
.kpi-sub { font-size: 14px; color: #3ddc97; }

/* Top KPI cards */
.metric-card {
    background-color: rgba(21, 25, 36, 0.85);
    border: 1px solid #1e2331;
    border-radius: 14px;
    padding: 16px;
    text-align: center;
}

@media (prefers-color-scheme: light) {
    .metric-card {
        background-color: #ffffff;
        border-color: #cccccc;
    }
}

/* Text inside metric cards */
.metric-card-title {
    margin: 0;
    font-size: 16px;
    color: var(--text);
}
.metric-card-value-blue {
    margin: 0;
    font-size: 28px;
    font-weight: 700;
    color: #49d0ff;
}
.metric-card-value-green {
    margin: 0;
    font-size: 28px;
    font-weight: 700;
    color: #3ddc97;
}

</style>
""", unsafe_allow_html=True)
