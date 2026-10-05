"""Shared visual language for the LMS Streamlit demo."""

PRIMARY = "#1565C0"
PRIMARY_DARK = "#0D47A1"
PRIMARY_LIGHT = "#E3F2FD"
BACKGROUND = "#F6F8FB"
SURFACE = "#FFFFFF"
TEXT_PRIMARY = "#1F2937"
TEXT_MUTED = "#64748B"
SUCCESS = "#16A34A"
WARNING = "#F59E0B"
ERROR = "#DC2626"


def inject_theme(st) -> None:
    """Apply stable CSS classes instead of coupling to Streamlit internals."""
    st.markdown(
        f"""
        <style>
        .stApp {{ background: {BACKGROUND}; color: {TEXT_PRIMARY}; }}
        .block-container {{ max-width: 1180px; padding-top: 1.5rem; padding-bottom: 2.5rem; }}
        .lms-topbar {{ display:flex; justify-content:space-between; align-items:center;
          background:{SURFACE}; border:1px solid #E2E8F0; border-radius:14px;
          padding:1rem 1.25rem; margin-bottom:1.5rem; box-shadow:0 2px 10px rgba(15,23,42,.05); }}
        .lms-brand {{ color:{PRIMARY_DARK}; font-size:1.15rem; font-weight:750; margin:0; }}
        .lms-subtitle {{ color:{TEXT_MUTED}; font-size:.86rem; margin:.15rem 0 0; }}
        .lms-role {{ color:{PRIMARY_DARK}; background:{PRIMARY_LIGHT}; border-radius:999px;
          padding:.3rem .7rem; font-size:.78rem; font-weight:700; }}
        .lms-page-title {{ color:{TEXT_PRIMARY}; font-size:1.65rem; font-weight:750; margin:0 0 .35rem; }}
        .lms-section-title {{ color:{TEXT_PRIMARY}; font-size:1.15rem; font-weight:700;
          margin:1.35rem 0 .75rem; }}
        .course-card {{ background:{SURFACE}; border:1px solid #E2E8F0; border-radius:14px;
          padding:1rem; min-height:156px; box-shadow:0 2px 10px rgba(15,23,42,.045); }}
        .course-code {{ color:{PRIMARY}; font-size:.78rem; font-weight:750; letter-spacing:.04em; }}
        .course-name {{ color:{TEXT_PRIMARY}; font-size:1.05rem; font-weight:700; margin:.4rem 0; }}
        .course-meta {{ color:{TEXT_MUTED}; font-size:.85rem; line-height:1.45; }}
        .lms-empty {{ background:{SURFACE}; border:1px dashed #CBD5E1; border-radius:14px;
          color:{TEXT_MUTED}; padding:1.3rem; text-align:center; }}
        .lms-note {{ background:{PRIMARY_LIGHT}; border-left:4px solid {PRIMARY}; border-radius:8px;
          color:{TEXT_PRIMARY}; padding:.85rem 1rem; margin:.75rem 0; }}
        .dlu-header-banner {{ border-bottom-color:#E2E8F0; }}
        .dlu-logo-text, .dlu-logo-sub {{ color:{PRIMARY_DARK} !important; }}
        .dlu-black-nav {{ background:{PRIMARY_DARK} !important; border-radius:10px; }}
        .section-green-title {{ color:{PRIMARY_DARK} !important; border-bottom-color:{PRIMARY} !important; }}
        .deeptutor-box {{ background:{PRIMARY_LIGHT} !important; border-left-color:{PRIMARY} !important; }}
        [data-testid="stSidebar"] {{ background:{SURFACE}; border-right:1px solid #E2E8F0; }}
        [data-testid="stSidebar"] .stButton button {{ text-align:left; border:0; background:transparent;
          color:{TEXT_PRIMARY}; border-radius:8px; }}
        [data-testid="stSidebar"] .stButton button:hover {{ background:{PRIMARY_LIGHT}; color:{PRIMARY_DARK}; }}
        .stButton > button[kind="primary"] {{ background:{PRIMARY}; border-color:{PRIMARY}; }}
        .stButton > button[kind="primary"]:hover {{ background:{PRIMARY_DARK}; border-color:{PRIMARY_DARK}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
