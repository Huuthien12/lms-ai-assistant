# ==============================================================================
# main.py
# FASTAPI BACKEND - LMS DLU + SQL SERVER + DEEPTUTOR
# ==============================================================================

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel

import pyodbc
import os
import shutil
import subprocess
import json
import sys

from pathlib import Path

from typing import Optional


# ==============================================================================
# 1. FASTAPI APP
# ==============================================================================

app = FastAPI(
    title="LMS DeepTutor API",
    description="Backend LMS Đại học Đà Lạt tích hợp DeepTutor",
    version="2.0.0"
)


# ==============================================================================
# 2. CORS
# ==============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# 3. PROJECT DIRECTORIES
# ==============================================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PROJECT_ROOT = os.path.dirname(BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from deeptutor_integration import DeepTutorConfig, DeepTutorService
from deeptutor_integration.api import create_router as create_deeptutor_router
from deeptutor_integration.contracts import DocumentInput, QueryInput
from backend.services.ai.deepseek_provider import DeepSeekProvider
from backend.services.ai.fallback_provider import FallbackAIProvider
from backend.services.ai.grounded_chat import GroundedChatService
from backend.services.ai.ollama_provider import OllamaProvider
from backend.services.ai.orchestrator import AIOrchestrator
from grounded_chat_router import create_grounded_chat_router
from moodle_adapter import MoodleAdapter
from moodle_ingestion_router import create_moodle_ingestion_router
from readiness_router import create_readiness_router

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

UPLOAD_DIR = os.path.abspath(
    os.getenv("LMS_UPLOAD_DIR")
    or os.path.join(BASE_DIR, "uploads")
)

os.makedirs(
    UPLOAD_DIR,
    exist_ok=True
)


# ==============================================================================
# 4. SQL SERVER CONFIG
# ==============================================================================

SERVER = os.getenv("LMS_DB_SERVER", "localhost")

DATABASE = os.getenv("LMS_DB_NAME", "LMS_DeepTutor")

ODBC_DRIVER = os.getenv(
    "LMS_DB_DRIVER",
    "ODBC Driver 17 for SQL Server"
)


# ==============================================================================
# 5. DEEPTUTOR CONFIG
# ==============================================================================

DEEPTUTOR_CONFIG = DeepTutorConfig.from_env(Path(PROJECT_ROOT))
DEEPTUTOR_SERVICE = DeepTutorService(DEEPTUTOR_CONFIG)
DEEPTUTOR_DIR = str(DEEPTUTOR_CONFIG.deeptutor_dir)
DEEPTUTOR_EXE = str(DEEPTUTOR_CONFIG.executable)

app.include_router(create_deeptutor_router(DEEPTUTOR_SERVICE))

try:
    MOODLE_ADAPTER = MoodleAdapter()
except ValueError:
    MOODLE_ADAPTER = None
app.include_router(create_moodle_ingestion_router(MOODLE_ADAPTER, DEEPTUTOR_SERVICE))

_deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
_ollama_provider = OllamaProvider(
    model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
)
GROUNDED_CHAT_SERVICE = (
    GroundedChatService(AIOrchestrator(FallbackAIProvider(
        DeepSeekProvider(_deepseek_api_key), _ollama_provider
    )))
    if _deepseek_api_key
    else GroundedChatService(AIOrchestrator(_ollama_provider))
)
app.include_router(create_grounded_chat_router(DEEPTUTOR_SERVICE, GROUNDED_CHAT_SERVICE))
app.include_router(create_readiness_router(DEEPTUTOR_SERVICE, _ollama_provider, MOODLE_ADAPTER))


# ==============================================================================
# 6. DATABASE CONNECTION
# ==============================================================================

def get_connection():

    try:

        connection_string = (
            f"DRIVER={{{ODBC_DRIVER}}};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=5;"
        )

        connection = pyodbc.connect(
            connection_string
        )

        return connection

    except Exception as e:

        raise Exception(
            f"Không thể kết nối SQL Server: {e}"
        )


# ==============================================================================
# 7. GENERAL HELPERS
# ==============================================================================

def row_to_dict(cursor, row):

    columns = [
        column[0]
        for column in cursor.description
    ]

    return dict(
        zip(
            columns,
            row
        )
    )


def safe_filename(filename: str):

    filename = os.path.basename(
        filename
    )

    filename = filename.replace(
        "..",
        ""
    )

    return filename


def get_kb_name(course_id: str) -> str:
    """
    Mỗi môn học sử dụng một Knowledge Base riêng.

    INT1339 -> lms-int1339
    INT1401 -> lms-int1401
    """

    return (
        f"lms-{course_id.strip().lower()}"
    )


