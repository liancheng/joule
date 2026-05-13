import dataclasses as D
import unittest
from typing import Any

from rich.text import Text

from joule import trees as T
from joule.parsers.jsonnet import parse_jsonnet

from .dsl.fake_document import FakeDocument, FakeFile
from .dsl.util import side_by_side

unittest.TestCase.maxDiff = None
unittest.TestCase.longMessage = False


class FakeDocumentTestCase(unittest.TestCase):
    fake_uri = "file:///tmp/test.jsonnet"

    def fake_file(self, source: str, marks: bool = True):
        return FakeFile(source, uri=self.fake_uri, marks=marks)

    def fake_document(self, source: str):
        return FakeDocument(source, uri=self.fake_uri)


class ParsingTestCase(FakeDocumentTestCase):
    def assertAstEqual(self, obtained: T.Tree, expected: T.Tree):
        obtained_tree = obtained.pretty
        expected_tree = expected.pretty
        message = Text("\n") + side_by_side(
            f"Obtained:\n{obtained_tree}",
            f"Expected:\n{expected_tree}",
        )
        self.assertMultiLineEqual(obtained_tree, expected_tree, message)

    def assertParsed(self, doc: FakeFile, rule: str, expected: Any):
        obtained = parse_jsonnet(doc.text, doc.uri, rule)
        if isinstance(expected, T.Tree):
            self.assertAstEqual(obtained, expected)
        else:
            self.assertEqual(obtained, expected)

    @D.dataclass
    class Expectation:
        doc: FakeFile
        rule: str
        test_case: ParsingTestCase

        def expect(self, expected: Any):
            self.test_case.assertParsed(self.doc, self.rule, expected)

    def parse(self, doc: FakeFile, rule: str):
        return ParsingTestCase.Expectation(doc, rule, self)
