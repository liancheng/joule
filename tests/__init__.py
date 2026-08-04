import unittest
from textwrap import dedent

from tests.dsl import FakeDocument


class FakeDocumentTestCase(unittest.TestCase):
    fake_uri = "file:///tmp/test.jsonnet"

    def fake_document(self, source: str, marks: bool = True) -> FakeDocument:
        return FakeDocument(dedent(source), uri=self.fake_uri, marks=marks)