# ==============================================================================
# 8. DEEPTUTOR HELPERS
# ==============================================================================

def check_deeptutor_executable():

    if not os.path.exists(
        DEEPTUTOR_EXE
    ):

        raise RuntimeError(
            "Không tìm thấy DeepTutor executable tại: "
            f"{DEEPTUTOR_EXE}"
        )

def run_deeptutor_command(
    args: list[str],
    timeout: int = 300
):
    """
    Chạy DeepTutor CLI từ FastAPI.

    Quan trọng trên Windows:
    - ép Python subprocess dùng UTF-8
    - ép stdout/stderr UTF-8
    - tắt Rich color/terminal detection
    """

    check_deeptutor_executable()

    command = [
        DEEPTUTOR_EXE,
        *args
    ]

    # Lấy environment hiện tại để DeepTutor vẫn đọc được
    # các API key/config đang có.
    env = os.environ.copy()

    # Bắt buộc Python của DeepTutor dùng UTF-8
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    # Giúp Rich không xử lý subprocess như Windows terminal cũ.
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"

    try:

        result = subprocess.run(
            command,
            cwd=DEEPTUTOR_DIR,

            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,

            text=True,
            encoding="utf-8",
            errors="replace",

            env=env,

            timeout=timeout,

            shell=False,

            # Quan trọng trên Windows:
            # không mở cửa sổ console mới.
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt"
                else 0
            )
        )

        return result

    except subprocess.TimeoutExpired:

        raise RuntimeError(
            "DeepTutor xử lý quá thời gian cho phép."
        )

    except Exception as e:

        raise RuntimeError(
            f"Không thể chạy DeepTutor: {e}"
        )


def get_deeptutor_kb_info(
    kb_name: str
):
    """
    Lấy trạng thái thật của Knowledge Base.

    Return:
        None -> KB chưa tồn tại

        dict -> KB tồn tại, chứa:
            status
            rag_initialized
            raw_documents
            ...
    """

    result = run_deeptutor_command(
        [
            "kb",
            "info",
            kb_name
        ],
        timeout=60
    )

    # Command lỗi -> coi như KB chưa tồn tại
    if result.returncode != 0:
        return None

    output = result.stdout.strip()

    if not output:
        return None

    try:
        return json.loads(output)

    except json.JSONDecodeError:
        return None


def deeptutor_kb_exists(
    kb_name: str
) -> bool:
    """
    Chỉ kiểm tra KB có tồn tại hay không.
    """

    info = get_deeptutor_kb_info(
        kb_name
    )

    return info is not None


def deeptutor_kb_is_ready(
    kb_name: str
) -> bool:
    """
    KB chỉ được xem là sử dụng được khi:
    - status = ready
    - rag_initialized = true
    """

    info = get_deeptutor_kb_info(
        kb_name
    )

    if not info:
        return False

    status = str(
        info.get("status", "")
    ).lower()

    statistics = info.get(
        "statistics",
        {}
    )

    rag_initialized = statistics.get(
        "rag_initialized",
        False
    )

    return (
        status == "ready"
        and rag_initialized is True
    )


