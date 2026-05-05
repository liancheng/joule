import unittest

from rich.text import Text

from joule import ast as A

from .dsl.util import side_by_side

unittest.TestCase.maxDiff = None
unittest.TestCase.longMessage = False


class AstTestCase(unittest.TestCase):
    def assertAstEqual(self, obtained: A.AST, expected: A.AST):
        obtained_tree = obtained.pretty
        expected_tree = expected.pretty
        message = Text("\n") + side_by_side(
            f"Obtained:\n{obtained_tree}",
            f"Expected:\n{expected_tree}",
        )
        self.assertMultiLineEqual(obtained_tree, expected_tree, message)
