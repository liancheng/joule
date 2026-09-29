import unittest
from typing import override

import ocdiff

from joule.trees import Tree
from tests.dsl import FakeDocument


class FakeDocumentTestCase(unittest.TestCase):
    fake_uri = "file:///tmp/test.jsonnet"

    @override
    def assertEqual(self, first, second, msg=None):
        if isinstance(first, Tree) and isinstance(second, Tree):
            if first != second:
                diff = ocdiff.console_diff(first.pretty, second.pretty)
                message = diff if msg is None else f"{msg}\n{diff}"
                raise self.failureException(message)
        else:
            super().assertEqual(first, second, msg)

    def fake_document(self, source: str) -> FakeDocument:
        return FakeDocument(source, uri=self.fake_uri)