def index_document_to_deeptutor(
    course_id: str,
    document_path: str
):
    """
    Đồng bộ tài liệu LMS vào DeepTutor.

    Quy tắc:
    - KB chưa có -> CREATE
    - Ghost KB (unknown, 0 docs, RAG false, không index) -> CREATE
    - KB ready -> ADD
    - KB processing -> báo đang xử lý
    - KB lỗi -> không tự động ghi đè
    """

    kb_name = get_kb_name(course_id)

    document_path = os.path.abspath(
        document_path
    )

    if not os.path.exists(document_path):
        raise RuntimeError(
            f"Không tìm thấy file để index: {document_path}"
        )

    # ==========================================================
    # 1. KIỂM TRA KB
    # ==========================================================

    kb_info = get_deeptutor_kb_info(
        kb_name
    )

    kb_should_create = False

    # ==========================================================
    # 2. KB KHÔNG TỒN TẠI
    # ==========================================================

    if kb_info is None:

        kb_should_create = True

    else:

        status = str(
            kb_info.get(
                "status",
                ""
            )
        ).lower()

        statistics = kb_info.get(
            "statistics",
            {}
        )

        raw_documents = int(
            statistics.get(
                "raw_documents",
                0
            ) or 0
        )

        rag_initialized = statistics.get(
            "rag_initialized",
            False
        )

        index_versions = (
            statistics.get(
                "index_versions",
                []
            )
            or []
        )

        # ======================================================
        # GHOST KB
        #
        # DeepTutor có thể trả về:
        #
        # status = unknown
        # raw_documents = 0
        # rag_initialized = false
        # index_versions = []
        #
        # dù KB chưa thực sự được khởi tạo.
        #
        # Trường hợp này coi như KB chưa tồn tại.
        # ======================================================

        if (
            status in ("unknown", "")
            and raw_documents == 0
            and rag_initialized is False
            and len(index_versions) == 0
        ):

            kb_should_create = True

    # ==========================================================
    # 3. CREATE KB
    # ==========================================================

    if kb_should_create:

        action = "create"

        result = run_deeptutor_command(
            [
                "kb",
                "create",
                kb_name,
                "--doc",
                document_path
            ],
            timeout=300
        )

    # ==========================================================
    # 4. KB ĐÃ TỒN TẠI
    # ==========================================================

    else:

        status = str(
            kb_info.get(
                "status",
                ""
            )
        ).lower()

        statistics = kb_info.get(
            "statistics",
            {}
        )

        rag_initialized = statistics.get(
            "rag_initialized",
            False
        )

        # ------------------------------------------------------
        # READY -> ADD DOCUMENT
        # ------------------------------------------------------

        if (
            status == "ready"
            and rag_initialized is True
        ):

            action = "add"

            result = run_deeptutor_command(
                [
                    "kb",
                    "add",
                    kb_name,
                    "--doc",
                    document_path
                ],
                timeout=300
            )

        # ------------------------------------------------------
        # PROCESSING
        # ------------------------------------------------------

        elif status == "processing":

            raise RuntimeError(
                f"Knowledge Base {kb_name} "
                "đang xử lý tài liệu. "
                "Vui lòng chờ quá trình index hoàn tất."
            )

        # ------------------------------------------------------
        # BROKEN KB
        # ------------------------------------------------------

        else:

            raise RuntimeError(
                f"Knowledge Base {kb_name} tồn tại "
                f"nhưng chưa sẵn sàng "
                f"(status={status}, "
                f"rag_initialized={rag_initialized})."
            )

    # ==========================================================
    # 5. KIỂM TRA LỆNH CREATE / ADD
    # ==========================================================

    if result.returncode != 0:

        error_message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "DeepTutor không trả về thông báo lỗi."
        )

        raise RuntimeError(
            f"DeepTutor {action} tài liệu thất bại "
            f"trong {kb_name}: "
            f"{error_message}"
        )

    # ==========================================================
    # 6. KIỂM TRA KB SAU KHI INDEX
    # ==========================================================

    final_info = get_deeptutor_kb_info(
        kb_name
    )

    if not final_info:

        raise RuntimeError(
            f"DeepTutor đã chạy {action} nhưng "
            f"không đọc được trạng thái của {kb_name}."
        )

    final_status = str(
        final_info.get(
            "status",
            ""
        )
    ).lower()

    final_statistics = final_info.get(
        "statistics",
        {}
    )

    final_rag_initialized = (
        final_statistics.get(
            "rag_initialized",
            False
        )
    )

    raw_documents = (
        final_statistics.get(
            "raw_documents",
            0
        )
    )

    # ==========================================================
    # 7. CHỈ THÀNH CÔNG KHI KB READY
    # ==========================================================

    if (
        final_status != "ready"
        or final_rag_initialized is not True
    ):

        raise RuntimeError(
            f"Tài liệu đã được gửi vào DeepTutor "
            f"nhưng Knowledge Base {kb_name} "
            f"chưa sẵn sàng "
            f"(status={final_status}, "
            f"rag_initialized={final_rag_initialized})."
        )

    # ==========================================================
    # 8. SUCCESS
    # ==========================================================

    return {
        "success": True,
        "action": action,
        "kb_name": kb_name,
        "document_path": document_path,
        "status": final_status,
        "rag_initialized": final_rag_initialized,
        "raw_documents": raw_documents,
        "message": (
            f"Đã tạo Knowledge Base và index "
            f"{kb_name} thành công."
            if action == "create"
            else
            f"Đã thêm tài liệu vào Knowledge Base "
            f"{kb_name} thành công."
        )
    }


