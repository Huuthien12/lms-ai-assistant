"""Production guards for legacy HTTP routes; domain repositories stay reusable."""
import re
from fastapi import HTTPException,Depends,Request
from fastapi.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from moodle_service_auth import require_moodle_service
from deeptutor_integration.auth_contracts import AuthContractError

PUBLIC = {"/", "/health/ready", "/deeptutor/health", "/docs", "/redoc", "/openapi.json"}
GUARDED = {"/auth/me", "/deeptutor/query", "/chat/grounded", "/lms/chat"}
INTERNAL = {"/users", "/db-test", "/courses", "/deeptutor/status", "/deeptutor/legacy-status",
            "/chat/save", "/upload-material/", "/deeptutor/documents", "/deeptutor/knowledge-bases",
            "/lms/ready", "/lms/resources/ingest"}


def resource_owner_lookup(connect):
    def lookup(kind, identifier):
        with connect() as connection:
            cursor = connection.cursor()
            if kind == "attempt":
                row = cursor.execute("SELECT student_id, course_id FROM dbo.QuizAttempts WHERE attempt_id=?", identifier).fetchone()
            else:
                row = cursor.execute("SELECT owner_ref, course_id FROM dbo.VerifiedLearningArtifacts WHERE artifact_type=? AND artifact_id=?", kind, identifier).fetchone()
            if row is None:
                raise HTTPException(404, detail={"code": "artifact_not_found", "message": "Learning artifact was not found."})
            return row[0], row[1]
    return lookup


def install_legacy_security(app, authorizer, owner_lookup):
    @app.middleware("http")
    async def guard(request, call_next):
        path = request.url.path
        try:
            if request.method == "OPTIONS" or path in PUBLIC or path in GUARDED or path.startswith("/learning/"):
                return await call_next(request)
            if path in INTERNAL or path.startswith(("/internal/", "/moodle/", "/materials/")):
                await run_in_threadpool(require_moodle_service, request.headers.get("X-Internal-Api-Key"))
                return await call_next(request)
            dependency = app.dependency_overrides.get(authorizer, authorizer)
            access = await run_in_threadpool(dependency, request)
            # Identity is established before owner lookup or parsing client claims.
            if path.startswith("/chat/history/"):
                parts = path.split("/")
                if len(parts) != 5: raise HTTPException(422)
                access.require_owner(parts[3])
                await run_in_threadpool(access.scope, parts[4])
            elif path.startswith("/courses/"):
                parts = path.split("/")
                course_id = parts[2]
                if path.endswith(("/progress", "/recommendations")):
                    access.require_owner(request.query_params.get("student_id", ""))
                await run_in_threadpool(access.scope, course_id)
            elif path.startswith("/deeptutor/kb/"):
                await run_in_threadpool(access.scope, path.split("/")[3])
            else:
                match = re.fullmatch(r"/(quiz-attempts|quizzes|flashcards)/([^/]+)(?:/(submit|review|reviews|attempts))?", path)
                if not match:
                    raise HTTPException(403, detail={"code": "route_access_denied", "message": "Route access is not permitted."})
                resource, identifier, operation = match.groups()
                kind = {"quiz-attempts": "attempt", "quizzes": "quiz", "flashcards": "flashcard"}[resource]
                owner, course = await run_in_threadpool(owner_lookup, kind, identifier)
                access.require_owner(owner)
                scope = await run_in_threadpool(access.scope, course)
                if operation in {"reviews", "attempts"}:
                    body = await request.json()
                    access.require_owner(body.get("student_id", ""))
                    if operation == "attempts" and body.get("course_id") != scope.course_key:
                        raise HTTPException(403, detail={"code": "course_access_denied", "message": "Course access is not permitted."})
                if operation == "review" and request.query_params.get("student_id") != access.owner_ref:
                    access.require_owner(request.query_params.get("student_id", ""))
            response=await call_next(request)
            if response.status_code>=500:
                return JSONResponse({"detail":{"code":"learning_dependency_unavailable","message":"Application dependency is unavailable."}},status_code=503)
            return response
        except AuthContractError as error:
            return JSONResponse({"detail": error.public_payload()}, status_code=error.status_code)
        except HTTPException as error:
            return JSONResponse({"detail": error.detail}, status_code=error.status_code)
        except (ValueError, TypeError):
            return JSONResponse({"detail": {"code": "invalid_request", "message": "Request is invalid."}}, status_code=422)
        except Exception:
            return JSONResponse({"detail": {"code": "authorization_dependency_unavailable", "message": "Authorization dependency is unavailable."}}, status_code=503)


def create_learning_scope_dependency(authorizer,owner_lookup):
    from backend.services.ai.learning_context import LearningScope
    def scope(request:Request,access=Depends(authorizer)):
        parameters=request.path_params
        course=parameters.get("course_id")
        if course is None:
            for kind,key in (("attempt","attempt_id"),("quiz","quiz_id"),("flashcard","flashcard_id")):
                if key in parameters:
                    owner,course=owner_lookup(kind,parameters[key]); access.require_owner(owner); break
        if course is None: raise HTTPException(503,detail={"code":"learning_scope_unavailable","message":"Learning scope is unavailable."})
        authorized=access.scope(course)
        return LearningScope(owner_id=authorized.owner_ref,course_id=authorized.course_key)
    return scope
