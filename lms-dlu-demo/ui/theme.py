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
          padding:.8rem 1.25rem; margin-bottom:1.5rem; box-shadow:0 2px 10px rgba(15,23,42,.05); }}
        .lms-brand {{ color:{PRIMARY_DARK}; font-size:1.15rem; font-weight:750; margin:0; }}
        .lms-subtitle {{ color:{TEXT_MUTED}; font-size:.86rem; margin:.15rem 0 0; }}
        .lms-role {{ color:{PRIMARY_DARK}; background:{PRIMARY_LIGHT}; border-radius:999px;
          padding:.3rem .7rem; font-size:.78rem; font-weight:700; }}
        .lms-account {{ display:flex; align-items:center; gap:.65rem; color:{TEXT_MUTED}; }}
        .lms-account small {{ display:block; color:{TEXT_MUTED}; font-size:.72rem; margin-top:.12rem; }}
        .lms-avatar {{ width:34px; height:34px; display:grid; place-items:center; border-radius:50%; background:{PRIMARY_LIGHT}; color:{PRIMARY_DARK}; font-weight:800; }}
        .lms-notice {{ color:{PRIMARY}; font-size:1.1rem; }}
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
        [data-testid="stSidebar"] .stButton button[kind="primary"] {{ background:{PRIMARY_LIGHT}; color:{PRIMARY_DARK}; border:0; }}
        .stButton > button[kind="primary"] {{ background:{PRIMARY}; border-color:{PRIMARY}; }}
        .stButton > button[kind="primary"]:hover {{ background:{PRIMARY_DARK}; border-color:{PRIMARY_DARK}; }}
        .student-welcome {{ min-height:190px; display:flex; align-items:center; justify-content:space-between; overflow:hidden;
          border-radius:20px; padding:1.7rem 2rem; color:#fff; background:linear-gradient(115deg,{PRIMARY_DARK},#1976D2 62%,#42A5F5); box-shadow:0 12px 24px rgba(21,101,192,.18); }}
        .student-welcome span {{ font-size:.8rem; opacity:.85; }} .student-welcome h1 {{ margin:.35rem 0; color:#fff; font-size:1.8rem; }}
        .student-welcome p {{ margin:0; opacity:.9; }} .welcome-orbit {{ width:112px; height:112px; display:grid; place-items:center; border:1px solid rgba(255,255,255,.3); border-radius:50%; font-size:2rem; transform:rotate(-12deg); }}
        .welcome-orbit span {{ font-size:3.2rem; opacity:.35; }}
        .metric-card {{ display:flex; background:{SURFACE}; border:1px solid #E2E8F0; border-radius:16px; margin:1.2rem 0 1.6rem; box-shadow:0 2px 10px rgba(15,23,42,.045); }}
        .metric-item {{ flex:1; display:grid; justify-items:center; gap:.45rem; padding:1.1rem; color:{TEXT_PRIMARY}; }}
        .metric-item + .metric-item {{ border-left:1px solid #E2E8F0; }} .metric-item span {{ color:{PRIMARY}; font-size:.75rem; }}
        .metric-ring {{ width:68px; height:68px; display:grid; place-items:center; border-radius:50%; background:{SURFACE}; font-weight:800; border:6px solid; }}
        .metric-blue {{ border-color:{PRIMARY}; color:{PRIMARY_DARK}; }} .metric-green {{ border-color:{SUCCESS}; color:{SUCCESS}; }} .metric-orange {{ border-color:{WARNING}; color:{WARNING}; }}
        .dashboard-course {{ min-height:180px; background:{SURFACE}; border:1px solid #E2E8F0; border-radius:16px; padding:1rem; box-shadow:0 2px 10px rgba(15,23,42,.045); }}
        .dashboard-course .course-icon {{ width:38px; height:38px; display:grid; place-items:center; border-radius:11px; margin-bottom:.75rem; }}
        .dashboard-course.purple .course-icon {{ background:#F3E8FF; color:#7E22CE; }} .dashboard-course.python .course-icon {{ background:#FEF3C7; color:#B45309; }} .dashboard-course.red .course-icon {{ background:#FEE2E2; color:#DC2626; }}
        .utility-card {{ background:{SURFACE}; border:1px solid #E2E8F0; border-radius:16px; padding:1rem; margin-bottom:1rem; box-shadow:0 2px 10px rgba(15,23,42,.045); }}
        .utility-card h3 {{ margin:0 0 .9rem; color:{TEXT_PRIMARY}; font-size:1rem; }} .utility-card h4 {{ margin:0 0 .8rem; text-align:center; color:{TEXT_MUTED}; font-size:.8rem; }}
        .calendar-grid {{ display:grid; grid-template-columns:repeat(7,1fr); gap:.28rem; text-align:center; }} .calendar-grid span {{ min-height:25px; display:grid; place-items:center; font-size:.75rem; color:{TEXT_MUTED}; }}
        .calendar-days span {{ font-weight:700; font-size:.65rem; }} .calendar-grid .calendar-today {{ color:#fff; background:{PRIMARY}; border-radius:50%; }} .utility-empty {{ color:{TEXT_MUTED}; background:{BACKGROUND}; border-radius:10px; padding:1rem; text-align:center; font-size:.84rem; }}
        @media (max-width: 850px) {{ .metric-card {{ flex-direction:column; }} .metric-item + .metric-item {{ border-left:0; border-top:1px solid #E2E8F0; }} .student-welcome {{ padding:1.35rem; }} }}
        </style>
        """,
        unsafe_allow_html=True,
    )
