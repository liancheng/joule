import os
import unittest

import ocdiff

from joule.trees import Tree
from tests.dsl import FakeDocument


class FakeDocumentTestCase(unittest.TestCase):
    fake_uri = "file:///tmp/test.jsonnet"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.maxDiff = None

        def func(first: Tree, second: Tree, msg: str | None = None):
            if first != second:
                diff = ocdiff.console_diff(first.pretty, second.pretty)
                message = diff if msg is None else f"{msg}\n{diff}"
                raise self.failureException(message)

        def register(cls: type) -> None:
            self.addTypeEqualityFunc(cls, func)
            for subclass in cls.__subclasses__():
                register(subclass)

        if os.environ.get("CI", "").lower() in ("", "0", "false"):
            register(Tree)

    def fake_document(self, source: str, marks: bool = True) -> FakeDocument:
        return FakeDocument(source, uri=self.fake_uri, marks=marks)
