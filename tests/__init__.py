import dataclasses as D
import unittest
from typing import Any

from rich.text import Text

from joule import ast as A
from joule.parsers.jsonnet import parse_jsonnet

from .dsl.fake_document import FakeFile
from .dsl.util import side_by_side

unittest.TestCase.maxDiff = None
unittest.TestCase.longMessage = False


class AstTestCase(unittest.TestCase):
    fake_uri = "file:///tmp/test.jsonnet"

    def fake_file(self, source: str, marks: bool = True):
        return FakeFile(source, uri=self.fake_uri, marks=marks)

    def assertParsed(self, doc: FakeFile, rule: str, expected: Any):
        self.assertEqual(parse_jsonnet(doc.uri, doc.text, rule), expected)

    def assertAstParsed(self, doc: FakeFile, rule: str, expected: A.AST):
        self.assertAstEqual(
            obtained=parse_jsonnet(doc.uri, doc.text, rule),
            expected=expected,
        )

    def assertAstEqual(self, obtained: A.AST, expected: A.AST):
        obtained_tree = obtained.pretty
        expected_tree = expected.pretty
        message = Text("\n") + side_by_side(
            f"Obtained:\n{obtained_tree}",
            f"Expected:\n{expected_tree}",
        )
        self.assertMultiLineEqual(obtained_tree, expected_tree, message)

    @D.dataclass
    class Expectation:
        doc: FakeFile
        rule: str
        test_case: AstTestCase

        def expect(self, expected: A.AST | Any):
            match expected:
                case A.AST():
                    self.test_case.assertAstParsed(self.doc, self.rule, expected)
                case _:
                    self.test_case.assertParsed(self.doc, self.rule, expected)

    def parse(self, doc: FakeFile, rule: str):
        return AstTestCase.Expectation(doc, rule, self)
