from pathlib import Path


def test_verified_learning_schema_starts_after_quiz_and_flashcard_schemas():
    source = (Path(__file__).parents[1] / "lms-dlu-demo" / "main.py").read_text(encoding="utf-8")

    quiz = source.index("app.include_router(create_quiz_router")
    learning = source.index("app.include_router(create_learning_router")
    verified = source.index("app.include_router(create_verified_learning_router")

    assert quiz < verified
    assert learning < verified