def ask_deeptutor(
    course_id: str,
    message: str
):

    kb_name = get_kb_name(
        course_id
    )

    # --------------------------------------------------------------------------
    # Kiểm tra KB
    # --------------------------------------------------------------------------

    if not deeptutor_kb_exists(
        kb_name
    ):

        raise RuntimeError(
            f"Môn {course_id} chưa có Knowledge Base "
            f"({kb_name}). "
            "Giảng viên cần upload tài liệu trước."
        )

    # --------------------------------------------------------------------------
    # DeepTutor Chat + RAG
    # --------------------------------------------------------------------------

    rag_question = f"""
    Bạn là trợ lý học tập AI dành cho sinh viên.

    Hãy trả lời câu hỏi của sinh viên hoàn toàn bằng tiếng Việt.

    Yêu cầu bắt buộc:
    - Chỉ sử dụng thông tin từ tài liệu được truy xuất trong Knowledge Base.
    - Trả lời hoàn toàn bằng tiếng Việt.
    - Tiêu đề, phần giải thích và kết luận đều phải bằng tiếng Việt.
    - Không mở đầu câu trả lời bằng tiếng Anh.
    - Các thuật ngữ chuyên ngành bằng tiếng Anh có thể giữ nguyên,
    nhưng phải giải thích bằng tiếng Việt khi cần thiết.
    - Trình bày rõ ràng, dễ hiểu và phù hợp với sinh viên.
    - Ưu tiên trả lời trực tiếp vào câu hỏi, không viết dài dòng không cần thiết.
    - Có thể sử dụng Markdown để trình bày danh sách, tiêu đề hoặc nhấn mạnh.
    - Nếu thông tin có trong tài liệu, hãy trả lời dựa trên nội dung đó.
    - Nếu tài liệu không chứa đủ thông tin để trả lời, hãy nói rõ:
    "Không tìm thấy đủ thông tin này trong tài liệu môn học."
    - Không tự bịa thêm thông tin không có trong tài liệu.

    Câu hỏi của sinh viên:
    {message}
    """

    result = run_deeptutor_command(
        [
            "run",
            "chat",
            rag_question,
            "--tool",
            "rag",
            "--kb",
            kb_name,
            "--language",
            "vi",
            "--format",
            "json"
        ],
        timeout=300
    )
    if result.returncode != 0:

        error_message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "DeepTutor không trả về thông báo lỗi."
        )

        raise RuntimeError(
            f"DeepTutor chat thất bại: "
            f"{error_message}"
        )

    # --------------------------------------------------------------------------
    # Parse JSON Lines
    # --------------------------------------------------------------------------

    bot_response = None

    session_id = None

    sources = []

    for line in result.stdout.splitlines():

        line = line.strip()

        if not line:

            continue

        try:

            event = json.loads(
                line
            )

        except json.JSONDecodeError:

            # DeepTutor đôi khi có log không phải JSON.
            # Ta bỏ qua log đó.
            continue

        event_type = event.get(
            "type"
        )

        # ----------------------------------------------------------------------
        # SESSION
        # ----------------------------------------------------------------------

        if event_type == "session":

            session_id = (
                event
                .get("metadata", {})
                .get("session_id")
            )

            if not session_id:

                session_id = event.get(
                    "session_id"
                )

        # ----------------------------------------------------------------------
        # SOURCES
        # ----------------------------------------------------------------------

        elif event_type == "sources":

            sources = (
                event
                .get("metadata", {})
                .get("sources", [])
            )

        # ----------------------------------------------------------------------
        # FINAL RESULT
        # ----------------------------------------------------------------------

        elif event_type == "result":

            bot_response = (
                event
                .get("metadata", {})
                .get("response")
            )

            if not session_id:

                session_id = event.get(
                    "session_id"
                )

    # --------------------------------------------------------------------------
    # Không tìm được result
    # --------------------------------------------------------------------------

    if not bot_response:

        raise RuntimeError(
            "DeepTutor đã chạy nhưng backend "
            "không tìm thấy response trong JSON output."
        )

    # --------------------------------------------------------------------------
    # Làm sạch sources trước khi trả về frontend
    # --------------------------------------------------------------------------

    clean_sources = []

    for source in sources:

        clean_sources.append(
            {
                "title": source.get(
                    "title"
                ),

                "page": source.get(
                    "page"
                ),

                "score": source.get(
                    "score"
                ),

                "kb_name": source.get(
                    "kb_name",
                    kb_name
                )
            }
        )

    return {
        "response": bot_response,
        "session_id": session_id,
        "kb_name": kb_name,
        "sources": clean_sources
    }


# Compatibility boundary for the existing LMS callers. DeepTutor process and
# knowledge-base behavior is owned by the isolated integration package above.
def get_kb_name(course_id: str) -> str:
    return DEEPTUTOR_SERVICE.kb_name(course_id)


def index_document_to_deeptutor(course_id: str, document_path: str):
    path = Path(document_path)
    return DEEPTUTOR_SERVICE.ingest_document(
        DocumentInput(
            document_id=path.stem,
            course_id=course_id,
            filename=path.name,
            path=str(path),
            source="lms-demo",
        )
    )


