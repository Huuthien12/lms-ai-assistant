"""Authenticated Streamlit vertical flow; credentials are session-memory only."""
from dataclasses import dataclass, field
from datetime import datetime
from random import Random
from uuid import uuid4
from urllib.parse import quote
from html import escape
import os
import re
import streamlit as st
from deeptutor_client import RealDeepTutorClient, BackendRequestError
from demo_quick_login import DemoSecretUnavailable, configured_accounts, load_account_token
from ui.components import course_display_name, quiz_document_titles, render_citations, render_document_card, render_document_workspace_header, render_learning_tab_header, render_verified_dashboard, render_verified_empty_state, render_verified_topbar, strip_system_citation_markers
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


def clear_scoped_work_state(state):
    """Clear stale widget/work state even when Streamlit already removed a widget key."""
    for key in list(state):
        if key.startswith(("work_", "quiz_answer_", "card_review_", "card_reveal_")):
            state.pop(key, None)


def normalize_verified_tab(state):
    """Redirect a persisted legacy Profile selection to the first remaining tab."""
    if state.get("verified_learning_tab")=="Hồ sơ": state["verified_learning_tab"]="Tổng quan"


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
    codes["trusted_topic_mapping_unavailable"]=(
        "Tài liệu nguồn của Quiz không còn khớp với publication ACTIVE. "
        "Hãy làm Quiz mới sau khi giảng viên làm mới tài liệu.")
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
    summary=result.get("summary",{}) if isinstance(result,dict) else {}
    documents=result.get("documents",[]) if isinstance(result,dict) else []
    st.subheader("Tổng quan học tập")
    st.caption("Điểm thành thạo được tính từ bài Quiz và lần ôn Flashcard đã ghi nhận.")
    columns=st.columns(3)
    columns[0].metric("Tài liệu được phép học",summary.get("accessible_document_count") if type(summary.get("accessible_document_count")) is int else 0)
    columns[1].metric("Quiz đã hoàn thành",summary.get("completed_quiz_attempts") if type(summary.get("completed_quiz_attempts")) is int else 0)
    columns[2].metric("Flashcard đã ôn",summary.get("reviewed_flashcards") if type(summary.get("reviewed_flashcards")) is int else 0)
    overall=progress_percent(summary.get("overall_mastery"))
    if overall is not None: st.progress(overall/100,text=f"Mức độ thành thạo tổng thể: {overall:g}%")
    needing=summary.get("documents_needing_review",[])
    if needing: st.info("Cần ôn lại: "+" • ".join(item for item in needing if isinstance(item,str)))
    st.subheader("Tiến độ theo tài liệu")
    if not documents:
        render_verified_empty_state(st, "Chưa có tài liệu được phép", "Chưa có publication ACTIVE được phép truy cập.")
        return
    for document in documents:
        if not isinstance(document, dict):
            continue
        score = progress_percent(document.get("mastery_score"))
        with st.container(border=True):
            st.subheader(document.get("title") if isinstance(document.get("title"), str) else "Tài liệu đã xác minh")
            if score is None:
                st.caption("Chưa có hoạt động học tập")
            else:
                st.progress(score / 100, text=f"Điểm thành thạo: {score:g}%")
            mastery, confidence, evidence = st.columns(3)
            mastery.metric("Mức độ thành thạo", progress_label(_MASTERY_LABELS, document.get("level")))
            confidence.metric("Độ tin cậy", progress_label(_CONFIDENCE_LABELS, document.get("confidence")))
            evidence.metric("Hoạt động học tập", document.get("activity_count") if type(document.get("activity_count")) is int else 0)
            recommendation=document.get("recommendation")
            actions=recommendation.get("recommended_actions",[]) if isinstance(recommendation,dict) else []
            if actions:
                labels = [progress_label(_ACTION_LABELS, action) for action in actions if isinstance(action, str)]
                if labels:
                    st.info("Gợi ý ôn tập: " + " • ".join(labels))
            if isinstance(recommendation,dict) and isinstance(recommendation.get("reason"),str):
                st.caption(recommendation["reason"] + " Dùng các tab Quiz hoặc Flashcards để thực hiện gợi ý.")


