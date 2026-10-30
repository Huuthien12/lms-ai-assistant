"""Reusable Streamlit presentation components for the LMS shell."""

from __future__ import annotations

import calendar
from datetime import date
from html import escape
from typing import Any


COURSE_DISPLAY_NAMES = {
    "INT1339": "Lập trình Python",
    "INT2001": "Lập trình Web nâng cao",
}


def course_display_name(course_key: object, verified_name: object = None) -> str:
    """Return a learner-facing course name while keeping the course key internal."""
    key = str(course_key or "").strip()
    if key in COURSE_DISPLAY_NAMES:
        return COURSE_DISPLAY_NAMES[key]
    name = str(verified_name or "").strip()
    return name if name and name != key else "Khóa học"


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
    course_name = escape(course_display_name(course.get("course_id"), course.get("course_name")))
    description = escape(str(course.get("description") or "Chưa có mô tả môn học."))
    st.markdown(
        f"<div class='dashboard-course {accent}'><div class='course-icon'>▣</div><div class='course-name'>{course_name}</div><div class='course-meta'>{description}</div></div>",
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


def render_verified_dashboard(st, courses: list[dict[str, Any]], selected_course: str | None = None,
                              on_select=None) -> None:
    """Render authorized courses as controls backed by the caller's selection callback."""
    st.markdown(
        "<div class='verified-dashboard-header'><div><p>KHÔNG GIAN HỌC TẬP</p>"
        "<h1>Tổng quan học tập</h1>"
        f"</div><strong>{len(courses)} khóa học</strong></div>",
        unsafe_allow_html=True,
    )
    if not courses:
        return
    columns = st.columns(min(3, len(courses)), gap="medium")
    accents = ("indigo", "sky", "violet")
    for index, course in enumerate(courses):
        course_key = str(course.get("course_key", ""))
        course_name = escape(course_display_name(course_key, course.get("course_name") or course.get("fullname") or course.get("name")))
        capability = "Có quyền đồng bộ" if course.get("can_sync") else "Truy cập học tập"
        with columns[index % len(columns)]:
            st.button(course_name, key=f"course_card_{course_key}", use_container_width=True,
                      type="primary" if course_key == selected_course else "secondary",
                      on_click=on_select, args=(course_key,) if on_select else None,
                      help=f"Chọn {course_name}")
            st.caption(capability)


def render_document_workspace_header(st, course_id: str, publication_count: int, can_sync: bool, course_name: object = None) -> None:
    capability = "Quản lý đồng bộ được cấp quyền" if can_sync else "Chỉ xem publication ACTIVE được cấp quyền"
    st.markdown(
        f"<div class='document-workspace-header'><div><p>HỌC PHẦN ĐANG CHỌN</p>"
        f"<h1>{escape(course_display_name(course_id, course_name))}</h1><span>{capability}</span></div>"
        f"<strong>{publication_count} ACTIVE</strong></div>",
        unsafe_allow_html=True,
    )


def render_document_card(st, resource: dict[str, Any] | None, publication: dict[str, Any] | None) -> None:
    item = publication or resource or {}
    filename = escape(str((resource or {}).get("filename") or item.get("filename") or item.get("document_id", "")))
    status = escape(str((publication or {}).get("status") or "Chưa có ACTIVE publication"))
    details = []
    if (resource or {}).get("mime_type"):
        details.append(escape(str(resource["mime_type"])))
    metadata = " · ".join(details)
    st.markdown(
        f"<div class='document-publication-card'><div class='document-publication-icon'>▤</div><div>"
        f"<h3>{filename}</h3>"
        f"<p>{metadata}</p></div><span class='document-publication-status'>{status}</span></div>",
        unsafe_allow_html=True,
    )


def render_course_detail_hero(st, course_id: str, course_name: str) -> None:
    display_name = escape(course_display_name(course_id, course_name))
    st.markdown(
        f"<div class='course-breadcrumb'>Khóa học của tôi　›　{display_name}</div>"
        f"<div class='course-detail-hero'><div class='course-detail-icon'>▣</div><div>"
        f"<h1>{display_name}</h1>"
        f"<p>Thông tin khóa học được hiển thị từ dữ liệu được cấp quyền.</p></div></div>",
        unsafe_allow_html=True,
    )


def render_student_course_overview(st, course_id: str, course_name: str) -> None:
    display_name = escape(course_display_name(course_id, course_name))
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
            f"<dl><dt>Tên môn học</dt><dd>{display_name}</dd>"
            f"<dt>Mô tả</dt><dd>{description}</dd></dl></div>", unsafe_allow_html=True,
        )