def ask_deeptutor(course_id: str, message: str):
    query_result = DEEPTUTOR_SERVICE.query(
        QueryInput(course_id=course_id, question=message)
    )
    result = query_result["result"]
    response = (
        result.get("response")
        or result.get("answer")
        or result.get("content")
        or result.get("text")
    )
    if not isinstance(response, str) or not response.strip():
        raise RuntimeError("DeepTutor returned no textual response.")
    sources = result.get("sources") or result.get("documents") or []
    return {
        "response": response,
        "session_id": result.get("session_id"),
        "kb_name": query_result["kb_id"],
        "sources": sources if isinstance(sources, list) else [],
    }


# ==============================================================================
# 9. REQUEST MODELS
# ==============================================================================

class ChatRequest(BaseModel):

    student_id: str

    course_id: str

    message: str


class SaveChatRequest(BaseModel):

    student_id: str

    course_id: str

    user_message: str

    bot_response: str


# ==============================================================================
# 10. ROOT
# ==============================================================================

@app.get("/")
def root():

    deeptutor_available = os.path.exists(
        DEEPTUTOR_EXE
    )

    return {
        "status": "ok",
        "message": "LMS DeepTutor Backend đang hoạt động",
        "database": DATABASE,
        "deeptutor_connected": deeptutor_available,
        "deeptutor_exe": DEEPTUTOR_EXE
    }


# ==============================================================================
# 11. DATABASE TEST
# ==============================================================================

@app.get("/db-test")
def database_test():

    connection = None

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            "SELECT DB_NAME()"
        )

        database_name = (
            cursor.fetchone()[0]
        )

        return {
            "status": "success",
            "message": "Kết nối SQL Server thành công",
            "database": database_name,
            "server": SERVER
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if connection:

            connection.close()


# ==============================================================================
# 12. USERS
# ==============================================================================

@app.get("/users")
def get_users():

    connection = None

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                user_id,
                full_name,
                email,
                role
            FROM Users
            ORDER BY user_id
            """
        )

        rows = cursor.fetchall()

        users = [
            row_to_dict(
                cursor,
                row
            )
            for row in rows
        ]

        return {
            "users": users
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if connection:

            connection.close()


# ==============================================================================
# 13. COURSES
# ==============================================================================

@app.get("/courses")
def get_courses():

    connection = None

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                course_id,
                course_name,
                description
            FROM Courses
            ORDER BY course_id
            """
        )

        rows = cursor.fetchall()

        courses = [
            row_to_dict(
                cursor,
                row
            )
            for row in rows
        ]

        return {
            "courses": courses
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if connection:

            connection.close()


# ==============================================================================
# 14. COURSE DETAIL
# ==============================================================================

@app.get(
    "/courses/{course_id}"
)
def get_course(
    course_id: str
):

    connection = None

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                course_id,
                course_name,
                description
            FROM Courses
            WHERE course_id = ?
            """,
            course_id
        )

        row = cursor.fetchone()

        if not row:

            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy môn học."
            )

        course = row_to_dict(
            cursor,
            row
        )

        return {
            "course": course
        }

    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if connection:

            connection.close()


# ==============================================================================
# 15. ASSIGNMENTS
# ==============================================================================

@app.get(
    "/courses/{course_id}/assignments"
)
def get_assignments(
    course_id: str
):

    connection = None

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                assignment_id,
                course_id,
                title,
                due_date
            FROM Assignments
            WHERE course_id = ?
            ORDER BY due_date
            """,
            course_id
        )

        rows = cursor.fetchall()

        assignments = []

        for row in rows:

            assignment = row_to_dict(
                cursor,
                row
            )

            if assignment.get(
                "due_date"
            ):

                assignment[
                    "due_date"
                ] = assignment[
                    "due_date"
                ].isoformat()

            assignments.append(
                assignment
            )

        return {
            "assignments": assignments
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if connection:

            connection.close()


# ==============================================================================
# 16. MATERIALS
# ==============================================================================

@app.get(
    "/courses/{course_id}/materials"
)
def get_materials(
    course_id: str
):

    connection = None

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                material_id,
                course_id,
                file_name,
                file_path,
                uploaded_at
            FROM Materials
            WHERE course_id = ?
            ORDER BY uploaded_at DESC
            """,
            course_id
        )

        rows = cursor.fetchall()

        materials = []

        for row in rows:

            material = row_to_dict(
                cursor,
                row
            )

            if material.get(
                "uploaded_at"
            ):

                material[
                    "uploaded_at"
                ] = material[
                    "uploaded_at"
                ].isoformat()

            materials.append(
                material
            )

        return {
            "materials": materials
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if connection:

            connection.close()


# ==============================================================================
# 17. CHECK MATERIAL
# ==============================================================================

@app.get(
    "/materials/{material_id}/check"
)
def check_material(
    material_id: int
):

    connection = None

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                material_id,
                course_id,
                file_name,
                file_path,
                uploaded_at
            FROM Materials
            WHERE material_id = ?
            """,
            material_id
        )

        row = cursor.fetchone()

        if not row:

            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy tài liệu."
            )

        material = row_to_dict(
            cursor,
            row
        )

        file_name = material[
            "file_name"
        ]

        physical_path = os.path.join(
            UPLOAD_DIR,
            file_name
        )

        return {
            "material_id": material_id,
            "course_id": material[
                "course_id"
            ],
            "file_name": file_name,
            "database_path": material[
                "file_path"
            ],
            "physical_path": physical_path,
            "exists": os.path.exists(
                physical_path
            )
        }

    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if connection:

            connection.close()