def scope_control(prefix,chapters):
    options=["Theo chương","Toàn bộ khóa học"] if chapters else ["Toàn bộ khóa học"]
    choice=st.radio("Phạm vi kiến thức",options,horizontal=True,key=prefix+"_scope")
    if choice=="Theo chương":
        labels={chapter["document_id"]:chapter.get("filename") or chapter["document_id"] for chapter in chapters}
        chapter_id=st.selectbox("Chọn chương",list(labels),format_func=labels.get,key=prefix+"_chapter")
        return "chapter",chapter_id,labels[chapter_id]
    return "course",None,"Toàn bộ khóa học"


def flashcard_decks(cards):
    """Only current, server-mapped chapters form learner study decks."""
    decks={}
    for card in cards:
        if not isinstance(card,dict) or not card.get("needs_review"):
            continue
        chapter=card.get("chapter_label")
        if isinstance(chapter,str) and chapter.strip(): decks.setdefault(chapter,[]).append(card)
    return dict(sorted(decks.items(),key=lambda item:int(re.search(r"\d+$",item[0]).group()) if re.search(r"\d+$",item[0]) else item[0]))


def flashcard_saved_decks(cards):
    decks={}
    for card in cards:
        chapter=card.get("chapter_label") if isinstance(card,dict) else None
        if isinstance(chapter,str) and chapter.strip(): decks.setdefault(chapter,[]).append(card)
    return dict(sorted(decks.items(),key=lambda item:int(re.search(r"\d+$",item[0]).group()) if re.search(r"\d+$",item[0]) else item[0]))


def flashcard_study_cards(cards, deck, mode, review_filter="ACTIVE"):
    decks=flashcard_saved_decks(cards)
    selected=[card for topic,items in decks.items()
              if deck=="Tất cả" or topic==deck for card in items]
    rating={"UNRATED":None,"AGAIN":"AGAIN","HARD":"HARD","GOOD":"GOOD","EASY":"EASY"}.get(review_filter,review_filter)
    if review_filter=="ACTIVE": selected=[card for card in selected if card.get("needs_review")]
    elif review_filter!="ALL": selected=[card for card in selected if card.get("latest_rating")==rating]
    if mode=="Chỉ thẻ chưa nhớ": selected=[card for card in selected if card.get("needs_review")]
    if mode=="Học ngẫu nhiên":
        Random("|".join(str(card.get("flashcard_id","")) for card in selected)).shuffle(selected)
    return selected


