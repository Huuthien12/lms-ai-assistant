"""Authenticated Streamlit vertical flow; credentials are session-memory only."""
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4
from urllib.parse import quote
import os
import re
import streamlit as st
from deeptutor_client import RealDeepTutorClient, BackendRequestError
from demo_quick_login import DemoSecretUnavailable, configured_accounts, load_account_token
from ui.components import course_display_name, quiz_document_titles, render_citations, render_document_card, render_document_workspace_header, render_verified_dashboard, strip_system_citation_markers
from ui.theme import inject_theme


@dataclass
class VerifiedSession:
    token: str = field(repr=False)
    identity: dict


def clear_verified_session():
    for key in list(st.session_state): del st.session_state[key]


def clear_quiz_state():
    for key in ("work_quiz", "work_attempt", "work_grade", "work_review"):
        st.session_state.pop(key, None)


def select_verified_course(course_key, allowed):
    """Accept only an already-authorized key; shared by the sidebar and course cards."""
    if course_key in allowed:
        st.session_state.verified_course=course_key


def synchronize_verified_course(allowed):
    select_verified_course(st.session_state.get("verified_course"), allowed)


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
              422:"Yêu cầu không hợp lệ.",502:"Không thể hoàn tất truy xuất hoặc tạo nội dung.",503:"Dịch vụ cần thiết hiện chưa sẵn sàng.",
              504:"Quá thời gian xử lý. Vui lòng thử lại với số lượng nhỏ hơn."}
    requested=error.details.get("requested_count") if isinstance(getattr(error,"details",None),dict) else None
    validated=error.details.get("validated_count") if isinstance(getattr(error,"details",None),dict) else None
    grounded_message="Quiz không đủ căn cứ từ tài liệu đã xác minh; không có câu hỏi nào được lưu."
    if type(requested) is int and type(validated) is int and 0 <= validated < requested:
        grounded_message=f"Chỉ xác minh được {validated}/{requested} câu hỏi từ tài liệu. Hãy chọn chương khác hoặc giảm số câu. Không có Quiz nào được lưu."
    codes={"INVALID_QUIZ_SCHEMA":"Mô hình trả về Quiz không đúng cấu trúc yêu cầu.",
           "QUIZ_GROUNDING_FAILED":grounded_message,
           "QUIZ_ANSWER_SPAN_MISMATCH":grounded_message,
           "QUIZ_GENERATION_FAILED":"Không thể sinh Quiz từ tài liệu đã xác minh.",
           "INVALID_FLASHCARD_SCHEMA":"Mô hình trả về Flashcard không đúng cấu trúc yêu cầu.",
           "FLASHCARD_GENERATION_FAILED":"Không thể sinh Flashcard từ tài liệu đã xác minh.",
           "LEARNING_GENERATION_TIMEOUT":"Quá thời gian sinh nội dung. Không có kết quả chưa hoàn chỉnh được hiển thị.",
           "retrieval_timeout":"Quá thời gian truy xuất tài liệu đã xác minh.",
           "CLIENT_TIMEOUT":"Backend không hoàn tất trước giới hạn chờ của giao diện."}
    codes["LEARNING_PROVIDER_UNCONFIGURED"]="Provider sinh Quiz/Flashcard chưa được cấu hình đầy đủ."
    codes["LEARNING_PROVIDER_UNAVAILABLE"]="Dịch vụ AI đang tạm thời không khả dụng. Vui lòng thử lại sau."
    codes["LEARNING_PROVIDER_REQUEST_TOO_LARGE"]="Yêu cầu Quiz vượt giới hạn provider. Hãy chọn ít câu hơn hoặc một chương hẹp hơn."
    codes["LEARNING_RATE_LIMITED"]="Provider đang giới hạn tần suất. Vui lòng chờ rồi thử lại."
    codes["invalid_chapter"]="Chương đã chọn không còn thuộc publication ACTIVE của khóa học."
    codes["NO_NEW_FLASHCARDS"]="Không tạo được thẻ mới vì nội dung bị trùng với Flashcard đã lưu."
    st.error(codes.get(error.code,messages.get(error.status_code,"Không thể hoàn tất yêu cầu.")))


