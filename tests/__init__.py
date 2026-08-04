import unittest
from textwrap import dedent
from typing import override

from tests.dsl import FakeDocument


class FakeDocumentTestCase(unittest.TestCase):
    fake_uri = "file:///tmp/test.jsonnet"

    @override
    def setUp(self):
        self.maxDiff = None

    def fake_document(self, source: str, marks: bool = True) -> FakeDocument:
        return FakeDocument(dedent(source), uri=self.fake_uri, marks=marks)