def render_flashcard_workspace(client, all_cards):
    """Study authorized persisted Flashcards in a responsive three-panel layout."""
    decks=flashcard_saved_decks(all_cards)
    if not decks:
        render_verified_empty_state(st,"Chưa có Flashcard","Tạo Flashcard từ tài liệu ACTIVE để bắt đầu ôn tập.")
        return
    deck_names=["Tất cả",*decks]
    left,center,right=st.columns([1.05,1.7,1.05],gap="large")
    with left:
        st.subheader("Bộ flashcard")
        deck=st.radio("Chọn bộ thẻ",deck_names,key="flashcard_deck",label_visibility="collapsed",
                      format_func=lambda value: f"{value} · {sum(len(items) for items in decks.values()) if value=='Tất cả' else len(decks[value])} thẻ")
        st.caption("Bộ thẻ chỉ hiển thị các chương ACTIVE đã có Flashcard lưu.")
    with right:
        st.subheader("Chế độ học")
        mode=st.radio("Chế độ học",["Học lần lượt","Học ngẫu nhiên","Chỉ thẻ chưa nhớ"],key="flashcard_mode")
        review_filter=st.selectbox("Xem thẻ đã lưu",["Hàng đợi hiện tại","Tất cả thẻ đã lưu","Chưa đánh giá","Chưa nhớ","Khó nhớ","Nhớ tốt","Rất dễ nhớ"],key="flashcard_saved_filter")
        filter_codes={"Hàng đợi hiện tại":"ACTIVE","Tất cả thẻ đã lưu":"ALL","Chưa đánh giá":"UNRATED","Chưa nhớ":"AGAIN","Khó nhớ":"HARD","Nhớ tốt":"GOOD","Rất dễ nhớ":"EASY"}
        scoped=flashcard_study_cards(all_cards,deck,"Học lần lượt","ACTIVE")
        st.metric("Đã ôn",f"{sum(bool(card.get('reviewed')) for card in scoped)}/{len(scoped)}")
        st.metric("Cần ôn",sum(bool(card.get("needs_review")) for card in scoped))
        if review_filter!="Hàng đợi hiện tại": st.caption("Bộ lọc này chỉ thay đổi danh sách xem, không thay đổi trạng thái ôn tập.")
    study_cards=flashcard_study_cards(all_cards,deck,mode,filter_codes[review_filter])
    with center:
        if not study_cards:
            render_verified_empty_state(st,"Không có thẻ phù hợp","Thử chọn bộ khác hoặc chuyển sang học lần lượt.")
            return
        signature="|".join(str(card.get("flashcard_id","")) for card in study_cards)
        if st.session_state.get("flashcard_study_signature")!=signature:
            st.session_state.flashcard_study_signature=signature
            st.session_state.flashcard_study_index=0
        index=min(max(int(st.session_state.get("flashcard_study_index",0)),0),len(study_cards)-1)
        card=study_cards[index]; identifier=card["flashcard_id"]
        st.caption(f"Thẻ {index+1}/{len(study_cards)}")
        st.progress((index+1)/len(study_cards))
        reveal_key="card_reveal_"+identifier
        with st.container(border=True):
            st.markdown("<div class='flashcard-study'><span>CÂU HỎI</span><h3>"+escape(card["front_text"])+"</h3></div>",unsafe_allow_html=True)
            navigation=st.columns(3)
            if navigation[0].button("← Thẻ trước",key="previous_"+identifier,disabled=index==0,use_container_width=True):
                st.session_state.flashcard_study_index=index-1; st.rerun()
            if navigation[1].button("Hiển thị đáp án" if not st.session_state.get(reveal_key) else "Ẩn đáp án",key="reveal_"+identifier,use_container_width=True):
                st.session_state[reveal_key]=not st.session_state.get(reveal_key); st.rerun()
            if navigation[2].button("Thẻ tiếp →",key="next_"+identifier,disabled=index>=len(study_cards)-1,use_container_width=True):
                st.session_state.flashcard_study_index=index+1; st.rerun()
            if st.session_state.get(reveal_key):
                st.markdown("<div class='flashcard-study answer'><span>ĐÁP ÁN</span><p>"+escape(card["back_text"])+"</p></div>",unsafe_allow_html=True)
                render_citations(st,card.get("sources",[]))
                labels={"AGAIN":"Chưa nhớ","HARD":"Khó nhớ","GOOD":"Nhớ tốt","EASY":"Rất dễ nhớ"}
                rating=st.radio("Mức độ nhớ",list(labels),format_func=labels.get,horizontal=True,key="card_review_"+identifier)
                if st.button("Ghi nhận ôn tập",key="record_"+identifier,type="primary",use_container_width=True):
                    pending=st.session_state.setdefault("work_review_ids",{})
                    review_key=(identifier,rating); review_id=pending.setdefault(review_key,uuid4().hex)
                    client.request("POST","/learning/flashcards/"+identifier+"/reviews",{"rating":rating,"review_id":review_id})
                    pending.pop(review_key,None)
                    st.success("Đã ghi nhận ôn tập. Progress sẽ dùng lượt ôn này khi tải lại.")
                    st.rerun()


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
            st.form_submit_button("Đăng nhập",on_click=login,type="primary",use_container_width=True)
        if st.session_state.get("login_error"): show_error(BackendRequestError(st.session_state.login_error))
        return
    st.sidebar.markdown("<div class='sidebar-brand'><span>✦</span><div><strong>DeepTutor</strong><small>Không gian học tập</small></div></div>",unsafe_allow_html=True)
    st.sidebar.caption("Phiên Moodle đã xác minh")
    st.sidebar.button("Đăng xuất",key="sidebar_logout",on_click=clear_verified_session)
    normalize_verified_tab(st.session_state)
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
    render_verified_topbar(st, labels[course])
    render_verified_dashboard(st,courses,course,lambda choice: select_verified_course(choice,allowed))
    scope=(identity["owner_ref"],course)
    if st.session_state.get("work_scope")!=scope:
        clear_scoped_work_state(st.session_state)
        st.session_state.work_scope=scope
    prefix="/learning/courses/"+quote(course,safe="")
    generation_client_timeout=float(os.getenv("LEARNING_CLIENT_TIMEOUT_SECONDS","170"))
    overview,documents,chat,quiz,cards,progress=st.tabs(["Tổng quan","Tài liệu","AI Tutor","Quiz","Flashcards","Progress"])
    active_publications=[]
    with overview:
        render_learning_tab_header(st, "Tổng quan", "Chỉ hiển thị dữ liệu khóa học đã được Moodle xác minh.", "Đọc dữ liệu")
        try:
            course_overview=client.request("GET",prefix+"/overview")
            st.metric("Tài liệu ACTIVE", course_overview["active_publication_count"])
            if course_overview.get("can_manage_documents"):
                st.info("Bạn có quyền quản lý publication của học phần này. Các thao tác đồng bộ nằm trong tab Tài liệu.")
            else:
                st.caption("Tiến độ cá nhân và gợi ý học tập được hiển thị trong tab Progress.")
        except BackendRequestError as error: show_error(error)
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
                if st.button("Đồng bộ toàn khóa học", type="primary"):
                    client.request("POST",prefix+"/sync"); st.rerun()
            for resource in data.get("resources",[]):
                identifier=resource["document_id"]
                render_document_card(st,resource,published.get(identifier))
                if can_sync:
                    sync_action, retire_action, _ = st.columns([1, 1, 4])
                    with sync_action:
                        if st.button("Đồng bộ",key="sync_"+identifier):
                            client.request("POST",prefix+"/documents/"+quote(identifier,safe="")+"/sync"); st.rerun()
                    if identifier in published:
                        with retire_action:
                            if st.button("Ngừng sử dụng",key="retire_"+identifier):
                                client.request("DELETE",prefix+"/documents/"+quote(identifier,safe="")); st.rerun()
            resource_ids={r["document_id"] for r in data.get("resources",[])}
            for identifier,publication in published.items():
                if identifier not in resource_ids:
                    render_document_card(st,None,publication)
                    if can_sync:
                        retire_action, _ = st.columns([1, 5])
                        with retire_action:
                            if st.button("Ngừng sử dụng",key="retire_"+identifier):
                                client.request("DELETE",prefix+"/documents/"+quote(identifier,safe="")); st.rerun()
            if not data.get("resources") and not published:
                render_verified_empty_state(st, "Chưa có tài liệu", "Chưa có publication ACTIVE được phép truy cập.")
        except BackendRequestError as error: show_error(error)
    with chat:
        render_learning_tab_header(st, "AI Tutor", "Hỏi về tài liệu ACTIVE và nhận câu trả lời có nguồn.", "Có trích dẫn")
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
        render_learning_tab_header(st, "Quiz", "Tạo câu hỏi từ tài liệu ACTIVE, nộp bài và xem phản hồi sau chấm điểm.", "Từ tài liệu ACTIVE")
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
            if grade.get("correct_count",0) < grade.get("total_questions",0):
                if st.button("Ôn tập câu sai bằng Flashcard",key="review_wrong_answers"):
                    try:
                        with st.spinner("Đang tạo Flashcard ôn tập từ tài liệu ACTIVE..."):
                            batch=client.request("POST","/learning/attempts/"+grade["attempt_id"]+"/review-flashcards",timeout_seconds=generation_client_timeout)
                        st.session_state.work_review_batch=batch
                        if batch.get("status")=="READY":
                            st.success("Đã chuẩn bị Flashcard ôn tập. Mở tab Flashcards để ghi nhận mức độ nhớ.")
                        elif batch.get("status")=="PENDING":
                            st.info("Bộ Flashcard đang được chuẩn bị. Hãy thử lại sau ít phút.")
                        else:
                            st.info("Không có câu sai cần tạo Flashcard ôn tập.")
                    except BackendRequestError as error: show_error(error)
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
        render_learning_tab_header(st, "Flashcards", "Tạo và ôn thẻ có căn cứ từ tài liệu được cấp quyền.", "Ôn tập có ghi nhận")
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
            all_cards=client.request("GET",prefix+"/flashcards").get("flashcards",[])
            render_flashcard_workspace(client,all_cards)
        except BackendRequestError as error: show_error(error)
    with progress:
        try:
            result=client.request("GET",prefix+"/progress")
            render_learning_tab_header(st, "Tiến độ", "Thành thạo và gợi ý được tính từ Quiz và lượt ôn đã ghi nhận.")
            render_progress_dashboard(result)
        except BackendRequestError as error: show_error(error)
