from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


def _authorize_moodle_service(x_internal_api_key: str | None, service_token: str | None) -> None:
    if not service_token:
        raise HTTPException(
            status_code=503,
            detail={"code": "moodle_service_not_configured", "message": "Moodle service is not configured."},
        )
    if not x_internal_api_key or not hmac.compare_digest(x_internal_api_key, service_token):
        raise HTTPException(
            status_code=401,
            detail={"code": "moodle_service_unauthorized", "message": "Moodle service authorization is required."},
        )


def require_moodle_service(
    x_internal_api_key: str | None = Header(default=None),
) -> None:
    _authorize_moodle_service(x_internal_api_key, os.getenv("LMS_MOODLE_DISCOVERY_TOKEN"))


def create_moodle_service_dependency(service_token: str | None):
    def require_configured_moodle_service(
        x_internal_api_key: str | None = Header(default=None),
    ) -> None:
        _authorize_moodle_service(x_internal_api_key, service_token)

    return require_configured_moodle_service
