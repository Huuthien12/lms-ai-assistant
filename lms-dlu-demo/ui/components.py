"""Reusable Streamlit presentation components for the LMS shell."""

from __future__ import annotations

import calendar
from datetime import date
from html import escape
from typing import Any


def role_label(role: str) -> str:
    return "Giảng viên" if role == "teacher" else "Sinh viên"


def render_topbar(st, *, title: str, user_name: str, role: str, user_id: str = "") -> None:
    initial = escape((user_name or "?")[0].upper())
    st.markdown(
        f"""
        <div class="lms-topbar">
          <div class="lms-search">⌕ <span>Tìm kiếm khóa học, tài liệu, ...</span></div>
          <div class="lms-account"><span class="lms-notice">♧</span><span class="lms-avatar">{initial}</span>
          <span><strong>{escape(user_name)}</strong><small>{role_label(role)}{f' · {escape(user_id)}' if user_id else ''}</small></span><span>⌄</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_welcome_banner(st, user_name: str) -> None:
    today = date.today().strftime("%d/%m/%Y")
    st.markdown(
        f"""<div class="student-welcome"><div><span>{today}</span><h1>Chào mừng trở lại, {escape(user_name)}!</h1>
        <p>Tiếp tục hành trình học tập cùng LMS DeepTutor</p></div><div class="welcome-orbit">✦<span>⌘</span></div></div>""",
        unsafe_allow_html=True,
    )


def render_academic_metrics(st) -> None:
    metrics = [("metric-blue", "--", "Điểm trung bình"), ("metric-green", "--", "Hoạt động học tập"), ("metric-orange", "--", "Tỷ lệ tham dự")]
    cards = "".join(f"<div class='metric-item'><div class='metric-ring {color}'>{value}</div><strong>{label}</strong><span>Xem chi tiết →</span></div>" for color, value, label in metrics)
    st.markdown(f"<div class='metric-card'>{cards}</div>", unsafe_allow_html=True)


def render_dashboard_course_card(st, course: dict[str, Any], accent: str) -> None:
    course_id = escape(str(course.get("course_id", "")))
    course_name = escape(str(course.get("course_name", "Môn học")))
    description = escape(str(course.get("description") or "Chưa có mô tả môn học."))
    st.markdown(
        f"<div class='dashboard-course {accent}'><div class='course-icon'>▣</div><div class='course-code'>{course_id}</div><div class='course-name'>{course_name}</div><div class='course-meta'>{description}</div></div>",
        unsafe_allow_html=True,
    )


def render_student_courses_hero(st, course_count: int) -> None:
    st.markdown(
        f"<div class='courses-hero'><div><h1>Khóa học của tôi</h1>"
        f"<p>Danh sách các khóa học bạn đang tham gia</p></div>"
        f"<div class='courses-hero-art'>▣</div></div>"
        f"<div class='courses-count'>▣ Tất cả ({course_count})</div>",
        unsafe_allow_html=True,
    )


def render_course_detail_hero(st, course_id: str, course_name: str) -> None:
    st.markdown(
        f"<div class='course-breadcrumb'>Khóa học của tôi　›　{escape(course_id)}</div>"
        f"<div class='course-detail-hero'><div class='course-detail-icon'>▣</div><div>"
        f"<div class='course-code'>{escape(course_id)}</div><h1>{escape(course_name)}</h1>"
        f"<p>Thông tin khóa học được hiển thị từ dữ liệu được cấp quyền.</p></div></div>",
        unsafe_allow_html=True,
    )


def render_student_course_overview(st, course_id: str, course_name: str) -> None:
    description = "Thông tin khóa học được hiển thị từ dữ liệu được cấp quyền."
    left, right = st.columns([2, 1], gap="large")
    with left:
        st.markdown(
            f"<div class='course-overview-card'><h2>▤　Giới thiệu môn học</h2>"
            f"<p>{description}</p></div>", unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f"<div class='course-overview-card'><h2>ⓘ　Thông tin cơ bản</h2>"
            f"<dl><dt>Mã môn học</dt><dd>{escape(course_id)}</dd>"
            f"<dt>Tên môn học</dt><dd>{escape(course_name)}</dd>"
            f"<dt>Mô tả</dt><dd>{description}</dd></dl></div>", unsafe_allow_html=True,
        )


def render_student_course_card(st, course: dict[str, Any], accent: str) -> None:
    course_id = escape(str(course.get("course_id", "")))
    course_name = escape(str(course.get("course_name", "Môn học")))
    description = escape(str(course.get("description") or "Chưa có mô tả môn học."))
    st.markdown(
        f"<div class='student-course {accent}'><div class='student-course-banner'><span>▣</span></div>"
        f"<div class='student-course-body'><div class='course-code'>{course_id}</div>"
        f"<h3>{course_name}</h3><p>{description}</p></div></div>",
        unsafe_allow_html=True,
    )


def render_calendar_card(st) -> None:
    current = date.today()
    weeks = calendar.monthcalendar(current.year, current.month)
    days = "".join(f"<span>{day}</span>" for day in ("T2", "T3", "T4", "T5", "T6", "T7", "CN"))
    cells = "".join("<span></span>" if day == 0 else f"<span class='calendar-today'>{day}</span>" if day == current.day else f"<span>{day}</span>" for week in weeks for day in week)
    st.markdown(f"<div class='utility-card'><h3>▣ Lịch học</h3><h4>Tháng {current.month}, {current.year}</h4><div class='calendar-grid calendar-days'>{days}</div><div class='calendar-grid'>{cells}</div></div>", unsafe_allow_html=True)


def render_upcoming_events(st) -> None:
    st.markdown("<div class='utility-card'><h3>◷ Sự kiện sắp tới</h3><div class='utility-empty'>Chưa có sự kiện sắp tới</div></div>", unsafe_allow_html=True)


def render_course_card(st, course: dict[str, Any]) -> None:
    """Render one backend-supplied course without inventing course metadata."""
    course_id = escape(str(course.get("course_id", "")))
    course_name = escape(str(course.get("course_name", "Môn học")))
    description = escape(str(course.get("description") or "Chưa có mô tả môn học."))
    st.markdown(
        f"""
        <div class="course-card">
          <div class="course-code">{course_id}</div>
          <div class="course-name">{course_name}</div>
          <div class="course-meta">{description}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_placeholder(st, title: str, message: str) -> None:
    st.markdown(f"<h2 class='lms-page-title'>{title}</h2>", unsafe_allow_html=True)
    st.markdown(f"<div class='lms-empty'><div class='state-icon'>◇</div><h3>Chưa có dữ liệu</h3><p>{escape(message)}</p></div>", unsafe_allow_html=True)


def render_page_header(st, *, eyebrow: str, title: str, description: str = "", status: str = "") -> None:
    badge = f"<span class='lms-status'>{escape(status)}</span>" if status else ""
    st.markdown(
        f"<div class='page-header'><div><p class='lms-breadcrumb'>{escape(eyebrow)}</p>"
        f"<h1>{escape(title)}</h1><p>{escape(description)}</p></div>{badge}</div>",
        unsafe_allow_html=True,
    )


def render_status_badge(st, status: str) -> None:
    labels = {"indexed": ("Đã đồng bộ", "success"), "not_synced": ("Chưa đồng bộ", "muted"),
              "superseded": ("Đã thay thế", "warning"), "deleted": ("Đã xóa", "error")}
    label, tone = labels.get(status, ("Đang xử lý", "warning"))
    st.markdown(f"<span class='status-badge {tone}'>{label}</span>", unsafe_allow_html=True)


def render_error_state(st, message: str) -> None:
    st.markdown(
        f"<div class='lms-empty error-state'><div class='state-icon'>!</div><h3>Không thể tải nội dung</h3>"
        f"<p>{escape(message)}</p></div>",
        unsafe_allow_html=True,
    )


def render_workspace_header(st, course_id: str, course_name: str, role: str = "student") -> str:
    st.markdown(f"<h1 class='lms-page-title'>{escape(course_name)}</h1><p class='course-code'>{escape(course_id)}</p>", unsafe_allow_html=True)
    tabs = ["Tổng quan", "Tài liệu", "AI Tutor", "Quiz", "Flashcard", "Tiến độ"]
    if role == "teacher":
        tabs = ["Tổng quan", "Tài liệu", "Đồng bộ DeepTutor", "Quiz & Bài tập", "Sinh viên", "Thống kê"]
    return st.radio("Course workspace", tabs, horizontal=True, label_visibility="collapsed", key="workspace_tab")


def render_document_row(st, material: dict[str, Any]) -> None:
    name = escape(str(material.get("file_name") or "Tài liệu"))
    suffix = name.rsplit(".", 1)[-1].upper() if "." in name else "FILE"
    uploaded = str(material.get("uploaded_at") or "")
    st.markdown(f"<div class='course-card'><div class='course-code'>{suffix}</div><div class='course-name'>{name}</div><div class='course-meta'>{escape(uploaded) if uploaded else 'Thông tin tài liệu'}</div></div>", unsafe_allow_html=True)


def public_citation_titles(sources: list[dict[str, Any]]) -> list[str]:
    """Return distinct public titles in their retrieval order."""
    seen: set[str] = set()
    titles: list[str] = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title and title not in seen:
            seen.add(title)
            titles.append(title)
    return titles


def render_citations(st, sources: list[dict[str, Any]]) -> None:
    safe_titles = public_citation_titles(sources)
    if not safe_titles:
        return
    st.markdown("<h3 class='lms-section-title'>Nguồn tham khảo</h3>", unsafe_allow_html=True)
    for index, title in enumerate(safe_titles, 1):
        st.markdown(f"<div class='lms-note'>{index}. {escape(title)}</div>", unsafe_allow_html=True)
