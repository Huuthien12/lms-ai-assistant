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
    description="Backend LMS D?i h?c D? L?t t?ch h?p DeepTutor",
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
from deeptutor_integration.contracts import DocumentInput
from deeptutor_integration.errors import DeepTutorError
from backend.services.ai.deepseek_provider import DeepSeekProvider
from backend.services.ai.fallback_provider import FallbackAIProvider
from backend.services.ai.grounded_chat import GroundedChatService
from backend.services.ai.ollama_provider import OllamaProvider
from backend.services.ai.orchestrator import AIOrchestrator
from grounded_chat_router import create_grounded_chat_router
from moodle_adapter import MoodleAdapter
from moodle_ingestion_router import create_moodle_ingestion_router
from readiness_router import create_readiness_router
from quiz_lifecycle import QuizRepository, create_quiz_router
from learning_evidence import LearningEvidenceRepository, create_learning_router
from learning_workflow import LearningWorkflowRepository, create_workflow_router
from backend.services.ai.recommendation_service import RecommendationService

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

from lms_chat_router import router as chat_ui_router
app.include_router(chat_ui_router)
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
            f"Kh?ng th? k?t n?i SQL Server: {e}"
        )


# ==============================================================================
LEARNING_EVIDENCE = LearningEvidenceRepository(get_connection)
app.include_router(create_quiz_router(QuizRepository(get_connection, LEARNING_EVIDENCE)))
app.include_router(create_learning_router(LEARNING_EVIDENCE))
app.include_router(create_workflow_router(
    LearningWorkflowRepository(get_connection, LEARNING_EVIDENCE),
    RecommendationService(GROUNDED_CHAT_SERVICE.orchestrator),
))

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


# 8. DEEPTUTOR HELPERS
# ==============================================================================

def check_deeptutor_executable():

    if not os.path.exists(
        DEEPTUTOR_EXE
    ):

        raise RuntimeError(
            "Kh?ng t?m th?y DeepTutor executable t?i: "
            f"{DEEPTUTOR_EXE}"
        )

def run_deeptutor_command(
    args: list[str],
    timeout: int = 300
):
    """
    Ch?y DeepTutor CLI t? FastAPI.

    Quan tr?ng tr?n Windows:
    - ?p Python subprocess d?ng UTF-8
    - ?p stdout/stderr UTF-8
    - t?t Rich color/terminal detection
    """

    check_deeptutor_executable()

    command = [
        DEEPTUTOR_EXE,
        *args
    ]

    # L?y environment hi?n t?i d? DeepTutor v?n d?c du?c
    # c?c API key/config dang c?.
    env = os.environ.copy()

    # B?t bu?c Python c?a DeepTutor d?ng UTF-8
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    # Gi?p Rich kh?ng x? ly subprocess nhu Windows terminal cu.
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

            # Quan tr?ng tr?n Windows:
            # kh?ng m? c?a s? console m?i.
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt"
                else 0
            )
        )

        return result

    except subprocess.TimeoutExpired:

        raise RuntimeError(
            "DeepTutor x? ly qu? th?i gian cho ph?p."
        )

    except Exception as e:

        raise RuntimeError(
            f"Kh?ng th? ch?y DeepTutor: {e}"
        )


def get_deeptutor_kb_info(
    kb_name: str
):
    """
    L?y tr?ng th?i th?t c?a Knowledge Base.

    Return:
        None -> KB chua t?n t?i

        dict -> KB t?n t?i, ch?a:
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

    # Command l?i -> coi nhu KB chua t?n t?i
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
    Ch? ki?m tra KB c? t?n t?i hay kh?ng.
    """

    info = get_deeptutor_kb_info(
        kb_name
    )

    return info is not None


