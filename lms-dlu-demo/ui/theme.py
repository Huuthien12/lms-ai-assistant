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
        .block-container {{ max-width:none; padding:1.5rem 2rem 2.5rem; }}
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
        .dlu-black-nav {{ display:none !important; }}
        .section-green-title {{ color:{PRIMARY_DARK} !important; border-bottom-color:{PRIMARY} !important; }}
        .deeptutor-box {{ background:{PRIMARY_LIGHT} !important; border-left-color:{PRIMARY} !important; }}
        [data-testid="stSidebar"] {{ background:linear-gradient(160deg,#063b78,#002a5c 72%,#001d44); border-right:0; }}
        @media (min-width:851px) {{ [data-testid="stSidebar"][aria-expanded="true"] {{ position:sticky !important; top:0; align-self:flex-start; min-width:250px !important; width:250px !important; height:100vh !important; }} [data-testid="stSidebar"][aria-expanded="true"] > div:first-child {{ min-width:250px !important; width:250px !important; height:100vh !important; }} }}
        [data-testid="stSidebarContent"] {{ position:relative; height:100%; display:flex; flex-direction:column; }}
        [data-testid="stSidebarUserContent"] {{ min-height:0; flex:1; padding:1.2rem .8rem 1rem; }}
        [data-testid="stSidebar"] .st-key-sidebar_bottom_actions {{ position:absolute; right:.8rem; bottom:1rem; left:.8rem; }}
        [data-testid="stSidebarUserContent"] > div:first-child {{ display:flex; flex-direction:column; min-height:100%; height:100%; }}
        [data-testid="stSidebarUserContent"] .st-key-sidebar_bottom_actions {{ margin-top:auto; }}
        .sidebar-brand {{ display:flex; align-items:center; gap:.75rem; padding:.35rem .45rem 1.25rem; color:#fff; }}
        .sidebar-brand > span {{ width:38px; height:38px; display:grid; place-items:center; border-radius:11px; background:rgba(255,255,255,.12); color:#fff; font-size:1.35rem; }}
        .sidebar-brand strong {{ display:block; font-size:1.2rem; }} .sidebar-brand small {{ display:block; margin-top:.1rem; color:#B8D8FF; font-size:.76rem; }}
        [data-testid="stSidebar"] .stButton button {{ min-height:48px; padding:.7rem .9rem; text-align:left; border:0; background:transparent;
          color:#E7F1FF; border-radius:11px; font-weight:600; transition:background 180ms ease,color 180ms ease,transform 180ms ease; cursor:pointer; }}
        [data-testid="stSidebar"] .stButton button:hover {{ background:rgba(76,159,255,.22); color:#fff; transform:translateX(2px); }}
        [data-testid="stSidebar"] .stButton button[kind="primary"] {{ background:#087df5; color:#fff; border:0; box-shadow:0 6px 18px rgba(0,0,0,.12); }}
        [data-testid="stSidebar"] .stButton button[kind="primary"]:hover {{ background:#168cff; color:#fff; transform:none; }}
        [data-testid="stSidebar"] .st-key-sidebar_logout button:hover {{ background:#FEF2F2; color:{ERROR}; }}
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
        .dashboard-course {{ transition:border-color 200ms ease,box-shadow 200ms ease,transform 200ms ease; cursor:pointer; }}
        .dashboard-course:hover {{ border-color:#3B82F6; box-shadow:0 8px 24px rgba(21,101,192,.12); transform:translateY(-3px); }}
        .dashboard-course .course-icon {{ width:38px; height:38px; display:grid; place-items:center; border-radius:11px; margin-bottom:.75rem; }}
        .dashboard-course.purple .course-icon {{ background:#F3E8FF; color:#7E22CE; }} .dashboard-course.python .course-icon {{ background:#FEF3C7; color:#B45309; }} .dashboard-course.red .course-icon {{ background:#FEE2E2; color:#DC2626; }}
        .courses-hero {{ min-height:150px; display:flex; align-items:center; justify-content:space-between; padding:1.6rem 2rem; margin:-.2rem 0 1.2rem; border-radius:0 0 18px 18px; background:linear-gradient(105deg,#fff 38%,#E6F3FF); }}
        .courses-hero h1 {{ margin:0; color:#071B4D; font-size:2.35rem; }} .courses-hero p {{ margin:.35rem 0 0; color:#587095; font-size:1.1rem; }} .courses-hero-art {{ width:128px; height:92px; display:grid; place-items:center; border-radius:22px; background:linear-gradient(135deg,#B9DEFF,#5BAAEB); color:#fff; font-size:3rem; transform:rotate(-7deg); }}
        .courses-count {{ display:inline-block; margin:0 0 1.25rem; padding:.7rem 1rem; color:{PRIMARY}; background:#fff; border:1px solid #9CCBFF; border-radius:10px; box-shadow:0 2px 7px rgba(21,101,192,.12); font-weight:750; }}
        .course-breadcrumb {{ margin:.25rem 0 .9rem; color:{PRIMARY_DARK}; font-weight:700; font-size:.9rem; }} .course-detail-hero {{ display:flex; align-items:center; gap:1.3rem; padding:1.35rem 1rem; margin:0 -2rem 1rem; background:linear-gradient(105deg,#fff,#EEF5FF); }} .course-detail-hero h1 {{ margin:.15rem 0; color:#071B4D; font-size:2rem; }} .course-detail-hero p {{ margin:0; color:{TEXT_MUTED}; }} .course-detail-icon {{ width:84px; height:84px; display:grid; place-items:center; border-radius:20px; background:#EFE0FF; color:#7E22CE; font-size:2.2rem; }}
        .course-overview-card {{ min-height:210px; padding:1.25rem; border:1px solid #E2E8F0; border-radius:16px; background:#fff; box-shadow:0 2px 10px rgba(15,23,42,.045); }} .course-overview-card h2 {{ margin:0 0 1rem; color:#071B4D; font-size:1.2rem; }} .course-overview-card p {{ margin:0; padding:1rem; border-radius:12px; background:#F7FAFE; color:{TEXT_MUTED}; line-height:1.55; }} .course-overview-card dl {{ display:grid; grid-template-columns:42% 58%; margin:0; border:1px solid #E2E8F0; border-radius:10px; overflow:hidden; }} .course-overview-card dt,.course-overview-card dd {{ margin:0; padding:.8rem; border-bottom:1px solid #E2E8F0; }} .course-overview-card dt {{ font-weight:700; color:#334155; background:#FBFDFF; }} .course-overview-card dd {{ color:{TEXT_MUTED}; }} .course-overview-card dt:last-of-type,.course-overview-card dd:last-child {{ border-bottom:0; }}
        .st-key-workspace_tab {{ margin:1.1rem 0 1.4rem; border-bottom:1px solid #E2E8F0; }} .st-key-workspace_tab [role="radiogroup"] {{ gap:0 !important; flex-wrap:nowrap !important; justify-content:space-between; }} .st-key-workspace_tab label {{ border:0 !important; border-radius:0 !important; background:transparent !important; padding:.75rem 1rem !important; }} .st-key-workspace_tab label:has(input:checked) {{ color:{PRIMARY} !important; border-bottom:3px solid {PRIMARY} !important; }}
        .document-row {{ display:flex; align-items:center; gap:.9rem; padding:.85rem .35rem; }} .document-row strong {{ display:block; color:#0F254F; }} .document-row small {{ display:block; margin-top:.2rem; color:{TEXT_MUTED}; }} .document-icon {{ width:38px; height:38px; display:grid; place-items:center; border-radius:10px; font-weight:800; }} .document-icon.pdf {{ color:#DC2626; background:#FEE2E2; }} .document-icon.docx {{ color:#2563EB; background:#DBEAFE; }} .document-icon.pptx {{ color:#EA580C; background:#FFEDD5; }} .document-icon.md {{ color:#475569; background:#E2E8F0; }}
        .student-course {{ overflow:hidden; min-height:252px; margin-top:.7rem; border:1px solid #E2E8F0; border-radius:15px; background:#fff; box-shadow:0 2px 10px rgba(15,23,42,.045); }} .student-course-banner {{ height:102px; display:flex; justify-content:flex-end; align-items:center; padding:1rem 1.3rem; color:#fff; font-size:2.8rem; }} .student-course.violet .student-course-banner {{ background:linear-gradient(135deg,#D8BCFF,#7954DD); }} .student-course.sky .student-course-banner {{ background:linear-gradient(135deg,#BEE8FF,#3A98E8); }} .student-course.amber .student-course-banner {{ background:linear-gradient(135deg,#FFE6AD,#F08A42); }} .student-course-body {{ padding:1rem 1.2rem; }} .student-course-body h3 {{ margin:.35rem 0; color:#071B4D; font-size:1.25rem; }} .student-course-body p {{ min-height:2.7rem; margin:0; color:{TEXT_MUTED}; font-size:.9rem; line-height:1.45; }}
        .utility-card {{ background:{SURFACE}; border:1px solid #E2E8F0; border-radius:16px; padding:1rem; margin-bottom:1rem; box-shadow:0 2px 10px rgba(15,23,42,.045); }}
        .utility-card h3 {{ margin:0 0 .9rem; color:{TEXT_PRIMARY}; font-size:1rem; }} .utility-card h4 {{ margin:0 0 .8rem; text-align:center; color:{TEXT_MUTED}; font-size:.8rem; }}
        .calendar-grid {{ display:grid; grid-template-columns:repeat(7,1fr); gap:.28rem; text-align:center; }} .calendar-grid span {{ min-height:25px; display:grid; place-items:center; font-size:.75rem; color:{TEXT_MUTED}; }}
        .calendar-days span {{ font-weight:700; font-size:.65rem; }} .calendar-grid .calendar-today {{ color:#fff; background:{PRIMARY}; border-radius:50%; }} .utility-empty {{ color:{TEXT_MUTED}; background:{BACKGROUND}; border-radius:10px; padding:1rem; text-align:center; font-size:.84rem; }}
        .stButton > button[data-testid="stBaseButton-secondary"] {{ background:{SURFACE}; border:1px solid #CBD5E1; color:{TEXT_PRIMARY}; transition:background 180ms ease,border-color 180ms ease,color 180ms ease; }}
        .stButton > button[data-testid="stBaseButton-secondary"]:hover {{ background:{PRIMARY}; border-color:{PRIMARY}; color:#fff; }}
        [data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-secondary"] {{ background:transparent; border:0; color:#E7F1FF; }}
        [data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-secondary"]:hover {{ background:rgba(76,159,255,.22); border:0; color:#fff; }}
        .lms-search {{ min-width:min(38vw,520px); border:1px solid #D7E2F2; border-radius:999px; padding:.65rem 1rem; color:#5D7190; font-size:.9rem; background:#fff; }}
        .lms-topbar {{ border:0; border-radius:0; margin:-1.5rem -2rem 1.5rem; padding:.8rem 2rem; box-shadow:0 1px 0 #E2E8F0; }}
        .lms-login-brand {{ max-width:980px; margin:2rem auto 1.4rem; display:flex; align-items:center; gap:.85rem; color:#071B4D; }} .lms-login-brand > span {{ width:48px; height:48px; display:grid; place-items:center; border-radius:14px; background:linear-gradient(135deg,{PRIMARY_DARK},{PRIMARY}); color:#fff; font-size:1.45rem; }} .lms-login-brand strong {{ display:block; font-size:1.35rem; }} .lms-login-brand small {{ display:block; margin-top:.15rem; color:{TEXT_MUTED}; }} .lms-login-title {{ margin:0 0 .35rem; color:#071B4D; font-size:1.65rem; }} .lms-login-copy {{ margin:0 0 1.1rem; color:{TEXT_MUTED}; }}
        .page-header {{ display:flex; justify-content:space-between; gap:1rem; align-items:flex-start; padding:.5rem 0 1.2rem; }}
        .page-header h1 {{ margin:.15rem 0; color:#071B4D; font-size:2rem; }} .page-header p {{ margin:0; color:#587095; }}
        .lms-breadcrumb {{ font-size:.82rem; color:{PRIMARY}; font-weight:700; }} .lms-status {{ background:#DCFCE7; color:#15803D; border-radius:999px; padding:.45rem .9rem; font-weight:700; font-size:.85rem; }}
        .status-badge {{ display:inline-block; border-radius:999px; padding:.25rem .6rem; font-size:.76rem; font-weight:700; }}
        .status-badge.success {{ background:#DCFCE7; color:#15803D; }} .status-badge.warning {{ background:#FEF3C7; color:#B45309; }} .status-badge.error {{ background:#FEE2E2; color:#B91C1C; }} .status-badge.muted {{ background:#E8EEF7; color:#53657D; }}
        .lms-empty {{ min-height:230px; display:grid; place-content:center; gap:.45rem; text-align:center; padding:2rem; }} .lms-empty h3 {{ margin:0; color:#071B4D; }} .lms-empty p {{ margin:0; }} .state-icon {{ width:72px; height:72px; margin:auto; display:grid; place-items:center; border-radius:22px; background:#E7F1FF; color:{PRIMARY}; font-size:2rem; }} .error-state .state-icon {{ background:#FEE2E2; color:{ERROR}; }}
        [data-testid="stRadio"] > div {{ gap:.45rem; flex-wrap:wrap; }} [data-testid="stRadio"] label {{ background:{SURFACE}; border:1px solid #D7E2F2; border-radius:999px; padding:.35rem .7rem; color:#405675; }} [data-testid="stRadio"] label:has(input:checked) {{ background:{PRIMARY_LIGHT}; border-color:{PRIMARY}; color:{PRIMARY_DARK}; font-weight:700; }}
        @media (max-width: 850px) {{ [data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child {{ min-width:auto !important; width:auto !important; }} [data-testid="stSidebarCollapsedControl"] {{ display:flex !important; }} .metric-card {{ flex-direction:column; }} .metric-item + .metric-item {{ border-left:0; border-top:1px solid #E2E8F0; }} .student-welcome {{ padding:1.35rem; }} }}
        </style>
        """,
        unsafe_allow_html=True,
    )
