from contextlib import ExitStack
from pathlib import Path
import tempfile
import types
import unittest
import fitz
from portable_smoke_test import close_document, make_test_pdf


class SmokeCleanupTests(unittest.TestCase):
    def test_open_pdf_is_closed_before_temp_directory_cleanup(self):
        for fail in (False,True):
            with self.subTest(fail=fail):
                app=types.SimpleNamespace(doc=None)
                doc=None
                try:
                    with tempfile.TemporaryDirectory() as td, ExitStack() as cleanup:
                        path=Path(td)/'test.pdf';make_test_pdf(path)
                        doc=fitz.open(path);app.doc=doc
                        cleanup.callback(close_document,app)
                        if fail:raise RuntimeError('simulated export failure')
                except RuntimeError:
                    if not fail:raise
                self.assertIsNone(app.doc)
                self.assertTrue(doc.is_closed)
                self.assertFalse(Path(td).exists())

    def test_close_is_safe_when_no_document_remains(self):
        close_document(None)
        close_document(types.SimpleNamespace(doc=None))


if __name__=='__main__':unittest.main()