def deeptutor_kb_is_ready(
    kb_name: str
) -> bool:
    """
    KB ch? du?c xem l? s? d?ng du?c khi:
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
    D?ng b? t?i li?u LMS v?o DeepTutor.

    Quy t?c:
    - KB chua c? -> CREATE
    - Ghost KB (unknown, 0 docs, RAG false, kh?ng index) -> CREATE
    - KB ready -> ADD
    - KB processing -> b?o dang x? ly
    - KB l?i -> kh?ng t? d?ng ghi d?
    """

    kb_name = get_kb_name(course_id)

    document_path = os.path.abspath(
        document_path
    )

    if not os.path.exists(document_path):
        raise RuntimeError(
            f"Kh?ng t?m th?y file d? index: {document_path}"
        )

    # ==========================================================
    # 1. KI?M TRA KB
    # ==========================================================

    kb_info = get_deeptutor_kb_info(
        kb_name
    )

    kb_should_create = False

    # ==========================================================
    # 2. KB KHONG T?N T?I
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
        # DeepTutor c? th? tr? v?:
        #
        # status = unknown
        # raw_documents = 0
        # rag_initialized = false
        # index_versions = []
        #
        # d? KB chua th?c s? du?c kh?i t?o.
        #
        # Tru?ng h?p n?y coi nhu KB chua t?n t?i.
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
    # 4. KB DA T?N T?I
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
                "dang x? ly t?i li?u. "
                "Vui l?ng ch? qu? tr?nh index ho?n t?t."
            )

        # ------------------------------------------------------
        # BROKEN KB
        # ------------------------------------------------------

        else:

            raise RuntimeError(
                f"Knowledge Base {kb_name} t?n t?i "
                f"nhung chua s?n s?ng "
                f"(status={status}, "
                f"rag_initialized={rag_initialized})."
            )

    # ==========================================================
    # 5. KI?M TRA L?NH CREATE / ADD
    # ==========================================================

    if result.returncode != 0:

        error_message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "DeepTutor kh?ng tr? v? th?ng b?o l?i."
        )

        raise RuntimeError(
            f"DeepTutor {action} t?i li?u th?t b?i "
            f"trong {kb_name}: "
            f"{error_message}"
        )

    # ==========================================================
    # 6. KI?M TRA KB SAU KHI INDEX
    # ==========================================================

    final_info = get_deeptutor_kb_info(
        kb_name
    )

    if not final_info:

        raise RuntimeError(
            f"DeepTutor da ch?y {action} nhung "
            f"kh?ng d?c du?c tr?ng th?i c?a {kb_name}."
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
    # 7. CH? THANH CONG KHI KB READY
    # ==========================================================

    if (
        final_status != "ready"
        or final_rag_initialized is not True
    ):

        raise RuntimeError(
            f"T?i li?u da du?c g?i v?o DeepTutor "
            f"nhung Knowledge Base {kb_name} "
            f"chua s?n s?ng "
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
            f"Da t?o Knowledge Base v? index "
            f"{kb_name} th?nh c?ng."
            if action == "create"
            else
            f"Da th?m t?i li?u v?o Knowledge Base "
            f"{kb_name} th?nh c?ng."
        )
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
        "message": "LMS DeepTutor Backend dang ho?t d?ng",
        "database": DATABASE,
        "deeptutor_connected": deeptutor_available
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
            "message": "K?t n?i SQL Server th?nh c?ng",
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
                detail="Kh?ng t?m th?y m?n h?c."
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
                detail="Kh?ng t?m th?y t?i li?u."
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
                    f"Kh?ng t?m th?y m?n h?c "
                    f"{course_id}."
                )
            )

        # ----------------------------------------------------------------------
        # CHECK FILE
        # ----------------------------------------------------------------------

        if not file.filename:

            raise HTTPException(
                status_code=400,
                detail="File kh?ng h?p l?."
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
                    "Ch? h? tr? PDF, DOCX v? TXT."
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
        # SQL/file da luu th?nh c?ng tru?c.
        # N?u DeepTutor l?i, t?i li?u LMS v?n du?c gi?.
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

        except DeepTutorError as exc:

            deeptutor_error = exc.message

        except Exception:

            deeptutor_error = "DeepTutor document ingestion failed."

        # ----------------------------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------------------------

        return {
            "status": "success",

            "message": (
                "Upload t?i li?u th?nh c?ng"
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
    try:
        health = DEEPTUTOR_SERVICE.health()
        available = health.get("status") == "available"
    except Exception:
        available = False
    return {"available": available, "command_success": available}


# 22. DEEPTUTOR KB STATUS FOR COURSE
# ==============================================================================

@app.get(
    "/deeptutor/kb/{course_id}"
)
def get_course_kb_status(
    course_id: str
):
    try:
        kb_name = DEEPTUTOR_SERVICE.kb_name(course_id)
        status = DEEPTUTOR_SERVICE.status(kb_name)
        return {
            "course_id": course_id,
            "kb_name": kb_name,
            "exists": True,
            "ready": status["ready"],
            "status": status["knowledge_base"].get("status"),
        }
    except DeepTutorError as exc:
        if exc.code == "kb_not_found":
            return {"course_id": course_id, "kb_name": DEEPTUTOR_SERVICE.kb_name(course_id), "exists": False}
        raise HTTPException(status_code=exc.status_code, detail=exc.as_dict()) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "deeptutor_unavailable", "message": "DeepTutor is unavailable."},
        ) from exc


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

        # Ki?m tra c? l?ch s? chat kh?ng
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
                "message": "Kh?ng c? l?ch s? chat d? x?a.",
                "deleted": 0
            }

        # X?a to?n b? l?ch s? c?a sinh vi?n trong m?n n?y
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
            "message": "Da x?a l?ch s? chat.",
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