def count_control(label,key,maximum=20):
    field, _ = st.columns([1, 3])
    return int(field.number_input(label, min_value=1, max_value=maximum, value=3,
                                  step=1, key=key))


def display_quiz_text(value):
    """Render common factorial/product notation without letting Markdown consume `*`."""
    if not isinstance(value, str):
        return value
    value = re.sub(r"\bn!\s*=\s*", "n! = ", value)
    if "!" in value and "*" in value:
        value = value.replace("*", " × ")
    else:
        value = re.sub(r"(?<=\d)\*(?=\d)", " × ", value)
    return value.replace("*", r"\*")


_MASTERY_LABELS = {
    "WEAK": "Cần ôn tập", "DEVELOPING": "Đang cải thiện",
    "GOOD": "Nắm vững", "MASTERED": "Đã thành thạo",
    "INSUFFICIENT_EVIDENCE": "Chưa đủ dữ liệu",
}
_CONFIDENCE_LABELS = {"LOW": "Thấp", "MEDIUM": "Trung bình", "HIGH": "Cao"}
_ACTION_LABELS = {
    "REVIEW_TOPIC": "Ôn lại chủ đề", "GENERATE_FLASHCARDS": "Tạo Flashcard",
    "EASY_QUIZ": "Làm Quiz cơ bản", "MEDIUM_QUIZ": "Làm Quiz trung bình",
    "HARD_QUIZ": "Làm Quiz nâng cao", "CONTINUE_NEXT_TOPIC": "Học chủ đề tiếp theo",
}


def progress_percent(score):
    return None if type(score) not in (int, float) else max(0.0, min(100.0, float(score)))


def progress_label(mapping, value):
    return mapping.get(value, "Chưa có dữ liệu")


def progress_updated_at(value):
    if not isinstance(value, str) or not value.strip():
        return "Chưa có dữ liệu"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return "Chưa có dữ liệu"


def render_progress_dashboard(result):
    topics = result.get("topics", []) if isinstance(result, dict) else []
    recommendations = result.get("recommendations", []) if isinstance(result, dict) else []
    actions_by_topic = {
        item.get("topic"): item.get("recommended_actions", [])
        for item in recommendations if isinstance(item, dict) and isinstance(item.get("topic"), str)
    }
    st.subheader("Tiến độ học tập")
    st.caption("Điểm thành thạo được tính từ bài Quiz và lần ôn Flashcard đã ghi nhận.")
    if not topics:
        st.info("Chưa có dữ liệu học tập. Hãy làm Quiz hoặc ghi nhận ôn Flashcard để xem tiến độ.")
        return
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        score = progress_percent(topic.get("mastery_score"))
        with st.container(border=True):
            st.subheader(topic.get("topic") if isinstance(topic.get("topic"), str) else "Chủ đề")
            if score is None:
                st.caption("Chưa có đủ bằng chứng để chấm điểm thành thạo.")
            else:
                st.progress(score / 100, text=f"Điểm thành thạo: {score:g}%")
            mastery, confidence, evidence = st.columns(3)
            mastery.metric("Mức độ thành thạo", progress_label(_MASTERY_LABELS, topic.get("level")))
            confidence.metric("Độ tin cậy", progress_label(_CONFIDENCE_LABELS, topic.get("confidence")))
            evidence.metric("Số bằng chứng học tập", topic.get("evidence_count") if type(topic.get("evidence_count")) is int else 0)
            st.caption("Cập nhật gần nhất: " + progress_updated_at(topic.get("last_updated_at")))
            actions = actions_by_topic.get(topic.get("topic"), [])
            if actions:
                labels = [progress_label(_ACTION_LABELS, action) for action in actions if isinstance(action, str)]
                if labels:
                    st.info("Gợi ý ôn tập: " + " • ".join(labels))


def scope_control(prefix,chapters):
    options=["Theo chương","Toàn bộ khóa học"] if chapters else ["Toàn bộ khóa học"]
    choice=st.radio("Phạm vi kiến thức",options,horizontal=True,key=prefix+"_scope")
    if choice=="Theo chương":
        labels={chapter["document_id"]:chapter.get("filename") or chapter["document_id"] for chapter in chapters}
        chapter_id=st.selectbox("Chọn chương",list(labels),format_func=labels.get,key=prefix+"_chapter")
        return "chapter",chapter_id,labels[chapter_id]
    return "course",None,"Toàn bộ khóa học"


