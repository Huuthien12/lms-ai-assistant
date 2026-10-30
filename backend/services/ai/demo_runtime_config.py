def cors_origins(value: str | None) -> list[str]:
    origins = [item.strip() for item in (value or "http://127.0.0.1:8502,http://localhost:8502").split(",") if item.strip()]
    if not origins or "*" in origins or any(not item.startswith(("http://", "https://")) for item in origins):
        raise ValueError("LMS_CORS_ORIGINS must be explicit http(s) origins")
    return origins
