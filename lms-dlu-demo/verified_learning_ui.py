"""Authenticated Streamlit vertical flow; credentials are session-memory only."""
from dataclasses import dataclass, field
from uuid import uuid4
from urllib.parse import quote
import streamlit as st
from deeptutor_client import RealDeepTutorClient, BackendRequestError
from ui.components import render_citations, render_student_courses_hero
from ui.theme import inject_theme


@dataclass
class VerifiedSession:
    token: str = field(repr=False)
    identity: dict


def clear_verified_session():
    for key in list(st.session_state): del st.session_state[key]


def session_messages(history):
    messages=[]
    for item in history:
        response=item.get("response",{})
        messages.append({"role":"user","content":item.get("question","")})
        messages.append({"role":"assistant","content":response.get("answer","") if response.get("status")=="success" else "Không thể tạo câu trả lời.",
                         "sources":response.get("sources",[]) if response.get("status")=="success" else [],
                         "context_id":response.get("context_id"),"error":response.get("status")!="success"})
    return messages


def show_error(error):
    messages={401:"Thông tin đăng nhập Moodle không hợp lệ hoặc đã hết hạn.",403:"Bạn không có quyền truy cập tài nguyên này.",
              404:"Không tìm thấy tài nguyên.",409:"Chưa có ngữ cảnh ACTIVE đã xác minh hoặc trạng thái đã thay đổi.",
              422:"Yêu cầu không hợp lệ.",502:"Không thể hoàn tất truy xuất hoặc tạo nội dung.",503:"Dịch vụ cần thiết hiện chưa sẵn sàng."}
    st.error(messages.get(error.status_code,"Không thể hoàn tất yêu cầu."))