def render_verified_learning(base_url):
    inject_theme(st)
    session=st.session_state.get("verified_session")
    if session is None:
        st.markdown("<div class='login-shell'><div class='login-brand'>✦ <span>DeepTutor</span></div><p>HỌC TẬP ĐƯỢC XÁC MINH</p><h1>Đăng nhập để tiếp tục học</h1><span>Quyền truy cập học phần được Moodle xác minh cho từng phiên.</span></div>",unsafe_allow_html=True)
        accounts=configured_accounts()
        with st.expander("Đăng nhập nhanh — Tài khoản demo"):
            if not accounts:
                st.caption("Chưa cấu hình cho deployment này.")
            else:
                labels={account.key:account.label for account in accounts}
                selected=st.selectbox("Tài khoản demo",list(labels),format_func=labels.get,key="demo_account")
                def quick_login():
                    account=next((item for item in accounts if item.key==selected),None)
                    if account is None:
                        st.session_state.login_error=401; return
                    try:
                        token=load_account_token(account)
                        identity=RealDeepTutorClient(base_url,personal_token=token).identity()
                        clear_verified_session()
                        st.session_state.verified_session=VerifiedSession(token,identity)
                    except DemoSecretUnavailable:
                        st.session_state.demo_login_status="missing_secret"
                    except BackendRequestError:
                        st.session_state.login_error=401
                st.button("Đăng nhập tài khoản demo",on_click=quick_login)
                if st.session_state.get("demo_login_status")=="missing_secret":
                    st.warning("Chưa cấu hình.")
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
    st.sidebar.markdown("<div class='sidebar-brand'><span>✦</span><div><strong>DeepTutor</strong><small>Không gian học tập</small></div></div>",unsafe_allow_html=True)
    st.sidebar.button("Đăng xuất",on_click=clear_verified_session)
    client=RealDeepTutorClient(base_url,personal_token=session.token)
    try: identity=client.identity()
    except BackendRequestError as error:
        if error.status_code==401: clear_verified_session()
        show_error(error); return
    session.identity=identity
    courses=identity.get("courses",[])
    if not courses:
        st.info("Không có khóa học đang được phép truy cập."); return
    allowed=[c["course_key"] for c in courses]
    if st.session_state.get("verified_course") not in allowed: st.session_state.pop("verified_course",None)
    labels={key: course_display_name(key, next((item.get("course_name") or item.get("fullname") or item.get("name") for item in courses if item["course_key"] == key), None)) for key in allowed}
    st.sidebar.caption("Khóa học được cấp quyền")
    course=st.sidebar.selectbox("Khóa học của tôi",allowed,format_func=labels.get,key="verified_course",
                                on_change=synchronize_verified_course,args=(allowed,))
    render_verified_dashboard(st,courses,course,lambda choice: select_verified_course(choice,allowed))
    scope=(identity["owner_ref"],course)
    if st.session_state.get("work_scope")!=scope:
        for key in list(st.session_state):
            if key.startswith(("work_","quiz_answer_","card_review_")): del st.session_state[key]
        st.session_state.work_scope=scope
    prefix="/learning/courses/"+quote(course,safe="")
    generation_client_timeout=float(os.getenv("LEARNING_CLIENT_TIMEOUT_SECONDS","170"))
    documents,chat,quiz,cards,progress=st.tabs(["Tài liệu","AI Tutor","Quiz","Flashcards","Progress"])
    active_publications=[]
    with documents:
        try:
            with st.spinner("Đang tải publication ACTIVE..."):
                data=client.request("GET",prefix+"/documents")
            active_publications=list(data.get("publications",[]))
            published={d["document_id"]:d for d in data.get("publications",[])}
            can_sync=next(c.get("can_sync",False) for c in courses if c["course_key"]==course)
            render_document_workspace_header(st,course,len(published),can_sync,labels[course])
            if can_sync:
                data["resources"]=client.request("GET",prefix+"/resources")["resources"]
                if st.button("Đồng bộ toàn khóa học"):
                    client.request("POST",prefix+"/sync"); st.rerun()
            for resource in data.get("resources",[]):
                identifier=resource["document_id"]
                render_document_card(st,resource,published.get(identifier))
                if can_sync:
                    if st.button("Đồng bộ",key="sync_"+identifier):
                        client.request("POST",prefix+"/documents/"+quote(identifier,safe="")+"/sync"); st.rerun()
                    if identifier in published and st.button("Ngừng sử dụng",key="retire_"+identifier):
                        client.request("DELETE",prefix+"/documents/"+quote(identifier,safe="")); st.rerun()
            resource_ids={r["document_id"] for r in data.get("resources",[])}
            for identifier,publication in published.items():
                if identifier not in resource_ids:
                    render_document_card(st,None,publication)
                    if can_sync and st.button("Ngừng sử dụng",key="retire_"+identifier):
                        client.request("DELETE",prefix+"/documents/"+quote(identifier,safe="")); st.rerun()
            if not data.get("resources") and not published: st.info("Chưa có tài liệu hoặc publication ACTIVE được phép truy cập.")
        except BackendRequestError as error: show_error(error)
    with chat:
        if "work_messages" not in st.session_state:
            try: st.session_state.work_messages=session_messages(client.request("GET",prefix+"/history").get("history",[]))
            except BackendRequestError as error: show_error(error); st.session_state.work_messages=[]
        for message in st.session_state.work_messages:
            with st.chat_message(message["role"]):
                if message.get("error"): st.error(message["content"])
                elif message["role"] == "assistant": st.markdown(strip_system_citation_markers(message["content"],message.get("sources",[])))
                else: st.markdown(message["content"])
                render_citations(st,message.get("sources",[]))
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
        scope_mode,chapter_id,topic=scope_control("quiz",active_publications)
        count=count_control("Số câu hỏi","quiz_count")
        if st.button("Tạo Quiz",type="primary"):
            try:
                with st.spinner("Đang truy xuất tài liệu và tạo Quiz..."):
                    st.session_state.work_quiz=client.request("POST",prefix+"/quizzes",{
                        "question":topic,"topic":topic,"count":count,"difficulty":"medium",
                        "scope_mode":scope_mode,"chapter_id":chapter_id},generation_client_timeout)
                st.session_state.pop("work_attempt",None); st.session_state.pop("work_grade",None); st.session_state.pop("work_review",None)
                st.success("Đã tạo Quiz từ tài liệu ACTIVE.")
            except BackendRequestError as error:
                clear_quiz_state(); show_error(error)
        if material:=st.session_state.get("work_quiz"):
            answers=[]
            with st.form("submit_verified_quiz"):
                total_questions=len(material["questions"])
                for number,question in enumerate(material["questions"],1):
                    labels={o["id"]:display_quiz_text(o["text"]) for o in question["options"]}
                    st.caption(f"Câu {number}/{total_questions}")
                    selected=st.radio(display_quiz_text(question["question"]),list(labels),index=None,format_func=labels.get,
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
            review=st.session_state.get("work_review",{})
            unavailable=[item["question_id"] for item in review.get("results",[])
                         if item.get("explanation_status")!="available"]
            should_fetch=not review or bool(unavailable)
            if st.button("Xem giải thích" if not review else "Thử lại các giải thích chưa có",disabled=not should_fetch):
                try:
                    path="/learning/attempts/"+st.session_state.work_attempt+"/review"
                    if unavailable: path += "?" + "&".join("question_id="+quote(item,safe="") for item in unavailable)
                    fresh=client.request("GET",path)
                    old={item["question_id"]:item for item in review.get("results",[])}
                    old.update({item["question_id"]:item for item in fresh["results"]})
                    st.session_state.work_review={**fresh,"results":list(old.values())}
                except BackendRequestError as error: show_error(error)
            results={item.get("question_id"):item for item in st.session_state.get("work_review",{}).get("results",[])}
            if results: st.markdown("### Kết quả bài kiểm tra")
            for number,question in enumerate(material["questions"],1):
                result=results.get(question["question_id"])
                if result is None: continue
                state="Chưa trả lời" if result.get("selected_option_id") is None else ("Chính xác" if result.get("correct") else "Chưa chính xác")
                with st.expander(f"Câu {number} — {state}",expanded=True):
                    st.write("**Câu hỏi:** " + display_quiz_text(question["question"]))
                    options={option["id"]:display_quiz_text(option["text"]) for option in question["options"]}
                    selected=options.get(result.get("selected_option_id"))
                    st.write("**Đáp án của bạn:** " + (selected or "Chưa trả lời"))
                    if result.get("correct_answer"):
                        st.write("**Đáp án đúng:** " + display_quiz_text(result["correct_answer"]))
                    if result.get("explanation"):
                        st.write("**Giải thích:** " + result["explanation"])
                    elif result.get("explanation_status")=="publication_unavailable":
                        st.caption("Không thể tạo giải thích vì tài liệu tham chiếu không còn ACTIVE hoặc quyền truy cập đã thay đổi.")
                    elif result.get("explanation_status")=="provider_rate_limited":
                        st.caption("Provider đang giới hạn tần suất; bạn có thể thử lại sau.")
                    elif result.get("explanation_status")=="provider_timeout":
                        st.caption("Provider quá thời gian xử lý; bạn có thể thử lại sau.")
                    else:
                        st.caption("Provider chưa thể tạo giải thích cho câu này. Điểm và đáp án đã nộp vẫn được giữ nguyên.")
                    if material.get("scope_mode") != "chapter":
                        titles=quiz_document_titles(result.get("sources",[]))
                        if titles:
                            st.caption("Tài liệu: " + "; ".join(titles))
    with cards:
        scope_mode,chapter_id,topic=scope_control("cards",active_publications)
        count=count_control("Số thẻ cần tạo","card_count")
        if st.button("Tạo Flashcards",type="primary"):
            try:
                with st.spinner("Đang truy xuất tài liệu và tạo Flashcard..."):
                    created=client.request("POST",prefix+"/flashcards",{
                        "question":topic,"topic":topic,"count":count,"difficulty":"medium",
                        "scope_mode":scope_mode,"chapter_id":chapter_id},generation_client_timeout)
                st.success(f"Đã tạo {created.get('created_count',len(created.get('flashcards',[])))} Flashcard mới.")
                if created.get("skipped_duplicate_count"):
                    st.warning(f"Đã bỏ qua {created['skipped_duplicate_count']} thẻ trùng với dữ liệu đã lưu.")
            except BackendRequestError as error: show_error(error)
        try:
            card_filter=st.radio("Hiển thị",["Cần ôn tập","Tất cả","Đã ôn"],horizontal=True,key="card_filter")
            if card_filter=="Cần ôn tập":
                st.caption("Hiện gồm các thẻ chưa ôn. Hệ thống chưa lưu thời điểm ôn tiếp theo nên không suy đoán thẻ đến hạn.")
            all_cards=client.request("GET",prefix+"/flashcards").get("flashcards",[])
            visible=[card for card in all_cards if card_filter=="Tất cả" or
                     (card_filter=="Đã ôn" and card.get("reviewed")) or
                     (card_filter=="Cần ôn tập" and card.get("needs_review"))]
            if not visible: st.info("Không có Flashcard phù hợp với bộ lọc.")
            labels={"AGAIN":"Chưa nhớ","HARD":"Khó nhớ","GOOD":"Nhớ tốt","EASY":"Rất dễ nhớ"}
            for card in visible:
                with st.expander(card["front_text"]):
                    st.write(card["back_text"])
                    render_citations(st,card.get("sources",[]))
                    st.caption("Đã ôn" if card.get("reviewed") else "Chưa ôn")
                    rating=st.selectbox("Mức độ nhớ",list(labels),format_func=labels.get,
                                        key="card_review_"+card["flashcard_id"])
                    if st.button("Ghi nhận ôn tập",key="record_"+card["flashcard_id"]):
                        pending=st.session_state.setdefault("work_review_ids",{})
                        key=(card["flashcard_id"],rating); identifier=pending.setdefault(key,uuid4().hex)
                        client.request("POST","/learning/flashcards/"+card["flashcard_id"]+"/reviews",{"rating":rating,"review_id":identifier})
                        pending.pop(key,None); st.success("Đã ghi nhận ôn tập và cập nhật Progress.")
        except BackendRequestError as error: show_error(error)
    with progress:
        try:
            result=client.request("GET",prefix+"/progress")
            render_progress_dashboard(result)
        except BackendRequestError as error: show_error(error)
