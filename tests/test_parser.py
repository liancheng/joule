from textwrap import dedent
from typing import Sequence

import parsy as P

from joule import ast as A
from joule.ast import BinaryOp as B
from joule.ast import UnaryOp as U
from joule.parsing2 import Parser, blank, comma, enclosed, lparen, rparen
from tests.dsl.fake_document import FakeFile

from . import ASTTestCase
from .dsl import arg, binary, bind, false, field, fixed_key, num, param, true


class TestParser(ASTTestCase):
    fake_uri = "file:///tmp/test.jsonnet"

    parser = Parser(fake_uri)

    def fake_file(self, source: str):
        return FakeFile(source, uri=self.fake_uri)

    def assertParsed(self, doc: FakeFile, parser: P.Parser, expected: A.AST):
        self.assertAstEqual(parser.parse(doc.source), expected)

    def test_blank(self):
        blank.parse(" \t # comment")
        blank.parse("\n\n // comment")
        blank.parse(
            dedent(
                """\
                /**
                 * comment
                 */
                """
            )
        )

    def test_id(self):
        t = self.fake_file("x")
        self.assertParsed(t, self.parser.var_id, A.Id.Var(t.location, "x"))
        self.assertParsed(t, self.parser.var_ref_id, A.Id.VarRef(t.location, "x"))
        self.assertParsed(t, self.parser.field_id, A.Id.Field(t.location, "x"))
        self.assertParsed(t, self.parser.field_ref_id, A.Id.FieldRef(t.location, "x"))
        self.assertParsed(t, self.parser.param_ref_id, A.Id.ParamRef(t.location, "x"))

    def test_bool(self):
        t = self.fake_file("true")
        self.assertParsed(t, self.parser.boolean, true(t.location))

        t = self.fake_file("false")
        self.assertParsed(t, self.parser.boolean, false(t.location))

    def test_misc(self):
        t = self.fake_file("$")
        self.assertParsed(t, self.parser.dollar, A.Dollar(t.location))

        t = self.fake_file("self")
        self.assertParsed(t, self.parser.self_, A.Self(t.location))

        t = self.fake_file("super")
        self.assertParsed(t, self.parser.super_, A.Super(t.location))

        t = self.fake_file("null")
        self.assertParsed(t, self.parser.null, A.Null(t.location))

    def assertNumParsed(self, raw: str, value: float):
        t = self.fake_file(raw)
        self.assertParsed(t, self.parser.num, num(t.location, value))

    def test_number(self):
        with self.subTest("decimal"):
            self.assertNumParsed("0", 0.0)
            self.assertNumParsed("-0.", -0.0)
            self.assertNumParsed("+0.", 0.0)

            self.assertNumParsed("1.", 1.0)
            self.assertNumParsed("-1.", -1.0)

            self.assertNumParsed("1.05", 1.05)
            self.assertNumParsed("-1.05", -1.05)
            self.assertNumParsed("+1.05", +1.05)

            self.assertNumParsed("1.e2", 100.0)
            self.assertNumParsed("1.e+2", 100.0)
            self.assertNumParsed("1.e-2", 0.01)

            self.assertNumParsed("1.25e2", 125.0)
            self.assertNumParsed("1.25e+2", 125.0)
            self.assertNumParsed("1.25e-2", 0.0125)

        with self.subTest("binary"):
            self.assertNumParsed("0b0", 0.0)
            self.assertNumParsed("0b1", 1.0)
            self.assertNumParsed("0B01", 1.0)
            self.assertNumParsed("0B101", 5.0)

        with self.subTest("octal"):
            self.assertNumParsed("0o0", 0.0)
            self.assertNumParsed("0o7", 7.0)
            self.assertNumParsed("0O10", 8.0)
            self.assertNumParsed("0O011", 9.0)

        with self.subTest("hexical"):
            self.assertNumParsed("0x0", 0.0)
            self.assertNumParsed("0xf", 15.0)
            self.assertNumParsed("0X10", 16.0)
            self.assertNumParsed("0X011", 17.0)

    def assertStringParsed(self, source: str, expected: str):
        t = self.fake_file(source)
        self.assertParsed(t, self.parser.string, A.Str(t.location, expected))

    def test_string(self):
        with self.subTest("single-line"):
            self.assertStringParsed('""', "")
            self.assertStringParsed("''", "")
            self.assertStringParsed("'\\u0041'", "A")
            self.assertStringParsed("'\\uD83D\\uDE00'", "😀")

        with self.subTest("verbatim single-line"):
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

    def test_enclosed(self):
        parser = enclosed(P.string("x"), lparen, comma, rparen)

        def check(raw: str, expected: Sequence[str]):
            _, obtained, _ = parser.parse(raw)
            self.assertSequenceEqual(obtained, expected)

        check("()", [])
        check("( )", [])
        check("( /**/ )", [])
        check("(x )", ["x"])
        check("( x)", ["x"])
        check("( x )", ["x"])
        check("(x,)", ["x"])
        check("(x, )", ["x"])
        check("(x ,)", ["x"])
        check("(x, x)", ["x", "x"])
        check("(x, x,)", ["x", "x"])
        check(
            dedent(
                """\
                (
                    x,
                    x,
                )"""
            ),
            ["x", "x"],
        )

    def test_unary(self):
        t = self.fake_file(
            dedent(
                """\
                !x
                 ^1"""
            )
        )

        self.assertParsed(
            t,
            self.parser.unary,
            A.Unary(t.location, U.Not, A.Id.VarRef(t.at(1), "x")),
        )

        t = self.fake_file(
            dedent(
                """\
                -+x
                 ^^1
                  ^2"""
            )
        )

        self.assertParsed(
            t,
            self.parser.unary,
            A.Unary(
                t.location,
                U.Negate,
                A.Unary(t.at(1), U.Plus, A.Id.VarRef(t.at(2), "x")),
            ),
        )

    def test_binary(self):
        t = self.fake_file(
            dedent(
                """\
                v1 + v2 * v3 < v4 || v5 in v6 == v7
                ^^1  ^^2  ^^3  ^^4   ^^5   ^^6   ^^7
                """
            )
        )

        v1 = A.Id.VarRef(t.at(1), "v1")
        v2 = A.Id.VarRef(t.at(2), "v2")
        v3 = A.Id.VarRef(t.at(3), "v3")
        v4 = A.Id.VarRef(t.at(4), "v4")
        v5 = A.Id.VarRef(t.at(5), "v5")
        v6 = A.Id.VarRef(t.at(6), "v6")
        v7 = A.Id.VarRef(t.at(7), "v7")

        plus_lhs = v1
        plus_rhs = binary(B.Multiply, v2, v3)

        lt_lhs = binary(B.Plus, plus_lhs, plus_rhs)
        lt_rhs = v4

        eq_lhs = binary(B.In, v5, v6)
        eq_rhs = v7

        or_lhs = binary(B.LT, lt_lhs, lt_rhs)
        or_rhs = binary(B.Eq, eq_lhs, eq_rhs)

        self.assertParsed(t, self.parser.expr, binary(B.Or, or_lhs, or_rhs))

    def test_array(self):
        t = self.fake_file("[]")

        self.assertParsed(t, self.parser.array, A.Array(t.location, []))

        t = self.fake_file(
            dedent(
                """\
                [1, 2,]
                 ^1 ^2"""
            )
        )

        self.assertParsed(
            t,
            self.parser.array,
            A.Array(t.location, [num(t.at(1), 1), num(t.at(2), 2)]),
        )

    def test_bind_var(self):
        t = self.fake_file(
            dedent(
                """\
                x = 1
                ^1  ^2"""
            )
        )

        self.assertParsed(
            t,
            self.parser.bind,
            A.Bind(
                t.location,
                id=A.Id.Var(t.at(1), "x"),
                value=num(t.at(2), 1),
            ),
        )

    def test_bind_fn(self):
        t = self.fake_file(
            dedent(
                """\
                f(p) = p
                ^1^2   ^3
                 ^^^^^^^5"""
            )
        )

        self.assertParsed(
            t,
            self.parser.bind,
            A.Bind(
                t.location,
                A.Id.Var(t.at(1), "f"),
                A.Fn(
                    t.at(5),
                    params=[A.Param(t.at(2), id=A.Id.Var(t.at(2), "p"))],
                    body=A.Id.VarRef(t.at(3), "p"),
                ),
            ),
        )

    def test_param(self):
        t = self.fake_file(
            dedent(
                """\
                a = 1
                ^1  ^2
                """
            )
        )

        self.assertParsed(
            t,
            self.parser.param,
            param(
                A.Id.Var(t.at(1), "a"),
                default=num(t.at(2), 1),
            ),
        )

    def test_params(self):
        t = self.fake_file(
            dedent(
                """\
                (a = 1, b, c = 2)
                 ^1  ^2 ^3 ^4  ^5
                """
            )
        )

        self.assertSequenceEqual(
            self.parser.params.parse(t.source),
            [
                param(A.Id.Var(t.at(1), "a"), default=num(t.at(2), 1)),
                param(A.Id.Var(t.at(3), "b")),
                param(A.Id.Var(t.at(4), "c"), default=num(t.at(5), 2)),
            ],
        )

    def test_local(self):
        t = self.fake_file(
            dedent(
                """\
                local x = 1, y = 2; x
                      ^1  ^2 ^3  ^4 ^5"""
            )
        )

        self.assertParsed(
            t,
            self.parser.local,
            A.Local(
                t.location,
                binds=[
                    bind(A.Id.Var(t.at(1), "x"), num(t.at(2), 1)),
                    bind(A.Id.Var(t.at(3), "y"), num(t.at(4), 2)),
                ],
                body=A.Id.VarRef(t.at(5), "x"),
            ),
        )

    def test_fixed_field_key(self):
        t = self.fake_file("fixed")

        self.assertParsed(
            t,
            self.parser.field_key,
            A.FixedKey(t.location, A.Id.Field(t.location, "fixed")),
        )

        t = self.fake_file("'\\uD83D\\uDE00'")

        self.assertParsed(
            t,
            self.parser.field_key,
            A.FixedKey(t.location, A.Id.Field(t.location, "😀")),
        )

    def test_computed_field_key(self):
        t = self.fake_file(
            dedent(
                """\
                [x]
                 ^1"""
            )
        )

        self.assertParsed(
            t,
            self.parser.field_key,
            A.ComputedKey(t.location, A.Id.VarRef(t.at(1), "x")),
        )

    def test_field(self):
        for visibility in A.Visibility:
            for plus, inherited in zip(["", "+"], [False, True]):
                with self.subTest(f"visibility={visibility}, inherited={inherited}"):
                    t = self.fake_file(
                        dedent(
                            f"""\
                            f{plus}{visibility.value}
                            ^1
                                1
                                ^2"""
                        )
                    )

                    self.assertParsed(
                        t,
                        self.parser.field,
                        A.Field(
                            t.location,
                            key=A.FixedKey(t.at(1), A.Id.Field(t.at(1), "f")),
                            value=num(t.at(2), 1),
                            visibility=visibility,
                            inherited=inherited,
                        ),
                    )

    def test_field_fn(self):
        for visibility in A.Visibility:
            for plus, inherited in zip(["", "+"], [False, True]):
                with self.subTest(f"visibility={visibility}, inherited={inherited}"):
                    t = self.fake_file(
                        dedent(
                            f"""\
                            func(){plus}{visibility}
                            ^^^^1
                                ^2:
                                true
                                ^^^^3,:2"""
                        )
                    )

                    self.assertParsed(
                        t,
                        self.parser.field,
                        A.Field(
                            t.location,
                            key=fixed_key(t.at(1), "func"),
                            value=A.Fn(t.at(2), [], true(t.at(3))),
                            visibility=visibility,
                            inherited=inherited,
                        ),
                    )

    def test_import(self):
        for import_type in A.ImportType:
            with self.subTest(f"import_type={import_type}"):
                t = self.fake_file(
                    dedent(
                        f"""\
                        {import_type.value}
                            'file'
                            ^^^^^^1"""
                    )
                )

                self.assertParsed(
                    t,
                    self.parser.import_(import_type),
                    A.Import(
                        t.location,
                        import_type,
                        A.Importee.from_string(A.Str(t.at(1), "file")),
                    ),
                )

    def test_fn(self):
        t = self.fake_file(
            dedent(
                """\
                function() true
                           ^^^^1"""
            )
        )

        self.assertParsed(
            t,
            self.parser.function,
            A.Fn(t.location, [], true(t.at(1))),
        )

    def test_assert(self):
        t = self.fake_file(
            dedent(
                """\
                assert true
                       ^^^^1"""
            )
        )

        self.assertParsed(
            t,
            self.parser.assert_,
            A.Assert(t.location, true(t.at(1))),
        )

        t = self.fake_file(
            dedent(
                """\
                assert true: "never"
                       ^^^^1 ^^^^^^^2"""
            )
        )

        self.assertParsed(
            t,
            self.parser.assert_,
            A.Assert(t.location, true(t.at(1)), A.Str(t.at(2), "never")),
        )

        t = self.fake_file(
            dedent(
                """\
                assert true: "never"; false
                ^^^^^^^^^^^^^^^^^^^^1 ^^^^^4
                       ^^^^2 ^^^^^^^3"""
            )
        )

        self.assertParsed(
            t,
            self.parser.assert_expr,
            A.AssertExpr(
                t.location,
                A.Assert(
                    t.at(1),
                    condition=true(t.at(2)),
                    message=A.Str(
                        t.at(3),
                        "never",
                    ),
                ),
                false(t.at(4)),
            ),
        )

    def test_document(self):
        t = self.fake_file("true")
        self.assertParsed(
            t,
            self.parser.document,
            A.Document(t.location, true(t.location)),
        )

    def test_list_comp(self):
        t = self.fake_file(
            dedent(
                """\
                [i for i in x if true]
                   ^^^^^^^^^^1^^^^^^^2
                 ^3    ^4   ^5   ^^^^6"""
            )
        )

        i = A.Id.Var(t.at(4), "i")
        i_ref = A.Id.VarRef(t.at(3), "i")
        x = A.Id.VarRef(t.at(5), "x")

        self.assertParsed(
            t,
            self.parser.list_comp,
            A.ListComp(
                t.location,
                expr=i_ref,
                for_spec=A.ForSpec(t.at(1), id=i, source=x),
                comp_spec=[A.IfSpec(t.at(2), true(t.at(6)))],
            ),
        )

    def test_call(self):
        t = self.fake_file(
            dedent(
                """\
                func(1, p = 2)
                ^^^^1^2 ^^^^^3
                        ^4  ^5"""
            )
        )

        self.assertParsed(
            t,
            self.parser.expr,
            A.Call(
                t.location,
                callee=A.Id.VarRef(t.at(1), "func"),
                args=[
                    arg(num(t.at(2), 1)),
                    arg(num(t.at(5), 2), A.Id.ParamRef(t.at(4), "p")),
                ],
            ),
        )

    def test_slice(self):
        t = self.fake_file(
            dedent(
                """\
                arr[0 : 10 : 2]
                ^^^1^2  ^^3  ^4"""
            )
        )

        self.assertParsed(
            t,
            self.parser.expr,
            A.Slice(
                t.location,
                array=A.Id.VarRef(t.at(1), "arr"),
                begin=num(t.at(2), 0),
                end=num(t.at(3), 10),
                step=num(t.at(4), 2),
            ),
        )

        t = self.fake_file(
            dedent(
                """\
                arr[0 : 10]
                ^^^1^2  ^^3"""
            )
        )

        arr = A.Id.VarRef(t.at(1), "arr")
        begin = num(t.at(2), 0)
        end = num(t.at(3), 10)

        self.assertParsed(
            t,
            self.parser.expr,
            A.Slice(t.location, arr, begin, end),
        )

        t = self.fake_file(
            dedent(
                """\
                arr[0]
                ^^^1^2"""
            )
        )

        arr = A.Id.VarRef(t.at(1), "arr")
        begin = num(t.at(2), 0)

        self.assertParsed(
            t,
            self.parser.expr,
            A.Slice(t.location, arr, begin),
        )

        t = self.fake_file(
            dedent(
                """\
                obj["f"]
                ^^^1^^^2"""
            )
        )

        obj = A.Id.VarRef(t.at(1), "obj")
        begin = A.Str(t.at(2), "f")

        self.assertParsed(
            t,
            self.parser.expr,
            A.Slice(t.location, array=obj, begin=begin),
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

        self.assertParsed(
            t,
            self.parser.expr,
            A.FieldAccess(t.location, A.FieldAccess(t.at(1), obj, f1), f2),
        )

    def test_postfix(self):
        t = self.fake_file(
            dedent(
                """\
                obj.f1(p1)[0] {}
                ^^^^^^^^^^1
                ^^^^^^^^^^^^^2
                ^^^^^^3
                ^^^4^^5^^6 ^7 ^^8"""
            )
        )

        obj = A.Id.VarRef(t.at(4), "obj")
        f1 = A.Id.FieldRef(t.at(5), "f1")
        p1 = A.Id.VarRef(t.at(6), "p1")
        begin = num(t.at(7), 0)
        empty = A.Object(t.at(8))

        self.assertParsed(
            t,
            self.parser.expr,
            binary(
                B.Plus,
                A.Slice(
                    t.at(2),
                    A.Call(
                        t.at(1),
                        A.FieldAccess(t.at(3), obj, f1),
                        [arg(p1)],
                    ),
                    begin,
                ),
                empty,
            ),
        )

    def test_if(self):
        t = self.fake_file(
            dedent(
                """\
                if x then y else z
                   ^1     ^2     ^3"""
            )
        )

        x = A.Id.VarRef(t.at(1), "x")
        y = A.Id.VarRef(t.at(2), "y")
        z = A.Id.VarRef(t.at(3), "z")

        self.assertParsed(t, self.parser.if_, A.If(t.location, x, y, z))

        t = self.fake_file(
            dedent(
                """\
                if x then y
                   ^1     ^2"""
            )
        )

        self.assertParsed(t, self.parser.if_, A.If(t.location, x, y))

    def test_paren(self):
        t = self.fake_file(
            dedent(
                """\
                x * (y + z)
                ^1   ^2  ^3"""
            )
        )

        x = A.Id.VarRef(t.at(1), "x")
        y = A.Id.VarRef(t.at(2), "y")
        z = A.Id.VarRef(t.at(3), "z")

        self.assertParsed(
            t,
            self.parser.expr,
            A.Binary(
                t.location,
                A.BinaryOp.Multiply,
                x,
                binary(A.BinaryOp.Plus, y, z),
            ),
        )

    def test_object(self):
        with self.subTest("empty"):
            t = self.fake_file("{}")

            self.assertParsed(
                t,
                self.parser.object,
                A.Object(t.location),
            )

        with self.subTest("assert"):
            t = self.fake_file(
                dedent(
                    """\
                    { assert true }
                      ^1:    ^^^^:1,2"""
                )
            )

            self.assertParsed(
                t,
                self.parser.object,
                A.Object(
                    t.location,
                    asserts=[A.Assert(t.at(1), true(t.at(2)))],
                ),
            )

        with self.subTest("object local"):
            t = self.fake_file(
                dedent(
                    """\
                    { local v = 1, }
                            ^^^^^1
                            ^2  ^3"""
                )
            )

            v = A.Id.Var(t.at(2), "v")

            self.assertParsed(
                t,
                self.parser.object,
                A.Object(t.location, binds=[bind(v, num(t.at(3), 1))]),
            )

        with self.subTest("object local before field"):
            t = self.fake_file(
                dedent(
                    """\
                    { local v = 1, f: v }
                            ^^^^^1
                            ^2  ^3 ^4 ^5"""
                )
            )

            v = A.Id.Var(t.at(2), "v")
            f = fixed_key(t.at(4), "f")
            v_ref = A.Id.VarRef(t.at(5), "v")

            self.assertParsed(
                t,
                self.parser.object,
                A.Object(
                    t.location,
                    binds=[bind(v, num(t.at(3), 1))],
                    fields=[field(f, v_ref)],
                ),
            )

        with self.subTest("object local after field"):
            t = self.fake_file(
                dedent(
                    """\
                    { f: v, local v = 1, }
                      ^1 ^2       ^^^^^3
                                  ^4  ^5"""
                )
            )

            f = fixed_key(t.at(1), "f")
            v_ref = A.Id.VarRef(t.at(2), "v")
            v = A.Id.Var(t.at(4), "v")

            self.assertParsed(
                t,
                self.parser.object,
                A.Object(
                    t.location,
                    binds=[bind(v, num(t.at(5), 1))],
                    fields=[field(f, v_ref)],
                ),
            )

    def test_obj_comp(self):
        t = self.fake_file(
            dedent(
                """\
                {
                    local x = 1,
                          ^1  ^2
                    ['f' + y]:: x + y,
                     ^^^3  ^4   ^5  ^6
                    ^^^^^^^^^7
                    assert true,
                    ^8:    ^^^^:8,9
                    for x in [2, 3]
                        ^10   ^11^12
                    ^13:     ^^^^^^:13,14
                    if x + y < 4
                       ^15 ^16 ^17
                    ^^^^^^^^^^^^18
                }"""
            )
        )

        key = A.ComputedKey(
            t.at(7),
            expr=binary(
                A.BinaryOp.Plus,
                A.Str(t.at(3), "f"),
                A.Id.VarRef(t.at(4), "y"),
            ),
        )

        value = binary(
            A.BinaryOp.Plus,
            A.Id.VarRef(t.at(5), "x"),
            A.Id.VarRef(t.at(6), "y"),
        )

        array = A.Array(
            t.at(14),
            values=[
                num(t.at(11), 2),
                num(t.at(12), 3),
            ],
        )

        for_spec = A.ForSpec(
            t.at(13),
            id=A.Id.Var(t.at(10), "x"),
            source=array,
        )

        if_spec = A.IfSpec(
            t.at(18),
            condition=(
                binary(
                    A.BinaryOp.LT,
                    binary(
                        A.BinaryOp.Plus,
                        A.Id.VarRef(t.at(15), "x"),
                        A.Id.VarRef(t.at(16), "y"),
                    ),
                    num(t.at(17), 4),
                )
            ),
        )

        self.assertParsed(
            t,
            self.parser.object,
            A.ObjComp(
                location=t.location,
                field=field(key, value, A.Visibility.Hidden),
                binds=[
                    bind(A.Id.Var(t.at(1), "x"), num(t.at(2), 1)),
                ],
                asserts=[A.Assert(t.at(8), condition=true(t.at(9)))],
                for_spec=for_spec,
                comp_spec=[if_spec],
            ),
        )

    def test_doc(self):
        self.parser.document.parse(
            dedent(
                """\
                local refactor = import './refactor.libsonnet';
                local utils = import './utils.libsonnet';

                {
                  titleMapping: {
                    alertgroups: 'alertGroups',
                    alertlist: 'alertList',
                    annotationslist: 'annotationsList',
                    barchart: 'barChart',
                    bargauge: 'barGauge',
                    dashboardlist: 'dashboardList',
                    nodegraph: 'nodeGraph',
                    piechart: 'pieChart',
                    statetimeline: 'stateTimeline',
                    statushistory: 'statusHistory',
                    timeseries: 'timeSeries',
                    xychart: 'xyChart',
                  },
                }
                """
            )
        )
