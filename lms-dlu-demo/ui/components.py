"""Reusable Streamlit presentation components for the LMS shell."""

from __future__ import annotations

from html import escape
from typing import Any


def role_label(role: str) -> str:
    return "Giảng viên" if role == "teacher" else "Sinh viên"


def render_topbar(st, *, title: str, user_name: str, role: str) -> None:
    st.markdown(
        f"""
        <div class="lms-topbar">
          <div><p class="lms-brand">LMS DeepTutor · Đại học Đà Lạt</p>
          <p class="lms-subtitle">{title}</p></div>
          <div><strong>{escape(user_name)}</strong> <span class="lms-role">{role_label(role)}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
    st.markdown(f"<div class='lms-empty'>{message}</div>", unsafe_allow_html=True)


def render_workspace_header(st, course_id: str, course_name: str) -> str:
    st.markdown(f"<h1 class='lms-page-title'>{escape(course_name)}</h1><p class='course-code'>{escape(course_id)}</p>", unsafe_allow_html=True)
    return st.radio("Course workspace", ["Tổng quan", "Tài liệu", "AI Tutor"], horizontal=True, label_visibility="collapsed", key="workspace_tab")


def render_document_row(st, material: dict[str, Any]) -> None:
    name = escape(str(material.get("file_name") or "Tài liệu"))
    suffix = name.rsplit(".", 1)[-1].upper() if "." in name else "FILE"
    uploaded = str(material.get("uploaded_at") or "")
    st.markdown(f"<div class='course-card'><div class='course-code'>{suffix}</div><div class='course-name'>{name}</div><div class='course-meta'>{escape(uploaded) if uploaded else 'Thông tin tài liệu'}</div></div>", unsafe_allow_html=True)


def render_citations(st, sources: list[dict[str, Any]]) -> None:
    safe_titles = [str(item.get("title") or "").strip() for item in sources if isinstance(item, dict)]
    safe_titles = [title for title in safe_titles if title]
    if not safe_titles:
        return
    st.markdown("<h3 class='lms-section-title'>Nguồn tham khảo</h3>", unsafe_allow_html=True)
    for index, title in enumerate(safe_titles, 1):
        st.markdown(f"<div class='lms-note'>{index}. {escape(title)}</div>", unsafe_allow_html=True)
