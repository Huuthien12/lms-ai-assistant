"""HTTP/application projection of Tho's sole personal Moodle trust boundary."""
from dataclasses import dataclass,field
from hashlib import sha256
from fastapi import HTTPException,Request
from deeptutor_integration.auth_contracts import AuthContractError,AuthorizationNotConfiguredError,CourseAction,CourseAccessDeniedError,PrincipalRequiredError
from deeptutor_integration.contracts import AuthorizedCourseScope
from deeptutor_integration.moodle_trust import MoodleTrustBoundary,personal_bearer_token
from deeptutor_integration.errors import DeepTutorError


def _reject(error): raise HTTPException(error.status_code,detail=error.public_payload()) from None


@dataclass
class MoodleQueryAccess:
    service: object=field(repr=False)
    request: Request=field(repr=False)
    boundary: MoodleTrustBoundary=field(repr=False)
    principal: object
    binding: object
    _token: str=field(repr=False)
    _enrollments: list=field(repr=False)

    @property
    def owner_ref(self):
        # Preserve PR35 owner refs across the canonical Moodle issuer prefix migration.
        return sha256((self.binding.moodle_namespace+"\0"+str(self.binding.moodle_user_id)).encode()).hexdigest()

    def courses(self): return self._enrollments

    def project(self,context):
        if context.binding!=self.binding: _reject(CourseAccessDeniedError())
        scope=context.scope
        result=AuthorizedCourseScope(scope.moodle_course_id,scope.canonical_course_key,scope.kb_id,self.owner_ref,scope.moodle_namespace)
        if result.canonical_scope!=scope: _reject(CourseAccessDeniedError())
        return result

    def scope(self,course_id,kb_name=None,action=CourseAction.QUERY_COURSE):
        try:
            context=self.boundary.authorize(self._token,course_id,action)
            result=self.project(context)
            if kb_name is not None: self.service.kb_name(result.course_key,kb_name)
            return result
        except AuthContractError as error: _reject(error)
        except DeepTutorError as error: raise HTTPException(error.status_code,detail=error.as_dict()) from None

    def reauthorize(self,scope,action=CourseAction.QUERY_COURSE):
        current=self.scope(scope.moodle_course_id,scope.kb_name,action)
        if current!=scope: _reject(CourseAccessDeniedError())
        return current

    def require_owner(self,owner_ref):
        if owner_ref!=self.owner_ref: _reject(CourseAccessDeniedError())

    def __call__(self,query):
        scope=self.scope(query.course_id,query.kb_id)
        query.course_id,query.kb_id=scope.course_key,scope.kb_name
        self.request.state.authorized_scope=scope


def create_moodle_query_authorizer(service,base_url,capability_evidence=None,forbidden_tokens=(),file_credential_parameter="token"):
    forbidden=frozenset(t for t in forbidden_tokens if t)
    def require_course_query(request:Request):
        try:
            token=personal_bearer_token(request.headers.get("Authorization"))
            if token in forbidden: raise PrincipalRequiredError()
            try:
                boundary=MoodleTrustBoundary(base_url or "",course_kb_resolver=service.kb_name,capability_evidence=capability_evidence,file_credential_parameter=file_credential_parameter)
            except (ValueError,TypeError): raise AuthorizationNotConfiguredError() from None
            principal,binding,courses=boundary.enrolled_courses(token)
            access=MoodleQueryAccess(service,request,boundary,principal,binding,token,courses)
            request.state.moodle_access=access
            return access
        except AuthContractError as error: _reject(error)
    return require_course_query
