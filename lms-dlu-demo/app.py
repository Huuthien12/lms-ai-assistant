import hmac
import os
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

from ui.components import (
    render_academic_metrics, render_calendar_card, render_citations, render_course_card,
    render_dashboard_course_card, render_document_row, render_placeholder, render_topbar,
    render_student_course_card, render_student_courses_hero,
    render_upcoming_events, render_welcome_banner, render_workspace_header, role_label,
    render_error_state, render_page_header, render_status_badge,
)
from ui.theme import inject_theme


# ==============================================================================
# 1. CẤU HÌNH BACKEND
# ==============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

FASTAPI_URL = os.getenv("LMS_FASTAPI_URL", "http://127.0.0.1:8000")

DEMO_AUTH_ENABLED = os.getenv("LMS_DEMO_AUTH_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
}
DEMO_STUDENT_PASSWORD = os.getenv("LMS_DEMO_STUDENT_PASSWORD", "")
DEMO_TEACHER_PASSWORD = os.getenv("LMS_DEMO_TEACHER_PASSWORD", "")


# ==============================================================================
# 2. CẤU HÌNH TRANG
# ==============================================================================

st.set_page_config(
    page_title="Hệ thống quản lý học tập Trường Đại học Đà Lạt LMS-DLU",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# 3. CSS - GIỮ GIAO DIỆN FRONTEND CŨ
# ==============================================================================

st.markdown("""
<style>

/* Reset & Font */

body, .stApp {
    background-color: #f6f8fb !important;
    font-family: -apple-system, BlinkMacSystemFont,
                 "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
}


/* Header chính */

.dlu-header-banner {
    background: white;
    padding: 10px 0;
    text-align: center;
    border-bottom: 2px solid #e2e8f0;
}

.dlu-logo-text {
    color: #519200;
    font-weight: 800;
    font-size: 26px;
    margin: 0;
    letter-spacing: 0.5px;
}

.dlu-logo-sub {
    color: #519200;
    font-weight: bold;
    font-size: 13px;
    margin-top: -3px;
}


/* Thanh Menu Đen */

.dlu-black-nav {
    background-color: #121212;
    color: white;
    padding: 8px 25px;
    font-size: 13px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}


/* Login */

div[data-testid="stVerticalBlockBorderWrapper"] > div {
    background-color: #f2f2f2 !important;
    padding: 20px !important;
    border-radius: 2px !important;
}

.login-error-box {
    background-color: #f8d7da;
    color: #721c24;
    border: 1px solid #f5c6cb;
    padding: 10px 15px;
    font-size: 13px;
    margin-bottom: 12px;
    border-radius: 2px;
}


/* Card khóa học */

.course-card {
    background-color: white;
    border: 1px solid #e0e0e0;
    border-radius: 3px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.banner-pink {
    height: 120px;
    background: radial-gradient(
        circle,
        #ff6b8b 0%,
        #d81b60 100%
    );
}

.banner-grey {
    height: 120px;
    background: radial-gradient(
        circle,
        #cfd8dc 0%,
        #78909c 100%
    );
}

.course-card-content {
    padding: 12px;
    min-height: 70px;
}


/* Widget */

.widget-box {
    border: 1px solid #e0e0e0;
    margin-bottom: 20px;
    border-radius: 3px;
}

.widget-header-blue {
    background-color: #0088cc;
    color: white;
    padding: 8px 12px;
    font-weight: bold;
    font-size: 14px;
}

.widget-content {
    padding: 12px;
    background-color: #fbfbfb;
    font-size: 13px;
}


/* Breadcrumb */

.dlu-breadcrumb {
    font-size: 12px;
    color: #666;
    margin-bottom: 15px;
}


/* Section */

.section-green-title {
    color: #519200;
    border-bottom: 2px solid #519200;
    padding-bottom: 3px;
    font-weight: bold;
    font-size: 16px;
    margin-top: 20px;
    margin-bottom: 10px;
}


/* Button */

div.stButton > button[kind="primary"] {
    background-color: #1565c0 !important;
    border-color: #1565c0 !important;
    color: white !important;
}


/* DeepTutor */

.deeptutor-box {
    background: #f7fbf3;
    border-left: 4px solid #519200;
    padding: 15px;
    margin-top: 15px;
    margin-bottom: 15px;
}


/* Hide Streamlit */

#MainMenu {
    visibility: hidden;
}

footer {
    visibility: hidden;
}

</style>
""", unsafe_allow_html=True)

inject_theme(st)


# ==============================================================================
# 4. API FUNCTIONS
# ==============================================================================

def api_get(endpoint, timeout=15):

    try:

        response = requests.get(
            f"{FASTAPI_URL}{endpoint}",
            timeout=timeout
        )

        if response.status_code == 200:

            return {
                "success": True,
                "data": response.json(),
                "error": None
            }

        return {
            "success": False,
            "data": None,
            "error": f"Backend returned HTTP {response.status_code}."
        }

    except requests.exceptions.ConnectionError:

        return {
            "success": False,
            "data": None,
            "error": "Không thể kết nối FastAPI Backend."
        }

    except requests.exceptions.Timeout:

        return {
            "success": False,
            "data": None,
            "error": "Backend phản hồi quá lâu."
        }

    except Exception:

        return {
            "success": False,
            "data": None,
            "error": "Backend response could not be processed."
        }


def api_post(
    endpoint,
    json_data=None,
    data=None,
    files=None,
    timeout=120
):

    try:

        response = requests.post(
            f"{FASTAPI_URL}{endpoint}",
            json=json_data,
            data=data,
            files=files,
            timeout=timeout
        )

        if response.status_code in [200, 201]:

            return {
                "success": True,
                "data": response.json(),
                "error": None
            }

        return {
            "success": False,
            "data": None,
            "error": f"Backend returned HTTP {response.status_code}."
        }

    except requests.exceptions.ConnectionError:

        return {
            "success": False,
            "data": None,
            "error": "Không thể kết nối FastAPI Backend."
        }

    except requests.exceptions.Timeout:

        return {
            "success": False,
            "data": None,
            "error": "Backend phản hồi quá lâu."
        }

    except Exception:

        return {
            "success": False,
            "data": None,
            "error": "Backend response could not be processed."
        }


# ==============================================================================
# 5. SESSION STATE
# ==============================================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "login_failed" not in st.session_state:
    st.session_state.login_failed = False

if "user_role" not in st.session_state:
    st.session_state.user_role = "student"

if "user_id" not in st.session_state:
    st.session_state.user_id = ""

if "user_name" not in st.session_state:
    st.session_state.user_name = ""

if "view_page" not in st.session_state:
    st.session_state.view_page = "dashboard"

if "selected_course" not in st.session_state:
    st.session_state.selected_course = ""

if "selected_course_id" not in st.session_state:
    st.session_state.selected_course_id = ""

if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []

if "chat_course_id" not in st.session_state:
    st.session_state.chat_course_id = ""

if "workspace_tab" not in st.session_state:
    st.session_state.workspace_tab = "Tổng quan"


# ==============================================================================
# 6. LOGIN
# ==============================================================================

if not st.session_state.logged_in:

    st.markdown(
        '<div class="lms-login-brand"><span>✦</span><div><strong>LMS DeepTutor</strong>'
        '<small>Đại học Đà Lạt · Hệ thống học tập trực tuyến</small></div></div>',
        unsafe_allow_html=True,
    )

    st.write("")

    col_left, col_right = st.columns(
        [1, 1.1],
        gap="large"
    )

    # --------------------------------------------------------------------------
    # LOGIN FORM
    # --------------------------------------------------------------------------

    with col_left:

        st.markdown(
            "<h3 class='lms-login-title'>Chào mừng trở lại</h3>"
            "<p class='lms-login-copy'>Đăng nhập để tiếp tục hành trình học tập của bạn.</p>",
            unsafe_allow_html=True
        )

        with st.container(border=True):

            if st.session_state.login_failed:

                st.markdown(
                    '<div class="login-error-box">'
                    'Đăng nhập sai, xin vui lòng thử lại'
                    '</div>',
                    unsafe_allow_html=True
                )

            username = st.text_input(
                "Tên đăng nhập/Email",
                placeholder="Tên đăng nhập/Email",
                label_visibility="collapsed"
            )

            password = st.text_input(
                "Mật khẩu",
                type="password",
                placeholder="Mật khẩu",
                label_visibility="collapsed"
            )

            st.checkbox(
                "Nhớ tên tài khoản"
            )

            if st.button(
                "Đăng nhập",
                type="primary",
                use_container_width=True
            ):

                username = username.strip().lower()

                # ==============================================================
                # SINH VIÊN
                # ==============================================================

                if (
                    DEMO_AUTH_ENABLED
                    and DEMO_STUDENT_PASSWORD
                    and
                    username in ["sv", "sv001"]
                    and hmac.compare_digest(password, DEMO_STUDENT_PASSWORD)
                ):

                    st.session_state.logged_in = True
                    st.session_state.login_failed = False

                    st.session_state.user_role = "student"

                    # ID này tồn tại trong SQL Server
                    st.session_state.user_id = "SV001"

                    st.session_state.user_name = "Nguyễn Văn A"

                    st.session_state.view_page = "dashboard"

                    st.rerun()

                # ==============================================================
                # GIẢNG VIÊN
                # ==============================================================

                elif (
                    DEMO_AUTH_ENABLED
                    and DEMO_TEACHER_PASSWORD
                    and
                    username in ["gv", "gv001"]
                    and hmac.compare_digest(password, DEMO_TEACHER_PASSWORD)
                ):

                    st.session_state.logged_in = True
                    st.session_state.login_failed = False

                    st.session_state.user_role = "teacher"

                    # ID này tồn tại trong SQL Server
                    st.session_state.user_id = "GV001"

                    st.session_state.user_name = "Trần Thị B"

                    st.session_state.view_page = "dashboard"

                    st.rerun()

                else:

                    st.session_state.login_failed = True

                    st.rerun()

            st.write("")

            st.markdown(
                "<a href='#' style='color:#666;font-size:12px;"
                "text-decoration:none;'>"
                "Quên tên đăng nhập và mật khẩu?"
                "</a>",
                unsafe_allow_html=True
            )

            st.write("")

            st.caption(
                "Trình duyệt của bạn cần phải mở "
                "chức năng quản lý cookie ❓"
            )

        st.write("")

        st.markdown(
            "#### Đăng nhập bằng tài khoản của bạn trên:"
        )

        st.button(
            "G  Google Login"
        )

    # --------------------------------------------------------------------------
    # LOGIN HELP
    # --------------------------------------------------------------------------

    with col_right:

        st.markdown(
            "<h3 style='font-size:20px;font-weight:bold;color:#333;'>"
            "Hướng dẫn đăng nhập"
            "</h3>",
            unsafe_allow_html=True
        )

        st.markdown(
            """
1. Để đăng nhập vào Hệ thống Quản lý Học tập Trường Đại học Đà Lạt:
   - Sinh viên sử dụng **MSSV**.
   - Giảng viên sử dụng tài khoản cán bộ.

2. Nếu quên mật khẩu, vui lòng sử dụng chức năng khôi phục mật khẩu.

3. Theo dõi thông báo của nhà trường trên website Đại học Đà Lạt.

---

**Tài khoản demo**

Tài khoản demo chỉ hoạt động khi được bật và cấu hình bằng biến môi trường.
"""
        )

        st.markdown(
            "#### 🔌 Trạng thái Backend"
        )

        backend_status = api_get(
            "/",
            timeout=3
        )

        if backend_status["success"]:

            st.success(
                "FastAPI Backend đang hoạt động"
            )

        else:

            st.error(
                "FastAPI Backend chưa hoạt động"
            )

            st.caption(
                backend_status["error"]
            )


# ==============================================================================
# 7. SAU KHI ĐĂNG NHẬP
# ==============================================================================

else:

    # ==========================================================================
    # HEADER
    # ==========================================================================

    role = st.session_state.user_role
    navigation = (
        [("⌂  Trang chủ", "dashboard"), ("▣  Khóa học Moodle", "courses"), ("▤  Tài liệu & Đồng bộ", "documents"),
         ("☷  Quiz & Bài tập", "quiz"), ("▥  Thống kê", "progress"), ("✦  Trò chuyện AI", "ai_tutor")]
        if role == "teacher"
        else [("⌂  Trang chủ", "dashboard"), ("▣  Khóa học của tôi", "courses"), ("▤  Tài liệu", "documents"),
              ("✦  Trò chuyện AI", "ai_tutor"), ("◉  Quiz luyện tập", "quiz"), ("▤  Flashcard", "flashcards"),
              ("▥  Tiến độ học tập", "progress")]
    )
    with st.sidebar:
        st.markdown(
            "<div class='sidebar-brand'><span>🎓</span><div><strong>LMS DeepTutor</strong>"
            "<small>Đại học Đà Lạt</small></div></div>",
            unsafe_allow_html=True,
        )
        for label, target in navigation:
            if st.button(label, key=f"nav_{target}", use_container_width=True, type="primary" if st.session_state.view_page == target else "secondary"):
                if target in {"documents", "ai_tutor"} and st.session_state.selected_course_id:
                    st.session_state.workspace_tab = "Tài liệu" if target == "documents" else "AI Tutor"
                    st.session_state.view_page = "course_detail"
                else:
                    st.session_state.view_page = target
                st.rerun()
        with st.container(key="sidebar_bottom_actions"):
            st.divider()
            if st.button("⚙  Cài đặt", key="sidebar_settings", use_container_width=True):
                st.session_state.view_page = "settings"
                st.rerun()
            if st.button("↪ Đăng xuất", key="sidebar_logout", use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.login_failed = False
                st.session_state.user_id = ""
                st.session_state.user_name = ""
                st.session_state.selected_course = ""
                st.session_state.selected_course_id = ""
                st.session_state.chat_messages = []
                st.rerun()

    page_titles = {
        "dashboard": "Tổng quan", "courses": "Môn học", "course_detail": "Chi tiết môn học",
        "documents": "Tài liệu", "ai_tutor": "AI Tutor", "sync": "Đồng bộ DeepTutor",
        "quiz": "Quiz & Bài tập", "flashcards": "Flashcard", "progress": "Tiến độ học tập", "settings": "Cài đặt",
    }
    render_topbar(
        st,
        title=page_titles.get(st.session_state.view_page, "LMS DeepTutor"),
        user_name=st.session_state.user_name,
        role=role,
        user_id=st.session_state.user_id,
    )

    if role == "student" and st.session_state.view_page == "dashboard":
        courses_result = api_get("/courses", timeout=15)
        courses_data = courses_result["data"].get("courses", []) if courses_result["success"] else []
        main_column, utility_column = st.columns([2.7, 1], gap="large")
        with main_column:
            render_welcome_banner(st, st.session_state.user_name)
            render_academic_metrics(st)
            title_column, action_column = st.columns([4, 1])
            with title_column:
                st.markdown("<h2 class='lms-section-title'>▣ Khóa học của tôi</h2>", unsafe_allow_html=True)
            with action_column:
                if st.button("Xem tất cả →", key="dashboard_all_courses"):
                    st.session_state.view_page = "courses"
                    st.rerun()
            if courses_data:
                cards = st.columns(3)
                accents = ["purple", "python", "red"]
                for index, course in enumerate(courses_data[:3]):
                    with cards[index]:
                        render_dashboard_course_card(st, course, accents[index])
                        course_id = str(course.get("course_id", ""))
                        if st.button("Vào môn học →", key=f"dashboard_course_{course_id}", use_container_width=True):
                            st.session_state.selected_course = f"{course.get('course_name', '')} ({course_id})"
                            st.session_state.selected_course_id = course_id
                            st.session_state.chat_messages = []
                            st.session_state.chat_course_id = course_id
                            st.session_state.view_page = "course_detail"
                            st.rerun()
            elif courses_result["success"]:
                render_placeholder(st, "Chưa có khóa học", "Chưa có khóa học để hiển thị.")
            else:
                render_placeholder(st, "Không thể tải khóa học", "Không thể tải danh sách khóa học.")
        with utility_column:
            render_calendar_card(st)
            render_upcoming_events(st)
        st.stop()

    if role == "student" and st.session_state.view_page == "courses":
        courses_result = api_get("/courses", timeout=15)
        courses_data = courses_result["data"].get("courses", []) if courses_result["success"] else []
        render_student_courses_hero(st, len(courses_data))
        if not courses_result["success"]:
            render_error_state(st, "Không thể tải danh sách khóa học. Vui lòng thử lại.")
            if st.button("Thử tải lại", key="student_courses_retry"):
                st.rerun()
            st.stop()
        controls_left, controls_right = st.columns([3, 1])
        with controls_left:
            course_query = st.text_input("Tìm kiếm khóa học", placeholder="Tìm kiếm khóa học...", key="student_courses_query")
        with controls_right:
            sort_by = st.selectbox("Sắp xếp", ["Mã môn học", "Tên khóa học"], key="student_courses_sort")
        query = course_query.strip().casefold()
        visible_courses = [course for course in courses_data if not query or query in str(course.get("course_id", "")).casefold() or query in str(course.get("course_name", "")).casefold()]
        visible_courses.sort(key=lambda course: str(course.get("course_id" if sort_by == "Mã môn học" else "course_name", "")).casefold())
        if not visible_courses:
            render_placeholder(st, "Không tìm thấy khóa học", "Thử thay đổi từ khóa tìm kiếm.")
            st.stop()
        cards = st.columns(3)
        accents = ["violet", "sky", "amber"]
        for index, course in enumerate(visible_courses):
            course_id, course_name = str(course.get("course_id", "")), str(course.get("course_name", ""))
            with cards[index % 3]:
                render_student_course_card(st, course, accents[index % len(accents)])
                if st.button("Xem chi tiết  →", key=f"student_course_{course_id}", use_container_width=True):
                    st.session_state.selected_course = f"{course_name} ({course_id})"
                    st.session_state.selected_course_id = course_id
                    st.session_state.chat_messages = []
                    st.session_state.chat_course_id = course_id
                    st.session_state.view_page = "course_detail"
                    st.rerun()
        st.stop()

    c_h1, c_h2 = st.columns(
        [3, 1]
    )

    with c_h1:

        st.markdown(
            '<div style="display:flex;align-items:center;gap:15px;padding:5px 0;">'
            '<div>'
            '<h2 style="color:#519200;margin:0;font-size:22px;font-weight:bold;">'
            'TRƯỜNG ĐẠI HỌC ĐÀ LẠT'
            '</h2>'
            '<div style="color:#519200;font-size:10px;font-weight:bold;">'
            'DALAT UNIVERSITY'
            '</div>'
            '<div style="color:#519200;font-size:13px;font-weight:bold;">'
            'HỆ THỐNG HỌC TẬP TRỰC TUYẾN - LMS'
            '</div>'
            '</div>'
            '</div>',
            unsafe_allow_html=True
        )

    with c_h2:

        role_name = (
            "Sinh viên"
            if st.session_state.user_role == "student"
            else "Giảng viên"
        )

        st.write(
            f"🔔 💬 **{st.session_state.user_name}** ▾"
        )

        st.caption(
            f"{role_name} • {st.session_state.user_id}"
        )

        user_opt = st.selectbox(
            "User Actions",
            [
                "-- Menu --",
                "Bảng điều khiển",
                "Hồ sơ",
                "Điểm",
                "Đăng xuất"
            ],
            label_visibility="collapsed"
        )

        if user_opt == "Đăng xuất":

            st.session_state.logged_in = False
            st.session_state.login_failed = False
            st.session_state.user_id = ""
            st.session_state.user_name = ""
            st.session_state.selected_course = ""
            st.session_state.selected_course_id = ""
            st.session_state.chat_messages = []

            st.rerun()

        elif user_opt == "Bảng điều khiển":

            st.session_state.view_page = "dashboard"

            st.rerun()


    # ==========================================================================
    # The authenticated shell is rendered by the persistent sidebar and topbar.
    # Clear the legacy header containers so they do not reserve vertical space.
    c_h1.empty()
    c_h2.empty()

    # BLACK NAV
    # ==========================================================================

    st.markdown(
        '<div class="dlu-black-nav">'
        '<div>'
        '<span style="background:#519200;padding:3px 8px;font-weight:bold;">'
        'LMS-DLU'
        '</span>'
        '&nbsp;&nbsp; Đơn vị ▾'
        '&nbsp;&nbsp; ITC ▾'
        '&nbsp;&nbsp; Tiếng Việt (vi) ▾'
        '</div>'
        '<div>🔍</div>'
        '</div>',
        unsafe_allow_html=True
    )

    st.write("")


    # ==========================================================================
    # 8. DASHBOARD
    # ==========================================================================

    if st.session_state.view_page in {"dashboard", "courses"}:

        if role == "teacher":
            if st.session_state.view_page == "dashboard":
                render_page_header(
                    st, eyebrow="Trang chủ", title="Xin chào, giảng viên!",
                    description="Tổng quan các khóa học và hoạt động giảng dạy.",
                )
                metrics = st.columns(4)
                for column, (value, label) in zip(metrics, [("--", "Tổng số khóa học"), ("--", "Tổng sinh viên"), ("--", "Tài liệu đã chia sẻ"), ("--", "Tổng bài kiểm tra")]):
                    with column:
                        st.metric(label, value)
            else:
                render_page_header(st, eyebrow="Trang chủ › Moodle Courses", title="Khóa học Moodle", description="Quản lý và đồng bộ dữ liệu khóa học từ Moodle với DeepTutor.")
            st.markdown("<h2 class='lms-section-title'>Khóa học Moodle phụ trách</h2>", unsafe_allow_html=True)
            moodle_courses = api_get("/moodle/courses", timeout=15)
            if not moodle_courses["success"]:
                render_error_state(st, "Không thể tải danh sách môn học Moodle. Vui lòng kiểm tra kết nối Moodle và thử lại.")
            elif not moodle_courses["data"]:
                render_placeholder(st, "Chưa có khóa học Moodle", "Các khóa học được phân quyền sẽ xuất hiện tại đây.")
            else:
                for course in moodle_courses["data"]:
                    shortname = str(course.get("shortname") or "")
                    fullname = str(course.get("fullname") or shortname)
                    with st.container(border=True):
                        row_info, row_action = st.columns([5, 1])
                        with row_info:
                            st.markdown(f"**{fullname}**")
                            st.caption(shortname)
                        with row_action:
                            if st.button("Xem chi tiết", key=f"moodle_course_{course.get('id')}", use_container_width=True):
                                st.session_state.selected_moodle_course_id = int(course["id"])
                                st.session_state.selected_course_id = shortname
                                st.session_state.selected_course = f"{fullname} ({shortname})"
                                st.session_state.view_page = "course_detail"
                                st.session_state.workspace_tab = "Tài liệu"
                                st.rerun()
            st.stop()

        if st.session_state.view_page == "courses":
            courses_result = api_get("/courses", timeout=15)
            courses_data = courses_result["data"].get("courses", []) if courses_result["success"] else []
            render_student_courses_hero(st, len(courses_data))
            if not courses_result["success"]:
                render_error_state(st, "Không thể tải danh sách khóa học. Vui lòng thử lại.")
                if st.button("Thử tải lại", key="student_courses_retry"):
                    st.rerun()
                st.stop()

            controls_left, controls_right = st.columns([3, 1])
            with controls_left:
                course_query = st.text_input("Tìm kiếm khóa học", placeholder="Tìm kiếm khóa học...", key="student_courses_query")
            with controls_right:
                sort_by = st.selectbox("Sắp xếp", ["Mã môn học", "Tên khóa học"], key="student_courses_sort")
            query = course_query.strip().casefold()
            visible_courses = [course for course in courses_data if not query or query in str(course.get("course_id", "")).casefold() or query in str(course.get("course_name", "")).casefold()]
            visible_courses.sort(key=lambda course: str(course.get("course_id" if sort_by == "Mã môn học" else "course_name", "")).casefold())
            if not visible_courses:
                render_placeholder(st, "Không tìm thấy khóa học", "Thử thay đổi từ khóa tìm kiếm.")
                st.stop()

            cards = st.columns(3)
            accents = ["violet", "sky", "amber"]
            for index, course in enumerate(visible_courses):
                course_id, course_name = str(course.get("course_id", "")), str(course.get("course_name", ""))
                with cards[index % 3]:
                    render_student_course_card(st, course, accents[index % len(accents)])
                    if st.button("Xem chi tiết  →", key=f"student_course_{course_id}", use_container_width=True):
                        st.session_state.selected_course = f"{course_name} ({course_id})"
                        st.session_state.selected_course_id = course_id
                        st.session_state.chat_messages = []
                        st.session_state.chat_course_id = course_id
                        st.session_state.view_page = "course_detail"
                        st.rerun()
            st.stop()

        st.markdown(
            '<div class="dlu-breadcrumb">'
            'Bảng Điều khiển > Các khoá học của tôi > Thêm...'
            '</div>',
            unsafe_allow_html=True
        )

        c_left_main, c_right_sidebar = st.columns(
            [2.7, 1.1],
            gap="large"
        )

        # ======================================================================
        # COURSE LIST
        # ======================================================================

        with c_left_main:

            st.markdown(
                "#### ✳️ Khóa học từ Cơ sở dữ liệu"
            )

            courses_result = api_get(
                "/courses",
                timeout=15
            )

            if courses_result["success"]:

                courses_data = (
                    courses_result["data"]
                    .get("courses", [])
                )

                if courses_data:

                    cols = st.columns(2)

                    for idx, course in enumerate(
                        courses_data
                    ):

                        with cols[idx % 2]:

                            course_id = course.get(
                                "course_id",
                                ""
                            )

                            course_name = course.get(
                                "course_name",
                                ""
                            )

                            description = (
                                course.get("description")
                                or ""
                            )

                            banner_class = (
                                "banner-pink"
                                if idx % 2 == 0
                                else "banner-grey"
                            )

                            # HTML được nối thành 1 chuỗi
                            # để tránh Streamlit hiển thị <div> thành code.
                            course_html = (
                                '<div class="course-card">'
                                f'<div class="{banner_class}"></div>'
                                '<div class="course-card-content">'
                                f'<span style="font-size:11px;color:#888;">'
                                f'Mã môn: {course_id}'
                                '</span><br>'
                                f'<b style="font-size:13px;">'
                                f'{course_name}'
                                '</b><br>'
                                f'<p style="font-size:11px;color:#555;'
                                f'margin-top:4px;">'
                                f'{description}'
                                '</p>'
                                '</div>'
                                '</div>'
                            )

                            render_course_card(st, course)

                            if st.button(
                                f"Vào môn học",
                                key=f"btn_course_{course_id}",
                                use_container_width=True
                            ):

                                st.session_state.selected_course = (
                                    f"{course_name} ({course_id})"
                                )

                                st.session_state.selected_course_id = (
                                    course_id
                                )

                                st.session_state.view_page = (
                                    "course_detail"
                                )

                                st.session_state.chat_messages = []

                                st.session_state.chat_course_id = (
                                    course_id
                                )

                                st.rerun()

                else:

                    st.info(
                        "Chưa có khóa học nào "
                        "trong cơ sở dữ liệu."
                    )

            else:

                st.error(
                    "Không thể lấy danh sách môn học "
                    "từ Backend."
                )

                st.caption(
                    courses_result["error"]
                )

                if st.button(
                    "🔄 Thử tải lại"
                ):

                    st.rerun()

            st.write("")

            st.markdown(
                "#### ✳️ Tổng quan khóa học"
            )

            st.button(
                "Tất cả",
                type="primary"
            )

        # ======================================================================
        # RIGHT SIDEBAR
        # ======================================================================

        with c_right_sidebar:

            # Không dùng HTML multiline để tránh lỗi render.

            st.markdown(
                '<div class="widget-header-blue">📅 Lịch</div>',
                unsafe_allow_html=True
            )

            with st.container(border=True):

                st.markdown(
                    "<div style='text-align:center;font-size:13px;'>"
                    "<b>Tháng 9 2026</b>"
                    "</div>",
                    unsafe_allow_html=True
                )

                st.write("")

                week_header = st.columns(7)

                days = [
                    "T2", "T3", "T4",
                    "T5", "T6", "T7", "CN"
                ]

                for i, day in enumerate(days):

                    with week_header[i]:

                        st.caption(
                            day
                        )

                week = st.columns(7)

                dates = [
                    "14", "15", "16",
                    "17", "18", "19", "20"
                ]

                for i, date in enumerate(dates):

                    with week[i]:

                        if date == "17":

                            st.markdown(
                                "**17**"
                            )

                        else:

                            st.write(
                                date
                            )

            st.write("")

            st.markdown(
                '<div class="widget-header-blue">'
                '📅 Sự kiện sắp tới'
                '</div>',
                unsafe_allow_html=True
            )

            with st.container(border=True):

                st.markdown(
                    "🍃 **Điểm danh**"
                )

                st.caption(
                    "Thứ năm, 17 Tháng 9, "
                    "7:45 AM » 7:50 AM"
                )

                st.write("")

                st.markdown(
                    "📄 **Bài thực hành 01 đến hạn**"
                )

                st.caption(
                    "Thứ năm, 17 Tháng 9, "
                    "11:59 PM"
                )


    # ==========================================================================
    # 9. COURSE DETAIL
    # ==========================================================================

    elif st.session_state.view_page == "settings":
        render_page_header(st, eyebrow="Trang chủ › Cài đặt", title="Cài đặt", description="Thông tin tài khoản và tùy chọn giao diện.")
        profile, preferences = st.columns([1.4, 1])
        with profile:
            with st.container(border=True):
                st.subheader("Hồ sơ cá nhân")
                st.text_input("Họ và tên", value=st.session_state.user_name, disabled=True)
                st.text_input("Mã tài khoản", value=st.session_state.user_id, disabled=True)
                st.caption("Thông tin hồ sơ được quản lý bởi hệ thống nguồn.")
        with preferences:
            with st.container(border=True):
                st.subheader("Tùy chọn giao diện")
                st.radio("Giao diện", ["Sáng", "Tự động"], horizontal=True, disabled=True)
                st.caption("Các tùy chọn lưu hồ sơ chưa có API công khai.")

    elif st.session_state.view_page in {"quiz", "flashcards", "progress"}:
        titles = {
            "quiz": ("Quiz luyện tập", "Chọn một môn học để bắt đầu làm quiz từ nội dung được giảng viên cung cấp."),
            "flashcards": ("Flashcard", "Chọn một môn học để ôn tập bằng flashcard."),
            "progress": ("Tiến độ học tập", "Dữ liệu tiến độ sẽ hiển thị khi có thông tin học tập phù hợp."),
        }
        title, message = titles[st.session_state.view_page]
        render_page_header(st, eyebrow="Trang chủ", title=title, description=message)
        render_placeholder(st, title, message)
        if st.button("Chọn môn học", type="primary", key=f"{st.session_state.view_page}_courses"):
            st.session_state.view_page = "courses"
            st.rerun()

    elif st.session_state.view_page == "documents":
        render_placeholder(
            st,
            "Tài liệu",
            "Chọn một môn học để xem tài liệu hiện có. Chức năng duyệt tài nguyên Moodle sẽ được bổ sung khi có API phù hợp.",
        )
        if st.button("Mở danh sách môn học", type="primary", key="documents_courses"):
            st.session_state.view_page = "courses"
            st.rerun()

    elif st.session_state.view_page == "ai_tutor":
        render_placeholder(
            st,
            "AI Tutor",
            "Chọn một môn học để sử dụng DeepTutor trong đúng ngữ cảnh môn học và xem trích dẫn nguồn gốc.",
        )
        if st.button("Chọn môn học", type="primary", key="tutor_courses"):
            st.session_state.view_page = "courses"
            st.rerun()

    elif st.session_state.view_page == "sync":
        render_placeholder(
            st,
            "Đồng bộ DeepTutor",
            "Trạng thái đồng bộ Moodle sẽ được hiển thị tại đây khi giao diện có API duyệt tài nguyên Moodle an toàn.",
        )

    elif st.session_state.view_page == "course_detail":

        course_id = (
            st.session_state.selected_course_id
        )

        workspace_tab = render_workspace_header(
            st, course_id, st.session_state.selected_course or "Môn học", role
        )

        st.markdown(
            '<div class="dlu-breadcrumb">'
            'Bảng Điều khiển > '
            'Các khoá học của tôi > '
            'Khoa Công nghệ Thông tin > '
            f'{st.session_state.selected_course}'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button(
            "⬅️ Quay lại Bảng điều khiển"
        ):

            st.session_state.view_page = (
                "dashboard"
            )

            st.rerun()

        if workspace_tab == "Tổng quan":
            st.markdown("💬 **Thông báo chung**")
            st.markdown("🍃 **Điểm danh lớp học**")


        # ======================================================================
        # TÀI LIỆU MÔN HỌC
        # ======================================================================

        if workspace_tab == "Tài liệu":
            st.markdown(
                '<div class="section-green-title">'
                'Tài liệu môn học'
                '</div>',
                unsafe_allow_html=True
            )

        if st.session_state.user_role == "teacher" and st.session_state.get("selected_moodle_course_id"):
            resources_result = api_get(f"/moodle/courses/{st.session_state.selected_moodle_course_id}/resources", timeout=30)
            if workspace_tab in {"Tài liệu", "Đồng bộ DeepTutor"} and resources_result["success"]:
                for resource in resources_result["data"]:
                    with st.container(border=True):
                        st.markdown(f"**{resource.get('filename', 'Tài liệu')}**")
                        st.caption(f"{resource.get('format', 'FILE')} · Moodle")
                        status = resource.get("sync_status", "not_synced")
                        st.write("DeepTutor: " + {"indexed": "Đã đồng bộ", "superseded": "Đã thay thế", "deleted": "Đã xóa"}.get(status, "Chưa đồng bộ"))
                        if status == "indexed":
                            st.caption(f"KB: {resource.get('kb_id', '')}")
                        elif resource.get("format") != "UNSUPPORTED" and st.button("Đồng bộ DeepTutor", key=f"sync_{resource.get('resource_id')}"):
                            result = api_post("/moodle/resources/ingest", json_data={"course_id_moodle": st.session_state.selected_moodle_course_id, "resource_id": resource["resource_id"]}, timeout=180)
                            if result["success"]:
                                st.success("Đã đồng bộ DeepTutor.")
                                st.rerun()
                            else:
                                st.error("Đồng bộ DeepTutor thất bại.")
            elif workspace_tab in {"Tài liệu", "Đồng bộ DeepTutor"}:
                render_error_state(st, "Không thể tải tài liệu Moodle.")
            materials_result = {"success": True, "data": {"materials": []}}
        else:
            materials_result = api_get(
            f"/courses/{course_id}/materials",
            timeout=180
            )

        if materials_result["success"]:

            materials = (
                materials_result["data"]
                .get("materials", [])
            )

            if workspace_tab == "Tài liệu" and materials:

                for material in materials:

                    file_name = material.get(
                        "file_name",
                        "Tài liệu"
                    )

                    uploaded_at = material.get(
                        "uploaded_at",
                        ""
                    )

                    extension = (
                        file_name.split(".")[-1].lower()
                        if "." in file_name
                        else ""
                    )

                    if extension == "pdf":

                        icon = "📕"

                    elif extension == "docx":

                        icon = "📘"

                    elif extension == "txt":

                        icon = "📄"

                    else:

                        icon = "📎"

                    render_document_row(st, material)

                    if uploaded_at:

                        st.caption(
                            f"Ngày tải lên: {uploaded_at}"
                        )

                    st.divider()

            elif workspace_tab == "Tài liệu" and not (
                st.session_state.user_role == "teacher"
                and st.session_state.get("selected_moodle_course_id")
            ):

                st.info(
                    "Môn học này chưa có tài liệu."
                )

        else:

            st.error(
                "Không thể tải tài liệu môn học."
            )

            st.caption(
                materials_result["error"]
            )


        # ======================================================================
        # BÀI TẬP
        # ======================================================================

        if workspace_tab == "Tổng quan":
            st.markdown(
                '<div class="section-green-title">'
                'Lý thuyết & Bài tập'
                '</div>',
                unsafe_allow_html=True
            )

        assignments_result = api_get(
            f"/courses/{course_id}/assignments",
            timeout=15
        )

        if assignments_result["success"]:

            assignments = (
                assignments_result["data"]
                .get("assignments", [])
            )

            if workspace_tab == "Tổng quan" and assignments:

                for assignment in assignments:

                    st.markdown(
                        "📝 **"
                        + str(
                            assignment.get(
                                "title",
                                "Bài tập"
                            )
                        )
                        + "**"
                    )

                    st.caption(
                        "Hạn nộp: "
                        + str(
                            assignment.get(
                                "due_date",
                                ""
                            )
                        )
                    )

                    st.divider()

            elif workspace_tab == "Tổng quan":

                st.caption(
                    "Chưa có bài tập."
                )

        else:

            st.warning(
                "Không thể tải danh sách bài tập."
            )

            st.caption(
                assignments_result["error"]
            )


        # ======================================================================
        # DEEPTUTOR / MATERIAL MANAGEMENT
        # ======================================================================

        if workspace_tab != "Tổng quan":
            st.markdown(
                '<div class="section-green-title">'
                'Tài liệu tham khảo & DeepTutor AI'
                '</div>',
                unsafe_allow_html=True
            )


        # ======================================================================
        # 10. GIẢNG VIÊN
        # ======================================================================

        if workspace_tab == "Tài liệu" and st.session_state.user_role == "teacher" and not st.session_state.get("selected_moodle_course_id"):

            st.subheader(
                "👨‍🏫 Quản lý tài liệu môn học "
                "(Tích hợp DeepTutor AI)"
            )

            st.caption(
                f"Môn hiện tại: "
                f"{st.session_state.selected_course}"
            )

            with st.container(border=True):

                st.write(
                    "📤 **Tải lên tài liệu mới "
                    "cho hệ thống:**"
                )

                course_id_ipt = st.text_input(
                    "Mã môn học",
                    value=course_id,
                    disabled=True
                )

                uploaded_file = st.file_uploader(
                    "Chọn file tài liệu "
                    "(.pdf, .docx, .txt):",
                    type=[
                        "pdf",
                        "docx",
                        "txt"
                    ]
                )

                if uploaded_file is not None:

                    st.info(
                        f"Đã chọn: "
                        f"{uploaded_file.name}"
                    )

                    size_mb = (
                        len(
                            uploaded_file.getvalue()
                        )
                        / 1024
                        / 1024
                    )

                    st.caption(
                        f"Kích thước: "
                        f"{size_mb:.2f} MB"
                    )

                if st.button(
                    "📤 Tải tài liệu lên hệ thống",
                    type="primary",
                    use_container_width=True
                ):

                    if not uploaded_file:

                        st.warning(
                            "Vui lòng chọn file "
                            "đính kèm!"
                        )

                    else:

                        files = {
                            "file": (
                                uploaded_file.name,
                                uploaded_file.getvalue(),
                                uploaded_file.type
                            )
                        }

                        data = {
                            "course_id":
                                course_id_ipt
                        }

                        with st.spinner(
                            "Đang tải file lên Backend..."
                        ):

                            upload_result = api_post(
                                "/upload-material/",
                                data=data,
                                files=files,
                                timeout=120
                            )

                        if upload_result["success"]:

                            st.success(
                                f"✅ Tải thành công "
                                f"`{uploaded_file.name}` "
                                f"lên môn {course_id}."
                            )

                            st.balloons()

                            # Reload để file mới xuất hiện
                            st.rerun()

                        else:

                            st.error(
                                "Upload thất bại."
                            )

                            st.code(
                                upload_result["error"]
                            )


        # ======================================================================
        # 11. SINH VIÊN + DEEPTUTOR CHAT
        # ======================================================================

        elif workspace_tab == "AI Tutor" and st.session_state.user_role != "teacher":

            st.write(
                "📖 Sinh viên có thể xem tài liệu "
                "học tập do giảng viên cung cấp "
                "cho môn học này."
            )

            st.info(
                "💡 Bạn có thể hỏi DeepTutor AI "
                "các nội dung liên quan trực tiếp "
                "đến tài liệu của môn học."
            )

            st.markdown(
                '<div class="deeptutor-box">'
                '<b>🤖 DeepTutor AI</b><br>'
                'Trợ lý học tập AI của môn học.'
                '</div>',
                unsafe_allow_html=True
            )

            # ------------------------------------------------------------------
            # Nếu đổi môn -> reset chat trên giao diện
            # ------------------------------------------------------------------

            if (
                st.session_state.chat_course_id
                != course_id
            ):

                st.session_state.chat_messages = []

                st.session_state.chat_course_id = (
                    course_id
                )

            # ------------------------------------------------------------------
            # LOAD CHAT HISTORY
            # ------------------------------------------------------------------

            if not st.session_state.chat_messages:

                history_result = api_get(
                    f"/chat/history/"
                    f"{st.session_state.user_id}/"
                    f"{course_id}",
                    timeout=15
                )

                if history_result["success"]:

                    history = (
                        history_result["data"]
                        .get("history", [])
                    )

                    for item in history:

                        user_message = (
                            item.get(
                                "user_message",
                                ""
                            )
                        )

                        bot_response = (
                            item.get(
                                "bot_response",
                                ""
                            )
                        )

                        if user_message:

                            st.session_state.chat_messages.append(
                                {
                                    "role": "user",
                                    "content": user_message
                                }
                            )

                        if bot_response:

                            st.session_state.chat_messages.append(
                                {
                                    "role": "assistant",
                                    "content": bot_response
                                }
                            )

            # ------------------------------------------------------------------
            # DISPLAY CHAT
            # ------------------------------------------------------------------

            for message in (
                st.session_state.chat_messages
            ):

                with st.chat_message(
                    message["role"]
                ):

                    st.markdown(
                        message["content"]
                    )

            # ------------------------------------------------------------------
            # CHAT INPUT
            # ------------------------------------------------------------------

            prompt = st.chat_input(
                "Hỏi DeepTutor về tài liệu môn học..."
            )

            if prompt:

                st.session_state.chat_messages.append(
                    {
                        "role": "user",
                        "content": prompt
                    }
                )

                with st.chat_message(
                    "user"
                ):

                    st.markdown(
                        prompt
                    )

                chat_payload = {
                    "question": prompt,
                    "course_id": course_id,
                }

                with st.chat_message(
                    "assistant"
                ):

                    with st.spinner(
                        "DeepTutor đang xử lý câu hỏi..."
                    ):

                        chat_result = api_post(
                            "/lms/chat",
                            json_data=chat_payload,
                            timeout=120
                        )

                    if chat_result["success"]:

                        response_data = (
                            chat_result["data"]
                        )

                        answer = (
                            response_data.get(
                                "answer"
                            )
                            or
                            response_data.get(
                                "bot_response"
                            )
                            or
                            response_data.get(
                                "message"
                            )
                            or
                            "Backend không trả về "
                            "nội dung câu trả lời."
                        )

                        st.markdown(
                            answer
                        )

                        st.session_state.chat_messages.append(
                            {
                                "role": "assistant",
                                "content": answer
                            }
                        )

                        render_citations(st, response_data.get("sources", []))

                        ai = response_data.get("ai")
                        if isinstance(ai, dict):
                            provider, model = ai.get("provider"), ai.get("model")
                            if isinstance(provider, str) and isinstance(model, str):
                                st.caption(f"{response_data.get('kb_name', '')} · {provider} / {model}")

                        # Backend hiện tại có thể đang
                        # ở trạng thái chưa kết nối DeepTutor thật.
                        if (
                            response_data.get(
                                "deeptutor_connected"
                            )
                            is False
                        ):

                            st.caption(
                                "⚠️ FastAPI đã nhận câu hỏi, "
                                "nhưng DeepTutor thật chưa "
                                "được kết nối vào backend."
                            )

                    else:

                        error_text = (
                            "Không thể gửi câu hỏi "
                            "đến Backend: "
                            + chat_result["error"]
                        )

                        st.error(
                            error_text
                        )

            # ------------------------------------------------------------------
            # XÓA LỊCH SỬ CHAT
            # ------------------------------------------------------------------

            if st.session_state.chat_messages:

                if st.button(
                    "🗑️ Xóa lịch sử chat",
                    use_container_width=True,
                    key=f"clear_chat_{course_id}"
                ):

                    try:

                        # Lấy đúng ID sinh viên đang đăng nhập
                        student_id = st.session_state.user_id

                        # course_id đã được lấy từ:
                        # st.session_state.selected_course_id
                        response = requests.delete(
                            f"{FASTAPI_URL}/chat/history/"
                            f"{student_id}/"
                            f"{course_id}",
                            timeout=15
                        )

                        if response.status_code == 200:

                            # Xóa đúng session state mà app đang sử dụng
                            st.session_state.chat_messages = []

                            st.success(
                                "✅ Đã xóa lịch sử chat."
                            )

                            st.rerun()

                        else:

                            st.error(
                                "❌ Không thể xóa lịch sử chat."
                            )

                    except requests.exceptions.ConnectionError:

                        st.error(
                            "❌ Không thể kết nối FastAPI Backend."
                        )

                    except requests.exceptions.Timeout:

                        st.error(
                            "❌ Backend phản hồi quá lâu."
                        )

                    except Exception as e:

                        st.error(
                            "❌ Không thể xóa lịch sử chat."
                        )

        if workspace_tab in {"Quiz", "Flashcard", "Tiến độ", "Quiz & Bài tập", "Sinh viên", "Thống kê"}:
            labels = {
                "Quiz": "Quiz luyện tập", "Flashcard": "Flashcard", "Tiến độ": "Tiến độ học tập",
                "Quiz & Bài tập": "Quiz & Bài tập", "Sinh viên": "Sinh viên", "Thống kê": "Thống kê",
            }
            render_placeholder(st, labels[workspace_tab], "Chưa có dữ liệu công khai phù hợp cho khóa học này.")
