# Self-hosted Moodle runtime

This repository runs Moodle locally in Docker, independently from the FastAPI/Streamlit LMS demo, DeepTutor, Ollama, and any MoodleCloud instance.

## Architecture

```text
Browser → Moodle :8088 → MariaDB
LMS backend → Moodle REST API → MoodleAdapter → DeepTutorService → KB/RAG
```

Compose project `deeptutor-moodle` creates the `deeptutor-moodle` and `deeptutor-moodle-db` containers. Named volumes `deeptutor-moodle-app`, `deeptutor-moodle-data`, and `deeptutor-moodle-db-data` persist Moodle application configuration, uploaded Moodle files, and MariaDB state. Compose configuration and secrets remain separate: real values belong only in ignored `.moodle.env`.

## First start

1. Copy `.moodle.env.example` to `.moodle.env` and replace both password placeholders locally. Do not commit it.
2. Run `docker compose --env-file .moodle.env -f docker/moodle/compose.yml up -d --build`.
3. Open `http://127.0.0.1:8088` and finish the Moodle installer. Use database host `db`, port `3306`, database/user/password from `.moodle.env`, and the database type **MariaDB**.
4. Set Moodle's web address to `http://127.0.0.1:8088`; Moodle data directory is `/var/www/moodledata`.

## Administration and web services

After initial setup, create a least-privilege integration user, enable Web Services and REST, create an external service, and grant only these functions used by `MoodleAdapter`:

- `core_course_get_courses`
- `mod_resource_get_resources_by_courses`

Create a token for that integration user. Store it only in ignored `.env` as `MOODLE_TOKEN`; set `MOODLE_BASE_URL=http://127.0.0.1:8088`. Never place the token in Compose, source code, screenshots, or Git.

## INT1339 migration

Prefer Moodle's official course backup/restore from MoodleCloud. Restore the course while preserving the logical shortname `INT1339`; numeric course and resource IDs may change. Verify the required `Chuong 1.pdf` resource through the REST service, then call `POST /moodle/resources/ingest` using the new numeric IDs. The existing resolver keeps `INT1339 → int1339-python`.

If MoodleCloud backup/download needs login, MFA, or administrator access unavailable to the automation, perform only that download/restore yourself and do not share credentials or tokens.

## Operation

```powershell
docker compose --env-file .moodle.env -f docker/moodle/compose.yml up -d
docker compose --env-file .moodle.env -f docker/moodle/compose.yml ps
docker compose --env-file .moodle.env -f docker/moodle/compose.yml logs --tail=200 moodle db
docker compose --env-file .moodle.env -f docker/moodle/compose.yml stop
docker compose --env-file .moodle.env -f docker/moodle/compose.yml start
```

Do not run `down -v`: it deletes the persistent named volumes. For demo day: start Docker Desktop, start this Compose stack, verify Moodle REST/token, start Ollama and DeepTutor, run `lms-dlu-demo\start_lms.bat`, then check `/health/ready`, `/lms/ready`, and `/lms/chat`.

## Verification and persistence

After Moodle is configured, verify `docker compose ... ps`, visit Moodle, use the two REST functions through `MoodleAdapter`, stop/start the stack, then verify the course, PDF, service configuration, and token still work. Moodle version is the checked-out `MOODLE_405_STABLE` source revision printed by `git -C /var/www/html describe --always` inside the Moodle container.

## Troubleshooting

- A database healthcheck failure: inspect `docker compose ... logs db`; do not delete volumes.
- Installer loops: verify Moodle URL is exactly `http://127.0.0.1:8088` and DB host remains `db`.
- Adapter reports unavailable: confirm ignored `.env` contains `MOODLE_BASE_URL` and a valid service token.
- A port conflict: change only `MOODLE_HTTP_PORT` in ignored `.moodle.env`, then restart the Compose stack.
