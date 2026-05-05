from textwrap import dedent
from typing import Any

from joule import ast as A
from joule.parser.jsonnet import parse_jsonnet

from . import AstTestCase
from .dsl import false, num, true
from .dsl.fake_document import FakeFile


class TestParser(AstTestCase):
    fake_uri = "file:///tmp/test.jsonnet"

    def fake_file(self, source: str):
        return FakeFile(source, uri=self.fake_uri)

    def assertParsed(self, doc: FakeFile, rule: str, expected: Any):
        self.assertEqual(parse_jsonnet(doc.uri, doc.text, rule), expected)

    def assertAstParsed(self, doc: FakeFile, rule: str, expected: A.AST):
        self.assertAstEqual(
            obtained=parse_jsonnet(doc.uri, doc.text, rule),
            expected=expected,
        )

    def test_null(self):
        t = self.fake_file("null")
        self.assertAstParsed(t, "null", A.Null(t.anchor))

    def test_boolean(self):
        t = self.fake_file("true")
        self.assertAstParsed(t, "boolean", true(t.anchor))

        t = self.fake_file("false")
        self.assertAstParsed(t, "boolean", false(t.anchor))

    def test_id(self):
        t = self.fake_file("x")
        self.assertAstParsed(t, "field_id", A.Id.Field(t.anchor, "x"))
        self.assertAstParsed(t, "field_ref_id", A.Id.FieldRef(t.anchor, "x"))
        self.assertAstParsed(t, "param_ref_id", A.Id.ParamRef(t.anchor, "x"))
        self.assertAstParsed(t, "var_id", A.Id.Var(t.anchor, "x"))
        self.assertAstParsed(t, "var_ref_id", A.Id.VarRef(t.anchor, "x"))

    def test_misc(self):
        t = self.fake_file("$")
        self.assertAstParsed(t, "dollar", A.Dollar(t.anchor))

        t = self.fake_file("null")
        self.assertAstParsed(t, "null", A.Null(t.anchor))

        t = self.fake_file("self")
        self.assertAstParsed(t, "self", A.Self(t.anchor))

        t = self.fake_file("super")
        self.assertAstParsed(t, "super", A.Super(t.anchor))

    def assertNumParsed(self, raw: str, value: float | int):
        t = self.fake_file(raw)
        self.assertAstParsed(t, "number", num(t.anchor, value))

    def test_number(self):
        with self.subTest("decimal"):
            self.assertNumParsed("0", 0)
            self.assertNumParsed("-0.", -0.0)
            self.assertNumParsed("+0.", 0)

            self.assertNumParsed("1.", 1)
            self.assertNumParsed("-1.", -1)

            self.assertNumParsed("1.05", 1.05)
            self.assertNumParsed("-1.05", -1.05)
            self.assertNumParsed("+1.05", +1.05)

            self.assertNumParsed("1.e2", 100)
            self.assertNumParsed("1.e+2", 100)
            self.assertNumParsed("1.e-2", 0.01)

            self.assertNumParsed("1.25e2", 125)
            self.assertNumParsed("1.25e+2", 125)
            self.assertNumParsed("1.25e-2", 0.0125)

        with self.subTest("binary"):
            self.assertNumParsed("0b0", 0)
            self.assertNumParsed("0b1", 1)
            self.assertNumParsed("0B01", 1)
            self.assertNumParsed("0B101", 5)

        with self.subTest("octal"):
            self.assertNumParsed("0o0", 0)
            self.assertNumParsed("0o7", 7)
            self.assertNumParsed("0O10", 8)
            self.assertNumParsed("0O011", 9)

        with self.subTest("hexical"):
            self.assertNumParsed("0x0", 0)
            self.assertNumParsed("0xf", 15)
            self.assertNumParsed("0X10", 16)
            self.assertNumParsed("0X011", 17)

    def assertStringParsed(self, source: str, expected: str):
        t = self.fake_file(source)
        self.assertAstParsed(t, "string", A.Str(t.anchor, expected))

    def test_string(self):
        with self.subTest("inline"):
            self.assertStringParsed('""', "")
            self.assertStringParsed("''", "")
            self.assertStringParsed('"\\n"', "\n")
            self.assertStringParsed("'\\n'", "\n")
            self.assertStringParsed("'\\u0041'", "A")
            self.assertStringParsed("'\\uD83D\\uDE00'", "😀")

        with self.subTest("verbatim inline"):
            self.assertStringParsed('@""""', '"')
            self.assertStringParsed("@''''", "'")
            self.assertStringParsed('@"\\n"', "\\n")
            self.assertStringParsed("@'\\n'", "\\n")
            self.assertStringParsed("@'\\u0041'", "\\u0041")
            self.assertStringParsed("@'\\uD83D\\uDE00'", "\\uD83D\\uDE00")

        for dash, newline in zip(["", "-"], ["\n", ""]):
            with self.subTest(f"text block: with_newline={len(newline) > 0}"):
                self.assertStringParsed(
                    dedent(
                        f"""\
                        |||{dash}
                        |||"""
                    ),
                    newline,
                )

                self.assertStringParsed(
                    dedent(
                        f"""\
                        |||{dash}
                            a
                                b
                        |||"""
                    ),
                    dedent(
                        f"""\
                        a
                            b{newline}"""
                    ),
                )

                self.assertStringParsed(
                    dedent(
                        f"""\
                        |||{dash}
                            \\uD83D\\uDE00
                        |||"""
                    ),
                    dedent(
                        f"""\
                        😀{newline}"""
                    ),
                )

                self.assertStringParsed(
                    dedent(
                        f"""\
                        @|||{dash}
                            \\uD83D\\uDE00
                        |||"""
                    ),
                    dedent(
                        f"""\
                        \\uD83D\\uDE00{newline}"""
                    ),
                )

    def test_field_access(self):
        t = self.fake_file(
            dedent(
                """\
                obj.f1.f2
                ^^^^^^1
                ^^^2^^3^^4"""
            )
        )

        obj = A.Id.VarRef(t.at(2), "obj")
        f1 = A.Id.FieldRef(t.at(3), "f1")
        f2 = A.Id.FieldRef(t.at(4), "f2")

        self.assertAstParsed(
            t,
            "postfix",
            A.FieldAccess(t.anchor, A.FieldAccess(t.at(1), obj, f1), f2),
        )

    def test_unary_op(self):
        for op in list(A.UnaryOp):
            t = self.fake_file(op.value)
            self.assertParsed(t, "unary_op", (t.anchor.span, op))

    def test_unary(self):
        with self.subTest("0 operators"):
            t = self.fake_file("true")
            self.assertAstParsed(t, "unary", true(t.anchor))

        with self.subTest("1 operator"):
            t = self.fake_file(
                dedent(
                    """\
                    !true
                     ^^^^1"""
                )
            )

            self.assertAstParsed(
                t,
                "unary",
                A.Unary(t.anchor, A.UnaryOp.Not, true(t.at(1))),
            )
