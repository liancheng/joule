import joule.trees as T
from joule.trees import BinaryOp as B
from joule.trees import ForSpec, IfSpec
from joule.trees import UnaryOp as U
from tests import FakeDocumentTestCase
from tests.dsl import arg, bind


class TestParser(FakeDocumentTestCase):
    def assertAstEqual(self, actual: T.Tree, expected: T.Tree):
        self.assertEqual(actual.pretty, expected.pretty)

    def assertStrEqual(self, source: str, expected: str):
        t = self.fake_document(source)
        self.assertAstEqual(t.body, t.span.string(expected))

    def assertNumEqual(self, source: str, expected: float):
        t = self.fake_document(source)
        self.assertAstEqual(t.body, t.span.num(expected))

    def test_null(self):
        t = self.fake_document("null")
        self.assertAstEqual(t.body, t.span.null)

    def test_bool(self):
        t = self.fake_document("true")
        self.assertAstEqual(t.body, t.span.true)

        t = self.fake_document("false")
        self.assertAstEqual(t.body, t.span.false)

    def test_num(self):
        with self.subTest("decimal"):
            self.assertNumEqual("0", 0)
            self.assertNumEqual("0.", 0)

            self.assertNumEqual("1.", 1)
            self.assertNumEqual("1.05", 1.05)

            self.assertNumEqual("1.e2", 100)
            self.assertNumEqual("1.e+2", 100)
            self.assertNumEqual("1.e-2", 0.01)

            self.assertNumEqual("1.25e2", 125)
            self.assertNumEqual("1.25e+2", 125)
            self.assertNumEqual("1.25e-2", 0.0125)

        with self.subTest("binary"):
            self.assertNumEqual("0b0", 0)
            self.assertNumEqual("0b1", 1)
            self.assertNumEqual("0B01", 1)
            self.assertNumEqual("0B101", 5)

        with self.subTest("octal"):
            self.assertNumEqual("0o0", 0)
            self.assertNumEqual("0o7", 7)
            self.assertNumEqual("0O10", 8)
            self.assertNumEqual("0O011", 9)

        with self.subTest("hexical"):
            self.assertNumEqual("0x0", 0)
            self.assertNumEqual("0xf", 15)
            self.assertNumEqual("0X10", 16)
            self.assertNumEqual("0X011", 17)

    def test_quoted_string(self):
        with self.subTest("non-verbatim"):
            self.assertStrEqual(r'""', "")
            self.assertStrEqual(r"''", "")
            self.assertStrEqual(r'"\n"', "\n")
            self.assertStrEqual(r"'\n'", "\n")
            self.assertStrEqual(r"'\u0041'", "A")
            self.assertStrEqual(r"'\uD83D\uDE00'", "😀")

        with self.subTest("verbatim"):
            self.assertStrEqual(r'@""', r"")
            self.assertStrEqual(r"@''", r"")
            self.assertStrEqual(r'@"\n"', r"\n")
            self.assertStrEqual(r"@'\n'", r"\n")
            self.assertStrEqual(r"@'\u0041'", r"\u0041")
            self.assertStrEqual(r"@'\uD83D\uDE00'", r"\uD83D\uDE00")

    def test_text_block(self):
        for maybe_dash in ["", "-"]:
            maybe_newline = "\n" if maybe_dash == "" else ""

            with self.subTest(trailing_newline=maybe_newline == ""):
                self.assertStrEqual(
                    f"""\
                    |||{maybe_dash}
                        a
                            b
                    |||""",
                    f"a\n    b{maybe_newline}",
                )

                self.assertStrEqual(
                    f"""\
                    |||{maybe_dash}
                        \\uD83D\\uDE00
                    |||""",
                    rf"\uD83D\uDE00{maybe_newline}",
                )

                self.assertStrEqual(
                    f"""\
                    |||{maybe_dash}
                        a

                        b
                    |||""",
                    f"a\n\nb{maybe_newline}",
                )

                self.assertStrEqual(
                    f"""\
                    |||{maybe_dash}

                        a
                    |||""",
                    f"\na{maybe_newline}",
                )

    def test_array(self):
        with self.subTest("empty"):
            t = self.fake_document("[]")
            self.assertAstEqual(t.body, t.span.array())

        with self.subTest("nested"):
            t = self.fake_document(
                """\
                [[]]
                |^^1
                """
            )

            self.assertAstEqual(
                t.body,
                t.span.array(t.at(1).array()),
            )

        for maybe_comma in ["", ","]:
            with self.subTest(trailing_comma=maybe_comma == ","):
                t = self.fake_document(
                    f"""\
                    [1{maybe_comma}]
                    |^1
                    """
                )

                self.assertAstEqual(
                    t.body,
                    t.span.array(t.at(1).num(1)),
                )

                t = self.fake_document(
                    f"""\
                    [1, 2{maybe_comma}]
                    |^1 ^2
                    """
                )

                self.assertAstEqual(
                    t.body,
                    t.span.array(
                        t.at(1).num(1),
                        t.at(2).num(2),
                    ),
                )

    def test_unary(self):
        t = self.fake_document(
            """\
            !true
            |^^^^1
            """
        )

        self.assertAstEqual(
            t.body,
            U.Not(t.span, t.at(1).true),
        )

        t = self.fake_document(
            """\
            +1
            |^1
            """
        )

        self.assertAstEqual(
            t.body,
            U.Plus(t.span, t.at(1).num(1)),
        )

        t = self.fake_document(
            """\
            -1
            |^1
            """
        )

        self.assertAstEqual(
            t.body,
            U.Negate(t.span, t.at(1).num(1)),
        )

        t = self.fake_document(
            """\
            ~x
            |^1
            """
        )

        self.assertAstEqual(
            t.body,
            U.BitNot(t.span, t.at(1).var_ref("x")),
        )

    def test_binary(self):
        t = self.fake_document(
            """\
            v1 + v2 * v3 < v4 && v5 in v6 == v7
            ^^1  ^^2  ^^3  ^^4   ^^5   ^^6   ^^7
            """
        )

        v1 = t.at(1).var_ref("v1")
        v2 = t.at(2).var_ref("v2")
        v3 = t.at(3).var_ref("v3")
        v4 = t.at(4).var_ref("v4")
        v5 = t.at(5).var_ref("v5")
        v6 = t.at(6).var_ref("v6")
        v7 = t.at(7).var_ref("v7")

        plus_rhs = B.Multiply(v2, v3)
        lt_lhs = B.Plus(v1, plus_rhs)
        eq_lhs = B.In(v5, v6)
        and_lhs = B.LT(lt_lhs, v4)
        and_rhs = B.Eq(eq_lhs, v7)
        expr = B.And(and_lhs, and_rhs)

        self.assertAstEqual(t.body, expr)

    def test_import(self):
        t = self.fake_document(
            """\
            import "file"
            |      ^^^^^^1
            """
        )

        self.assertAstEqual(
            t.body,
            T.Import(
                t.span,
                kind=T.ImportKind.Default,
                importee=T.Importee.from_string(t.at(1).string("file")),
            ),
        )

    def test_assert(self):
        t = self.fake_document(
            """\
            assert true; null
            ^1     ^^^^2 ^^^^3
            """
        )

        self.assertAstEqual(
            t.body,
            T.AssertedExpr(
                t.span,
                T.Assert(
                    t.at(1).merge(t.at(2)),
                    condition=t.at(2).true,
                ),
                body=t.at(3).null,
            ),
        )

    def test_fn(self):
        t = self.fake_document(
            """\
            function() null
            |          ^^^^1
            """
        )

        self.assertAstEqual(
            t.body,
            T.Fn(t.span, params=[], body=t.at(1).null),
        )

        t = self.fake_document(
            """\
            function(a) a
            |        ^1 ^2
            """
        )

        self.assertAstEqual(
            t.body,
            T.Fn(
                t.span,
                params=[t.at(1).param("a")],
                body=t.at(2).var_ref("a"),
            ),
        )

        t = self.fake_document(
            """\
            function(a = 1) a
            |        ^1  ^2 ^3
            """
        )

        self.assertAstEqual(
            t.body,
            T.Fn(
                t.span,
                params=[t.at(1).param("a", default=t.at(2).num(1))],
                body=t.at(3).var_ref("a"),
            ),
        )

        t = self.fake_document(
            """\
            function(a, b = a) a + b
            |        ^1 ^2  ^3 ^4  ^5
            """
        )

        self.assertAstEqual(
            t.body,
            T.Fn(
                t.span,
                params=[
                    t.at(1).param("a"),
                    t.at(2).param("b", default=t.at(3).var_ref("a")),
                ],
                body=B.Plus(
                    t.at(4).var_ref("a"),
                    t.at(5).var_ref("b"),
                ),
            ),
        )

    def test_local(self):
        t = self.fake_document(
            """\
            local x = 1; x
            |     ^1  ^2 ^3
            """
        )

        self.assertAstEqual(
            t.body,
            T.Local(
                t.span,
                binds=[bind(t.at(1).var("x"), t.at(2).num(1))],
                body=t.at(3).var_ref("x"),
            ),
        )

        t = self.fake_document(
            """\
            local f() = null; f
            |     ^1
            |      ^^2  ^^^^3 ^4
            """
        )

        fn = T.Fn(
            t.at(2).merge(t.at(3)),
            params=[],
            body=t.at(3).null,
        )

        self.assertAstEqual(
            t.body,
            T.Local(
                t.span,
                binds=[bind(t.at(1).var("f"), fn)],
                body=t.at(4).var_ref("f"),
            ),
        )

        t = self.fake_document(
            """\
            local x = 1, y = 2; x + y
            |     ^1  ^2 ^3  ^4 ^5  ^6
            """
        )

        self.assertAstEqual(
            t.body,
            T.Local(
                t.span,
                binds=[
                    bind(t.at(1).var("x"), t.at(2).num(1)),
                    bind(t.at(3).var("y"), t.at(4).num(2)),
                ],
                body=B.Plus(
                    t.at(5).var_ref("x"),
                    t.at(6).var_ref("y"),
                ),
            ),
        )

    def test_call(self):
        t = self.fake_document(
            """\
            f()
            ^1
            """
        )

        self.assertAstEqual(
            t.body,
            T.Call(t.span, fn=t.at(1).var_ref("f"), args=[]),
        )

        t = self.fake_document(
            """\
            f(1, a=2)
            ^1^2 ^3^4
            """
        )

        self.assertAstEqual(
            t.body,
            T.Call(
                t.span,
                fn=t.at(1).var_ref("f"),
                args=[
                    arg(t.at(2).num(1)),
                    arg(t.at(4).num(2), t.at(3).param_ref("a")),
                ],
            ),
        )

    def test_array_comp(self):
        t = self.fake_document(
            """\
            [i for i in x if true]
            |^1    ^2   ^3   ^^^^4
            |  ^^^^^^^^^^5^^^^^^^6
            """
        )

        self.assertAstEqual(
            t.body,
            T.ArrayComp(
                t.span,
                expr=t.at(1).var_ref("i"),
                for_spec=ForSpec(
                    t.at(5),
                    id=t.at(2).var("i"),
                    source=t.at(3).var_ref("x"),
                ),
                extra_specs=[
                    IfSpec(
                        t.at(6),
                        condition=t.at(4).true,
                    )
                ],
            ),
        )
