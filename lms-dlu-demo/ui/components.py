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
