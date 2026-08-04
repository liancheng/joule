import joule.trees as T
from joule.trees import UnaryOp as U
from tests import FakeDocumentTestCase


class TestParser(FakeDocumentTestCase):
    def assertAstEqual(self, actual: T.Tree, expected: T.Tree):
        self.assertEqual(actual, expected)

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
            T.Unary(t.span, U.Not, t.at(1).true),
        )

        t = self.fake_document(
            """\
            +1
            |^1
            """
        )

        self.assertAstEqual(
            t.body,
            T.Unary(t.span, U.Plus, t.at(1).num(1)),
        )

        t = self.fake_document(
            """\
            -1.05
            |^^^^1
            """
        )

        self.assertAstEqual(
            t.body,
            T.Unary(t.span, U.Negate, t.at(1).num(1.05)),
        )
