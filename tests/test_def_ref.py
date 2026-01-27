import unittest
from textwrap import dedent

import lsprotocol.types as L
from rich.console import Console
from rich.text import Text

from .dsl import FakeDocument, FakeWorkspace, side_by_side

TITLE_STYLE = "black on yellow"
DEFAULT_HIGHLIGHT_STYLE = "black on blue"
EXPECTED_HIGHLIGHT_STYLE = "black on green"
OBSERVED_HIGHLIGHT_STYLE = "black on red"


class TestDefRef(unittest.TestCase):
    def assertLocationsEqual(
        self,
        workspace: FakeWorkspace,
        obtained: list[L.Location],
        expected: list[L.Location],
        clue: Text | None = None,
    ):
        docs = workspace.docs.values()

        def sort_key(loc: L.Location):
            return (loc.uri, loc.range.start, loc.range.end)

        obtained.sort(key=sort_key)
        expected.sort(key=sort_key)

        def highlight(locations: list[L.Location], style: str) -> Text:
            return Text("\n" * 2).join(
                [
                    doc.highlight(ranges, style)
                    for uri, group in groupby(locations, lambda loc: loc.uri)
                    if (doc := next(d for d in docs if d.uri == uri)) is not None
                    if (ranges := list(location.range for location in group))
                ]
            )

        def header(title: str) -> Text:
            return Text.styled(title + "\n", TITLE_STYLE)

        console = Console()

        with console.capture() as capture:
            from itertools import groupby

            console.print("\n")

            if clue is not None:
                console.print(clue)

            message = side_by_side(
                header("Expected") + highlight(expected, EXPECTED_HIGHLIGHT_STYLE),
                header("Obtained") + highlight(obtained, OBSERVED_HIGHLIGHT_STYLE),
            )

            console.print(message)

        self.assertSequenceEqual(obtained, expected, msg=capture.get())

    def checkDefRefs(
        self,
        workspace: FakeWorkspace,
        def_location: L.Location,
        ref_locations: list[L.Location],
    ):
        def_doc = workspace.docs[def_location.uri]

        clue = Text("\n").join(
            [
                Text("Checking symbol reference(s):"),
                def_doc.highlight([def_location.range], TITLE_STYLE),
            ]
        )

        self.assertLocationsEqual(
            workspace,
            workspace.index.references(
                def_location.uri,
                def_location.range.start,
            ),
            ref_locations,
            clue,
        )

        for location in ref_locations:
            ref_doc = workspace.docs[location.uri]

            clue = Text("\n").join(
                [
                    Text("Checking symbol definition:"),
                    ref_doc.highlight([location.range], TITLE_STYLE),
                ]
            )

            self.assertLocationsEqual(
                workspace,
                workspace.index.definitions(
                    location.uri,
                    location.range.start,
                ),
                [def_location],
                clue,
            )

    def test_local_bind(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1; x + x
                      ^x     ^x.1^x.2
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("x"),
            ref_locations=[
                t.at("x.1"),
                t.at("x.2"),
            ],
        )

    def test_field(self):
        t = FakeDocument(
            dedent(
                """\
                { f: 1 }.f
                  ^f     ^f.1
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("f"),
            ref_locations=[t.at("f.1")],
        )

    def test_nested_field(self):
        t = FakeDocument(
            dedent(
                """\
                { f: { g: 1 } }.f.g
                       ^g         ^g.1
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("g"),
            ref_locations=[t.at("g.1")],
        )

    def test_obj_obj_composition(self):
        t = FakeDocument(
            dedent(
                """\
                (
                    { f: 1 }
                    { f: 2 }
                      ^f
                ).f
                  ^f.1
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("f"),
            ref_locations=[t.at("f.1")],
        )

    def test_var_obj_composition(self):
        t = FakeDocument(
            dedent(
                """\
                local o = { f: 1 };
                (o + { f: 2 }).f
                       ^f      ^f.1
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("f"),
            ref_locations=[t.at("f.1")],
        )

    def test_obj_var_composition(self):
        t = FakeDocument(
            dedent(
                """\
                local o = { f: 1 };
                            ^f
                ({ f: 2 } + o).f
                               ^f.1
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("f"),
            ref_locations=[t.at("f.1")],
        )

    def test_var_var_composition(self):
        t = FakeDocument(
            dedent(
                """\
                local o1 = { f: 1 };
                local o2 = { f: 2 };
                local o3 = { f: { g: 3 } };
                                  ^g
                (o1 + o2 + o3).f.g
                                 ^g.1
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("g"),
            ref_locations=[t.at("g.1")],
        )

    @unittest.skip("Cross-document references not implemented")
    def test_import(self):
        t1 = FakeDocument(
            dedent(
                """\
                { f: 1 },
                  ^f
                """
            ),
            uri="file:///test/t1.jsonnet",
        )

        t2 = FakeDocument(
            dedent(
                """\
                (import 't1.jsonnet').f
                                      ^f
                """
            ),
            uri="file:///test/t2.jsonnet",
        )

        self.checkDefRefs(
            FakeWorkspace(
                root_uri="file:///test/",
                docs=[t1, t2],
            ),
            def_location=t1.at("f"),
            ref_locations=[t2.at("f")],
        )

    def test_same_var_field_names(self):
        t1 = FakeDocument(
            dedent(
                """\
                local f = { f: 1 };
                      ^1    ^2
                { f: f }.f.f
                  ^3 ^4  ^5^6
                """
            ),
            uri="file:///test/t1.jsonnet",
        )

        FakeWorkspace.single_doc(t1)

        self.checkDefRefs(
            FakeWorkspace.single_doc(t1),
            def_location=t1.at("1"),
            ref_locations=[t1.at("4")],
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t1),
            def_location=t1.at("2"),
            ref_locations=[t1.at("6")],
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t1),
            def_location=t1.at("3"),
            ref_locations=[t1.at("5")],
        )

    @unittest.skip("Cross-document references not implemented")
    def test_import_with_local(self):
        t1 = FakeDocument(
            dedent(
                """\
                local o1 = { f: 0 }; o1
                             ^f_def
                """
            ),
            uri="file:///test/t1.jsonnet",
        )

        t2 = FakeDocument(
            dedent(
                """\
                local o2 = import 't1.jsonnet'; o2.f
                                                   ^f_ref
                """
            ),
            uri="file:///test/t2.jsonnet",
        )

        self.checkDefRefs(
            FakeWorkspace(
                root_uri="file:///test/",
                docs=[t1, t2],
            ),
            def_location=t1.at("f_def"),
            ref_locations=[t2.at("f_ref")],
        )

    def test_self(self):
        t = FakeDocument(
            dedent(
                """\
                { f1: 1, f2: self.f1 }
                  ^^f1            ^^f1.1
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("f1"),
            ref_locations=[t.at("f1.1")],
        )

    def test_super_obj_obj(self):
        t = FakeDocument(
            dedent(
                """\
                { f1: 1 }
                  ^^f1
                + { f1: 2, f2: super.f1 }
                                     ^^f1.1
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("f1"),
            ref_locations=[t.at("f1.1")],
        )

    def test_super_var_obj(self):
        t = FakeDocument(
            dedent(
                """\
                local o1 = { f1: 1 };
                      ^^o1   ^^f1
                o1 + { f1: 2, f2: super.f1 }
                ^^o1.1                  ^^f1.1
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("f1"),
            ref_locations=[t.at("f1.1")],
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("o1"),
            ref_locations=[t.at("o1.1")],
        )

    def test_super_var_var(self):
        t = FakeDocument(
            dedent(
                """\
                local o1 = {
                      ^^o1
                    f1: 1
                };
                local o2 = {
                      ^^o2
                    f1: 2,
                    f2: super.f1
                };
                o1 + o2
                ^^o1.1
                     ^^o2.1
                """
            )
        )

        # NOTE: In this case, although `super.f1` on line 6 references `f1: 1` on line
        # 2, our current 1-pass indexing approach cannot detect this reference. This is
        # because `o2` is defined and indexed before `o1 + o2`, while the `super` scope
        # won't be set up until we index `o1 + o2`.

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("o1"),
            ref_locations=[t.at("o1.1")],
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("o2"),
            ref_locations=[t.at("o2.1")],
        )

    def test_fn_params(self):
        t = FakeDocument(
            dedent(
                """\
                local f(p) =
                      ^f_def
                        ^p_def
                    p + 1;
                    ^p_ref
                f(1)
                ^f_ref
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("p_def"),
            ref_locations=[t.at("p_ref")],
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("f_def"),
            ref_locations=[t.at("f_ref")],
        )

    def test_fn_param_refs(self):
        t = FakeDocument(
            dedent(
                """\
                function(
                    p1 = p2,
                    ^^p1 ^^p2.1
                    p2 = 3,
                    ^^p2
                    p3 = p1,
                    ^^p3 ^^p1.1
                ) p1 + p2 + p3;
                  ^^p1.2    ^^p3.1
                       ^^p2.2
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("p1"),
            ref_locations=[
                t.at("p1.1"),
                t.at("p1.2"),
            ],
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("p2"),
            ref_locations=[
                t.at("p2.1"),
                t.at("p2.2"),
            ],
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("p3"),
            ref_locations=[t.at("p3.1")],
        )

    def test_list_comp(self):
        t = FakeDocument(
            dedent(
                """\
                [local y = 1; x + y for x in std.range(1, 3)]
                       ^y     ^x.1^y.1  ^x
                """
            )
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("x"),
            ref_locations=[t.at("x.1")],
        )

        self.checkDefRefs(
            FakeWorkspace.single_doc(t),
            def_location=t.at("y"),
            ref_locations=[t.at("y.1")],
        )