def render_student_course_card(st, course: dict[str, Any], accent: str) -> None:
    course_name = escape(course_display_name(course.get("course_id"), course.get("course_name")))
    description = escape(str(course.get("description") or "Chưa có mô tả môn học."))
    st.markdown(
        f"<div class='student-course {accent}'><div class='student-course-banner'><span>▣</span></div>"
        f"<div class='student-course-body'><h3>{course_name}</h3><p>{description}</p></div></div>",
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
    course_name = escape(course_display_name(course.get("course_id"), course.get("course_name")))
    description = escape(str(course.get("description") or "Chưa có mô tả môn học."))
    st.markdown(
        f"""
        <div class="course-card">
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
    st.markdown(f"<h1 class='lms-page-title'>{escape(course_display_name(course_id, course_name))}</h1>", unsafe_allow_html=True)
    tabs = ["Tổng quan", "Tài liệu", "AI Tutor", "Quiz", "Flashcard", "Tiến độ"]
    if role == "teacher":
        tabs = ["Tổng quan", "Tài liệu", "Đồng bộ DeepTutor", "Quiz & Bài tập", "Sinh viên", "Thống kê"]
    return st.radio("Course workspace", tabs, horizontal=True, label_visibility="collapsed", key="workspace_tab")


def render_document_row(st, material: dict[str, Any]) -> None:
    name = escape(str(material.get("file_name") or "Tài liệu"))
    suffix = name.rsplit(".", 1)[-1].upper() if "." in name else "FILE"
    icon = {"PDF": "▣", "DOCX": "▤", "PPTX": "▰", "MD": "▧"}.get(suffix, "▧")
    uploaded = str(material.get("uploaded_at") or "")
    try:
        uploaded = date.fromisoformat(uploaded[:10]).strftime("%d/%m/%Y")
    except ValueError:
        uploaded = ""
    metadata = " · ".join(part for part in (suffix, uploaded) if part)
    st.markdown(
        f"<div class='document-row'><span class='document-icon {suffix.lower()}'>{icon}</span>"
        f"<div><strong>{name}</strong><small>{metadata or 'Thông tin tài liệu'}</small></div></div>",
        unsafe_allow_html=True,
    )


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


def quiz_document_titles(sources: list[dict[str, Any]]) -> list[str]:
    """Return one public title per verified document, never per retrieved chunk."""
    titles: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "").strip()
        if not title:
            continue
        identity = source.get("document_id") or source.get("publication_ref")
        # Old quiz records may lack durable provenance; title is only a safe fallback.
        key = f"document:{identity}" if isinstance(identity, str) and identity else f"legacy-title:{title}"
        if key not in seen:
            seen.add(key)
            titles.append(title)
    return titles


def strip_system_citation_markers(answer: str, sources: list[dict[str, Any]]) -> str:
    """Remove only complete, source-indexed markers produced by the tutor contract."""
    if not isinstance(answer, str) or not sources:
        return answer

    def is_marker(body: str) -> bool:
        parts = [part.strip() for part in body.split(",")]
        if not parts:
            return False
        numbers=[]
        for part in parts:
            if part.startswith("Nguồn"):
                part=part[5:].lstrip(" :")
            if not part.isdigit():
                return False
            number=int(part)
            if not 1 <= number <= len(sources):
                return False
            numbers.append(number)
        return bool(numbers)

    result=[]
    index=0
    while index < len(answer):
        if answer[index] != "[":
            result.append(answer[index]); index += 1; continue
        closing=answer.find("]", index + 1)
        if closing < 0 or not is_marker(answer[index + 1:closing]):
            result.append(answer[index]); index += 1; continue
        if result and result[-1] == " " and closing + 1 < len(answer) and answer[closing + 1] in ".,;:":
            result.pop()
        index=closing + 1
        if result and result[-1] == " ":
            while index < len(answer) and answer[index] == " ":
                index += 1
    return "".join(result).strip()


def render_citations(st, sources: list[dict[str, Any]]) -> None:
    titles=public_citation_titles(sources)
    if not titles:
        return
    names="; ".join(escape(title) for title in titles)
    st.markdown(f"<div class='lms-note'>Tài liệu tham khảo: {names}</div>", unsafe_allow_html=True)