# ==============================================================================
# 18. UPLOAD MATERIAL + DEEPTUTOR INDEX
# ==============================================================================

@app.post(
    "/upload-material/"
)
async def upload_material(
    course_id: str = Form(...),
    file: UploadFile = File(...)
):

    connection = None

    physical_path = None

    try:

        # ----------------------------------------------------------------------
        # CHECK COURSE
        # ----------------------------------------------------------------------

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                course_id
            FROM Courses
            WHERE course_id = ?
            """,
            course_id
        )

        course = cursor.fetchone()

        if not course:

            raise HTTPException(
                status_code=404,
                detail=(
                    f"Không tìm thấy môn học "
                    f"{course_id}."
                )
            )

        # ----------------------------------------------------------------------
        # CHECK FILE
        # ----------------------------------------------------------------------

        if not file.filename:

            raise HTTPException(
                status_code=400,
                detail="File không hợp lệ."
            )

        filename = safe_filename(
            file.filename
        )

        extension = os.path.splitext(
            filename
        )[1].lower()

        allowed_extensions = {
            ".pdf",
            ".docx",
            ".txt"
        }

        if extension not in allowed_extensions:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Chỉ hỗ trợ PDF, DOCX và TXT."
                )
            )

        # ----------------------------------------------------------------------
        # PREVENT DUPLICATE FILE NAME
        # ----------------------------------------------------------------------

        original_name = filename

        name_without_extension = (
            os.path.splitext(
                original_name
            )[0]
        )

        counter = 1

        physical_path = os.path.join(
            UPLOAD_DIR,
            filename
        )

        while os.path.exists(
            physical_path
        ):

            filename = (
                f"{name_without_extension}"
                f"_{counter}"
                f"{extension}"
            )

            physical_path = os.path.join(
                UPLOAD_DIR,
                filename
            )

            counter += 1

        # ----------------------------------------------------------------------
        # SAVE PHYSICAL FILE
        # ----------------------------------------------------------------------

        with open(
            physical_path,
            "wb"
        ) as buffer:

            shutil.copyfileobj(
                file.file,
                buffer
            )

        # ----------------------------------------------------------------------
        # DATABASE PATH
        # ----------------------------------------------------------------------

        database_path = os.path.join(
            "uploads",
            filename
        )

        # ----------------------------------------------------------------------
        # INSERT MATERIAL
        # ----------------------------------------------------------------------

        cursor.execute(
            """
            INSERT INTO Materials
            (
                course_id,
                file_name,
                file_path,
                uploaded_at
            )
            OUTPUT INSERTED.material_id
            VALUES
            (
                ?,
                ?,
                ?,
                GETDATE()
            )
            """,
            course_id,
            filename,
            database_path
        )

        material_id = (
            cursor.fetchone()[0]
        )

        connection.commit()

        # ----------------------------------------------------------------------
        # INDEX INTO DEEPTUTOR
        #
        # SQL/file đã lưu thành công trước.
        # Nếu DeepTutor lỗi, tài liệu LMS vẫn được giữ.
        # ----------------------------------------------------------------------

        deeptutor_indexed = False

        deeptutor_error = None

        deeptutor_action = None

        kb_name = get_kb_name(
            course_id
        )

        try:

            deeptutor_result = (
                index_document_to_deeptutor(
                    course_id=course_id,
                    document_path=physical_path
                )
            )

            deeptutor_indexed = True

            deeptutor_action = (
                deeptutor_result[
                    "action"
                ]
            )

        except Exception as e:

            deeptutor_error = str(e)

        # ----------------------------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------------------------

        return {
            "status": "success",

            "message": (
                "Upload tài liệu thành công"
            ),

            "material_id": material_id,

            "course_id": course_id,

            "file_name": filename,

            "file_path": database_path,

            "deeptutor": {
                "kb_name": kb_name,
                "indexed": deeptutor_indexed,
                "action": deeptutor_action,
                "error": deeptutor_error
            }
        }

    except HTTPException:

        if connection:

            try:

                connection.rollback()

            except Exception:

                pass

        raise

    except Exception as e:

        if connection:

            try:

                connection.rollback()

            except Exception:

                pass

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        try:

            await file.close()

        except Exception:

            pass

        if connection:

            connection.close()


# ==============================================================================
# 19. SAVE CHAT
# ==============================================================================

@app.post(
    "/chat/save"
)
def save_chat(
    request: SaveChatRequest
):

    connection = None

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO ChatHistory
            (
                student_id,
                course_id,
                user_message,
                bot_response,
                created_at
            )
            OUTPUT INSERTED.chat_id
            VALUES
            (
                ?,
                ?,
                ?,
                ?,
                GETDATE()
            )
            """,
            request.student_id,
            request.course_id,
            request.user_message,
            request.bot_response
        )

        chat_id = (
            cursor.fetchone()[0]
        )

        connection.commit()

        return {
            "status": "success",
            "chat_id": chat_id
        }

    except Exception as e:

        if connection:

            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if connection:

            connection.close()


