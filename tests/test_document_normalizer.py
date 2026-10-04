from __future__ import annotations

import unittest

from deeptutor_integration.contracts import SourceDocument
from deeptutor_integration.document_normalizer import DocumentNormalizer, source_sha256
from deeptutor_integration.errors import DeepTutorError


class DocumentNormalizerTests(unittest.TestCase):
    def source(self, filename="notes.md", mime_type="text/markdown", content=b"# Notes\r\n\r\nText"):
        return SourceDocument(
            document_id="resource-1", course_id="INT1339", filename=filename,
            mime_type=mime_type, source="moodle", content=content,
            metadata={"course_name": "Python", "token": "private", "download_url": "https://private"},
        )

    def test_normalizes_markdown_and_preserves_safe_provenance(self):
        result = DocumentNormalizer().normalize(self.source())
        self.assertEqual(result.markdown, "# Notes\n\nText")
        self.assertEqual(result.normalizer_version, "markdown-v1")
        self.assertEqual(result.document_id, "resource-1")
        self.assertEqual(result.course_id, "INT1339")
        self.assertEqual(result.original_filename, "notes.md")
        self.assertEqual(result.original_mime_type, "text/markdown")
        self.assertEqual(result.source, "moodle")
        self.assertEqual(result.metadata, {"course_name": "Python"})
        self.assertNotIn("private", str(result.model_dump()))

    def test_bom_is_removed(self):
        self.assertEqual(DocumentNormalizer().normalize(self.source(content=b"\xef\xbb\xbf# Notes")).markdown, "# Notes")

    def test_hash_is_deterministic_and_tracks_original_bytes(self):
        self.assertEqual(source_sha256(b"same"), source_sha256(b"same"))
        self.assertNotEqual(source_sha256(b"first"), source_sha256(b"second"))

    def test_empty_bytes_and_blank_markdown_are_rejected(self):
        with self.assertRaisesRegex(DeepTutorError, "non-empty"):
            source_sha256(b"")
        with self.assertRaisesRegex(DeepTutorError, "must not be blank"):
            DocumentNormalizer().normalize(self.source(content=b" \t\r\n"))

    def test_invalid_utf8_is_rejected_without_exposing_content(self):
        with self.assertRaises(DeepTutorError) as raised:
            DocumentNormalizer().normalize(self.source(content=b"secret-content-\xff"))
        self.assertEqual(raised.exception.code, "invalid_document")
        self.assertNotIn("secret-content", str(raised.exception))

    def test_unsupported_and_mismatched_formats_are_rejected(self):
        with self.assertRaisesRegex(DeepTutorError, "not supported"):
            DocumentNormalizer().normalize(self.source(filename="notes.exe", mime_type="application/octet-stream"))
        with self.assertRaisesRegex(DeepTutorError, "does not match"):
            DocumentNormalizer().normalize(self.source(filename="notes.md", mime_type="application/pdf"))

    def test_binary_formats_are_recognized_but_unavailable(self):
        cases = (
            ("notes.pdf", "application/pdf"),
            ("notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("notes.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
            ("notes.ppt", "application/vnd.ms-powerpoint"),
        )
        for filename, mime_type in cases:
            with self.subTest(filename=filename):
                with self.assertRaises(DeepTutorError) as raised:
                    DocumentNormalizer().normalize(self.source(filename=filename, mime_type=mime_type, content=b"binary"))
                self.assertEqual((raised.exception.code, raised.exception.status_code), ("normalizer_unavailable", 501))


if __name__ == "__main__":
    unittest.main()
