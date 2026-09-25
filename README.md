# DeepTutor LMS AI Assistant

This university project integrates the DeepTutor framework with a Dalat University LMS demonstration application. It provides a FastAPI backend, a Streamlit user interface, course-scoped knowledge bases, and SRS documentation for the intended system.

## Architecture

```text
LMS / Streamlit UI -> FastAPI backend -> DeepTutor knowledge base and RAG -> AI response
```

Course identifiers are mapped to dedicated DeepTutor knowledge bases so material from one course is not retrieved for another course.

## Repository layout

```text
DeepTutor/       DeepTutor framework pinned as a Git submodule
lms-dlu-demo/    University LMS application and integration
docs/            SRS and supporting project documentation
```

The current requirements source of truth is [`docs/SRS.md`](docs/SRS.md) together with the topic files under [`docs/srs/`](docs/srs/).

## Clone and initialize

Clone with the DeepTutor submodule:

```powershell
git clone --recurse-submodules https://github.com/Huuthien12/lms-ai-assistant.git
```

For an existing clone:

```powershell
git submodule update --init --recursive
```

## Local setup

1. Install a supported Python version.
2. Create a virtual environment for the LMS application.
3. Install `lms-dlu-demo/requirements.txt`.
4. Install and configure the DeepTutor submodule according to its README.
5. Copy `.env.example` to `.env` and set local values. Never commit `.env`.
6. Ensure SQL Server and the configured ODBC driver are available.

Example LMS environment setup:

```powershell
python -m venv lms-dlu-demo\venv
lms-dlu-demo\venv\Scripts\python.exe -m pip install -r lms-dlu-demo\requirements.txt
```

## Run the LMS demo

From Windows, run:

```powershell
lms-dlu-demo\start_lms.bat
```

The launcher starts the FastAPI backend on `http://127.0.0.1:8000` and the Streamlit interface on `http://localhost:8501`.

Demo authentication is disabled unless `LMS_DEMO_AUTH_ENABLED=true` and the demo passwords are supplied through local environment variables.

## Runtime data

Uploads, virtual environments, logs, local databases, DeepTutor runtime data, and generated knowledge-base/vector indexes are deliberately excluded from Git.