# ==============================================================================
# 20. CHAT HISTORY
# ==============================================================================

@app.get(
    "/chat/history/{student_id}/{course_id}"
)
def get_chat_history(
    student_id: str,
    course_id: str
):

    connection = None

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                chat_id,
                student_id,
                course_id,
                user_message,
                bot_response,
                created_at
            FROM ChatHistory
            WHERE student_id = ?
              AND course_id = ?
            ORDER BY created_at ASC
            """,
            student_id,
            course_id
        )

        rows = cursor.fetchall()

        history = []

        for row in rows:

            item = row_to_dict(
                cursor,
                row
            )

            if item.get(
                "created_at"
            ):

                item[
                    "created_at"
                ] = item[
                    "created_at"
                ].isoformat()

            history.append(
                item
            )

        return {
            "student_id": student_id,
            "course_id": course_id,
            "history": history
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if connection:

            connection.close()


# ==============================================================================
# 21. DEEPTUTOR STATUS
# ==============================================================================

@app.get(
    "/deeptutor/legacy-status",
    deprecated=True
)
def deeptutor_status():

    available = os.path.exists(
        DEEPTUTOR_EXE
    )

    result = {
        "available": available,
        "executable": DEEPTUTOR_EXE,
        "directory": DEEPTUTOR_DIR
    }

    if not available:

        result[
            "message"
        ] = "Không tìm thấy DeepTutor."

        return result

    try:

        command_result = (
            run_deeptutor_command(
                [
                    "kb",
                    "list"
                ],
                timeout=60
            )
        )

        result[
            "command_success"
        ] = (
            command_result.returncode == 0
        )

        result[
            "knowledge_bases"
        ] = command_result.stdout.strip()

        if command_result.stderr.strip():

            result[
                "stderr"
            ] = command_result.stderr.strip()

    except Exception as e:

        result[
            "command_success"
        ] = False

        result[
            "error"
        ] = str(e)

    return result


# ==============================================================================
# 22. DEEPTUTOR KB STATUS FOR COURSE
# ==============================================================================

@app.get(
    "/deeptutor/kb/{course_id}"
)
def get_course_kb_status(
    course_id: str
):

    kb_name = get_kb_name(
        course_id
    )

    try:

        exists = deeptutor_kb_exists(
            kb_name
        )

        if not exists:

            return {
                "course_id": course_id,
                "kb_name": kb_name,
                "exists": False
            }

        result = run_deeptutor_command(
            [
                "kb",
                "info",
                kb_name
            ],
            timeout=60
        )

        return {
            "course_id": course_id,
            "kb_name": kb_name,
            "exists": True,
            "info": result.stdout.strip()
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ==============================================================================
# 23. CHAT WITH REAL DEEPTUTOR
# ==============================================================================

@app.post(
    "/chat"
)
def chat_with_deeptutor(
    request: ChatRequest
):

    connection = None

    try:

        # ----------------------------------------------------------------------
        # MESSAGE
        # ----------------------------------------------------------------------

        message = (
            request.message.strip()
        )

        if not message:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Câu hỏi không được để trống."
                )
            )

        # ----------------------------------------------------------------------
        # DATABASE
        # ----------------------------------------------------------------------

        connection = get_connection()

        cursor = connection.cursor()

        # ----------------------------------------------------------------------
        # CHECK STUDENT
        # ----------------------------------------------------------------------

        cursor.execute(
            """
            SELECT
                user_id,
                full_name,
                role
            FROM Users
            WHERE user_id = ?
            """,
            request.student_id
        )

        student = cursor.fetchone()

        if not student:

            raise HTTPException(
                status_code=404,
                detail=(
                    f"Không tìm thấy sinh viên "
                    f"{request.student_id}."
                )
            )

        if str(
            student[2]
        ).lower() != "student":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Tài khoản "
                    f"{request.student_id} "
                    f"không phải sinh viên."
                )
            )

        # ----------------------------------------------------------------------
        # CHECK COURSE
        # ----------------------------------------------------------------------

        cursor.execute(
            """
            SELECT
                course_id,
                course_name
            FROM Courses
            WHERE course_id = ?
            """,
            request.course_id
        )

        course = cursor.fetchone()

        if not course:

            raise HTTPException(
                status_code=404,
                detail=(
                    f"Không tìm thấy môn học "
                    f"{request.course_id}."
                )
            )

        course_name = course[1]

        # ----------------------------------------------------------------------
        # GET MATERIALS
        # ----------------------------------------------------------------------

        cursor.execute(
            """
            SELECT
                material_id,
                file_name,
                file_path
            FROM Materials
            WHERE course_id = ?
            ORDER BY uploaded_at DESC
            """,
            request.course_id
        )

        material_rows = (
            cursor.fetchall()
        )

        material_names = [
            material[1]
            for material in material_rows
        ]

        # ----------------------------------------------------------------------
        # Kiểm tra ít nhất LMS có tài liệu
        # ----------------------------------------------------------------------

        if not material_names:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Môn học này chưa có tài liệu. "
                    "Giảng viên cần upload tài liệu "
                    "trước khi sử dụng DeepTutor."
                )
            )

        # ----------------------------------------------------------------------
        # CALL DEEPTUTOR
        # ----------------------------------------------------------------------

        try:

            deeptutor_result = (
                ask_deeptutor(
                    course_id=request.course_id,
                    message=message
                )
            )

        except Exception as e:

            raise HTTPException(
                status_code=503,
                detail=(
                    "DeepTutor hiện không thể "
                    f"xử lý câu hỏi: {e}"
                )
            )

        bot_response = (
            deeptutor_result[
                "response"
            ]
        )

        # ----------------------------------------------------------------------
        # SAVE CHAT HISTORY
        # ----------------------------------------------------------------------

        cursor.execute(
            """
            INSERT INTO ChatHistory
            (
                student_id,
                course_id,
                user_message,
                bot_response,
                created_at
            )
            OUTPUT INSERTED.chat_id
            VALUES
            (
                ?,
                ?,
                ?,
                ?,
                GETDATE()
            )
            """,
            request.student_id,
            request.course_id,
            message,
            bot_response
        )

        chat_id = (
            cursor.fetchone()[0]
        )

        connection.commit()

        # ----------------------------------------------------------------------
        # FINAL RESPONSE
        # ----------------------------------------------------------------------

        return {
            "status": "success",

            "chat_id": chat_id,

            "student_id": (
                request.student_id
            ),

            "course_id": (
                request.course_id
            ),

            "course_name": (
                course_name
            ),

            "question": message,

            "response": bot_response,

            "materials": (
                material_names
            ),

            "deeptutor_connected": True,

            "deeptutor": {

                "kb_name": (
                    deeptutor_result[
                        "kb_name"
                    ]
                ),

                "session_id": (
                    deeptutor_result[
                        "session_id"
                    ]
                ),

                "sources": (
                    deeptutor_result[
                        "sources"
                    ]
                )
            }
        }

    except HTTPException:

        if connection:

            try:

                connection.rollback()

            except Exception:

                pass

        raise

    except Exception as e:

        if connection:

            try:

                connection.rollback()

            except Exception:

                pass

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if connection:

            connection.close()

# ==============================================================================
# DELETE CHAT HISTORY
# ==============================================================================

@app.delete(
    "/chat/history/{student_id}/{course_id}"
)
def delete_chat_history(
    student_id: str,
    course_id: str
):
    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        # Kiểm tra có lịch sử chat không
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM ChatHistory
            WHERE student_id = ?
              AND course_id = ?
            """,
            student_id,
            course_id
        )

        count = cursor.fetchone()[0]

        if count == 0:
            return {
                "status": "success",
                "message": "Không có lịch sử chat để xóa.",
                "deleted": 0
            }

        # Xóa toàn bộ lịch sử của sinh viên trong môn này
        cursor.execute(
            """
            DELETE FROM ChatHistory
            WHERE student_id = ?
              AND course_id = ?
            """,
            student_id,
            course_id
        )

        connection.commit()

        return {
            "status": "success",
            "message": "Đã xóa lịch sử chat.",
            "student_id": student_id,
            "course_id": course_id,
            "deleted": count
        }

    except Exception as e:
        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        if connection:
            connection.close()

# ==============================================================================
# 24. RUN
# ==============================================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
