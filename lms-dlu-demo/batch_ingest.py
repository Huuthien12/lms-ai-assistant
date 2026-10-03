import sys

from deeptutor_client import DeepTutorAPIClient, create_deeptutor_client

def get_client() -> DeepTutorAPIClient:
    return create_deeptutor_client()

def run_batch_ingestion(course_id_moodle: int, resource_id: int, kb_name: str | None = None):
    client = get_client()
    return client.ingest_resource(course_id_moodle, resource_id, kb_name)

if __name__ == "__main__":
    if len(sys.argv) not in {3, 4}:
        raise SystemExit("Usage: batch_ingest.py COURSE_ID_MOODLE RESOURCE_ID [KB_NAME]")
    print(run_batch_ingestion(int(sys.argv[1]), int(sys.argv[2]), *(sys.argv[3:])))