def render_verified_learning(base_url):
    inject_theme(st)
    st.title("LMS DeepTutor")
    session=st.session_state.get("verified_session")
    if session is None:
        st.subheader("Đăng nhập Moodle")
        st.caption("Sử dụng token Moodle cá nhân. Khóa học và quyền truy cập được backend xác minh.")
        def login():
            token=st.session_state.get("moodle_login_token","").strip()
            try:
                identity=RealDeepTutorClient(base_url,personal_token=token).identity()
                st.session_state.verified_session=VerifiedSession(token,identity)
                st.session_state.pop("moodle_login_token",None)
                st.session_state.pop("login_error",None)
            except BackendRequestError as error:
                st.session_state.login_error=error.status_code
        with st.form("verified_login"):
            st.text_input("Token Moodle cá nhân",type="password",key="moodle_login_token")
            st.form_submit_button("Đăng nhập",on_click=login)
        if st.session_state.get("login_error"): show_error(BackendRequestError(st.session_state.login_error))
        return
    st.sidebar.button("Đăng xuất",on_click=clear_verified_session)
    client=RealDeepTutorClient(base_url,personal_token=session.token)
    try: identity=client.identity()
    except BackendRequestError as error:
        if error.status_code==401: clear_verified_session()
        show_error(error); return
    session.identity=identity
    courses=identity.get("courses",[])
    st.sidebar.caption(f"Moodle user #{identity['moodle_user_id']}")
    render_student_courses_hero(st,len(courses))
    if not courses:
        st.info("Không có khóa học đang được phép truy cập."); return
    allowed=[c["course_key"] for c in courses]
    if st.session_state.get("verified_course") not in allowed: st.session_state.pop("verified_course",None)
    course=st.sidebar.selectbox("Khóa học của tôi",allowed,key="verified_course")
    scope=(identity["owner_ref"],course)
    if st.session_state.get("work_scope")!=scope:
        for key in list(st.session_state):
            if key.startswith(("work_","quiz_answer_","card_review_")): del st.session_state[key]
        st.session_state.work_scope=scope
    prefix="/learning/courses/"+quote(course,safe="")
    documents,chat,quiz,cards,progress=st.tabs(["Tài liệu","AI Tutor","Quiz","Flashcards","Progress"])
    with documents:
        st.subheader("Tài liệu khóa học")
        try:
            data=client.request("GET",prefix+"/documents")
            published={d["document_id"]:d for d in data.get("publications",[])}
            can_sync=next(c.get("can_sync",False) for c in courses if c["course_key"]==course)
            if can_sync:
                data["resources"]=client.request("GET",prefix+"/resources")["resources"]
                if st.button("Đồng bộ toàn khóa học"):
                    client.request("POST",prefix+"/sync"); st.rerun()
            for resource in data.get("resources",[]):
                identifier=resource["document_id"]
                st.write(resource["filename"])
                st.caption("ACTIVE" if identifier in published else "Chưa publish ACTIVE")
                if can_sync:
                    if st.button("Đồng bộ",key="sync_"+identifier):
                        client.request("POST",prefix+"/documents/"+quote(identifier,safe="")+"/sync"); st.rerun()
                    if identifier in published and st.button("Ngừng sử dụng",key="retire_"+identifier):
                        client.request("DELETE",prefix+"/documents/"+quote(identifier,safe="")); st.rerun()
            resource_ids={r["document_id"] for r in data.get("resources",[])}
            for identifier,publication in published.items():
                if identifier not in resource_ids:
                    st.write(publication.get("filename") or identifier)
                    st.caption("ACTIVE; tài liệu không còn được Moodle liệt kê.")
                    if can_sync and st.button("Ngừng sử dụng",key="retire_"+identifier):
                        client.request("DELETE",prefix+"/documents/"+quote(identifier,safe="")); st.rerun()
            if not data.get("resources") and not published: st.info("Chưa có tài liệu được phép truy cập.")
        except BackendRequestError as error: show_error(error)
    with chat:
        if "work_messages" not in st.session_state:
            try: st.session_state.work_messages=session_messages(client.request("GET",prefix+"/history").get("history",[]))
            except BackendRequestError as error: show_error(error); st.session_state.work_messages=[]
        for message in st.session_state.work_messages:
            with st.chat_message(message["role"]):
                if message.get("error"): st.error(message["content"])
                else: st.markdown(message["content"])
                render_citations(st,message.get("sources",[]))
                if message.get("sources"): st.caption("Nguồn được xác minh tại thời điểm tạo câu trả lời.")
                for source in message.get("sources",[]):
                    with st.expander(source.get("title") or "Nguồn"):
                        st.write(source.get("preview", ""))
                        st.caption(f"Document {source.get('document_id')} · Version {source.get('document_version_id')} · Chunk {source.get('chunk_id')}")
        if question:=st.chat_input("Hỏi AI Tutor về khóa học"):
            try:
                response=client.request("POST",prefix+"/chat",{"question":question})
                st.session_state.work_messages.extend(session_messages([{"question":question,"response":response}]))
                st.rerun()
            except BackendRequestError as error: show_error(error)
        if st.button("Xóa lịch sử trò chuyện"):
            try: client.request("DELETE",prefix+"/history"); st.session_state.work_messages=[]; st.rerun()
            except BackendRequestError as error: show_error(error)
    with quiz:
        with st.form("generate_verified_quiz"):
            topic=st.text_input("Chủ đề Quiz",value="Ôn tập khóa học")
            count=st.number_input("Số câu hỏi",min_value=1,max_value=20,value=3,step=1)
            if st.form_submit_button("Tạo Quiz"):
                try:
                    st.session_state.work_quiz=client.request("POST",prefix+"/quizzes",{"question":topic,"topic":topic,"count":count,"difficulty":"medium"})
                    st.session_state.pop("work_attempt",None); st.session_state.pop("work_grade",None); st.session_state.pop("work_review",None)
                except BackendRequestError as error: show_error(error)
        if material:=st.session_state.get("work_quiz"):
            answers=[]
            with st.form("submit_verified_quiz"):
                for question in material["questions"]:
                    labels={o["id"]:o["text"] for o in question["options"]}
                    selected=st.radio(question["question"],[None,*labels],format_func=lambda value,labels=labels:labels.get(value,"Chưa trả lời"),
                                      key="quiz_answer_"+material["quiz_id"]+question["question_id"])
                    answers.append({"question_id":question["question_id"],"selected_option_id":selected})
                if st.form_submit_button("Nộp bài"):
                    try:
                        if "work_attempt" not in st.session_state:
                            st.session_state.work_attempt=client.request("POST","/learning/quizzes/"+material["quiz_id"]+"/attempts")["attempt_id"]
                        st.session_state.work_grade=client.request("POST","/learning/attempts/"+st.session_state.work_attempt+"/submit",{"answers":answers})
                    except BackendRequestError as error: show_error(error)
            render_citations(st,material.get("sources",[]))
        if grade:=st.session_state.get("work_grade"):
            st.metric("Điểm từ server",grade["score_percent"])
            st.write(f"Đúng {grade['correct_count']}/{grade['total_questions']}")
            if st.button("Xem giải thích"):
                try: st.session_state.work_review=client.request("GET","/learning/attempts/"+st.session_state.work_attempt+"/review")
                except BackendRequestError as error: show_error(error)
            for result in st.session_state.get("work_review",{}).get("results",[]):
                st.write(result.get("explanation") or "Ngữ cảnh đã thay đổi hoặc chưa có giải thích.")
                render_citations(st,result.get("sources",[]))
    with cards:
        with st.form("generate_verified_cards"):
            topic=st.text_input("Chủ đề Flashcards",value="Ôn tập khóa học")
            count=st.number_input("Số Flashcards",min_value=1,max_value=20,value=3,step=1)
            if st.form_submit_button("Tạo Flashcards"):
                try: client.request("POST",prefix+"/flashcards",{"question":topic,"topic":topic,"count":count,"difficulty":"medium"})
                except BackendRequestError as error: show_error(error)
        try:
            for card in client.request("GET",prefix+"/flashcards").get("flashcards",[]):
                with st.expander(card["front_text"]):
                    st.write(card["back_text"])
                    render_citations(st,card.get("sources",[]))
                    rating=st.selectbox("Mức độ nhớ",["AGAIN","HARD","GOOD","EASY"],key="card_review_"+card["flashcard_id"])
                    if st.button("Ghi nhận ôn tập",key="record_"+card["flashcard_id"]):
                        pending=st.session_state.setdefault("work_review_ids",{})
                        key=(card["flashcard_id"],rating); identifier=pending.setdefault(key,uuid4().hex)
                        client.request("POST","/learning/flashcards/"+card["flashcard_id"]+"/reviews",{"rating":rating,"review_id":identifier})
                        pending.pop(key,None); st.success("Đã ghi nhận evidence trên server.")
        except BackendRequestError as error: show_error(error)
    with progress:
        try:
            result=client.request("GET",prefix+"/progress")
            st.caption("Mastery / recommendation dùng heuristic và luật, dựa trên evidence từ server.")
            if not result.get("topics"): st.info("Chưa có evidence được chấm hoặc ôn tập.")
            for topic in result.get("topics",[]): st.write(topic)
            for recommendation in result.get("recommendations",[]):
                st.write(recommendation["topic"],recommendation["recommended_actions"])
        except BackendRequestError as error: show_error(error)
