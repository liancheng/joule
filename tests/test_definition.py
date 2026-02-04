import unittest
from textwrap import dedent

from joule.providers import DefinitionProvider

from .dsl import FakeDocument


class TestDefinition(unittest.TestCase):
    def assertDefined(
        self,
        doc: FakeDocument,
        def_mark: str,
        ref_marks: str | list[str],
    ):
        if isinstance(ref_marks, str):
            ref_marks = [ref_marks]

        for ref_mark in ref_marks:
            self.assertSequenceEqual(
                DefinitionProvider.serve(doc.ast, doc.start_of(ref_mark)),
                [doc.at(def_mark)],
            )

    def assertNotDefined(
        self,
        doc: FakeDocument,
        ref_marks: str | list[str],
    ):
        if isinstance(ref_marks, str):
            ref_marks = [ref_marks]

        for ref_mark in ref_marks:
            self.assertSequenceEqual(
                DefinitionProvider.serve(doc.ast, doc.start_of(ref_mark)),
                [],
            )

    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1; x
                      ^1     ^2
                """
            )
        )

        self.assertDefined(t, def_mark="1", ref_marks="2")

    def test_local_shadowing(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1;
                local x = 2;
                      ^1
                x
                ^2
                """
            )
        )

        self.assertDefined(t, def_mark="1", ref_marks="2")

    def test_fn_params(self):
        t = FakeDocument(
            dedent(
                """
                function(p1=p2, p2, p3=p1)
                         ^^1^^2 ^^3 ^^4^^5
                    p1 + p2 + p3
                    ^^6  ^^7  ^^8
                """
            )
        )

        self.assertDefined(t, def_mark="1", ref_marks=["5", "6"])  # p1
        self.assertDefined(t, def_mark="3", ref_marks=["2", "7"])  # p2
        self.assertDefined(t, def_mark="4", ref_marks=["8"])  # p3

    def test_obj_comp(self):
        t = FakeDocument(
            dedent(
                """\
                {
                    local v = 0,
                          ^1
                    ['f' + i]: v,
                           ^2  ^3
                    for i in [1, 2]
                        ^4
                }
                """
            )
        )

        self.assertDefined(t, def_mark="1", ref_marks="3")
        self.assertDefined(t, def_mark="4", ref_marks="2")

    @unittest.skip("TODO")
    def test_obj_comp_obj_local_in_key(self):
        t = FakeDocument(
            dedent(
                """\
                local v = 1;
                      ^1
                {
                    local v = 2,
                    ['f' + i + v]: v,
                               ^2
                    for i in [1, 2]
                }
                """
            )
        )

        self.assertDefined(t, def_mark="1", ref_marks="2")
