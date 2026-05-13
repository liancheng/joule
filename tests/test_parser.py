from itertools import product

from joule import trees as T
from joule.trees import BinaryOp as B
from joule.trees import UnaryOp as U
from joule.trees import Visibility as V

from . import ParsingTestCase
from .dsl import arg, assert_expr, bind, field, get_field


class TestParser(ParsingTestCase):
    def test_boolean(self):
        t = self.fake_file("true")
        self.parse(t, "boolean").expect(t.span.true)

        t = self.fake_file("false")
        self.parse(t, "boolean").expect(t.span.false)

    def test_id(self):
        t = self.fake_file("int")
        self.parse(t, "field_id").expect(t.span.field("int"))
        self.parse(t, "field_ref_id").expect(t.span.field_ref("int"))
        self.parse(t, "param_ref_id").expect(t.span.param_ref("int"))
        self.parse(t, "var_id").expect(t.span.var("int"))
        self.parse(t, "var_ref_id").expect(t.span.var_ref("int"))

    def test_misc(self):
        t = self.fake_file("$")
        self.parse(t, "dollar").expect(t.span.dollar)

        t = self.fake_file("null")
        self.parse(t, "null").expect(t.span.null)

        t = self.fake_file("self")
        self.parse(t, "self").expect(t.span.self)

        t = self.fake_file("super")
        self.parse(t, "super").expect(t.span.super)

    def assertNumParsed(self, raw: str, value: float | int):
        t = self.fake_file(raw)
        self.parse(t, "number").expect(t.span.num(value))

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
        self.parse(t, "string").expect(t.span.str(expected))

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

        for maybe_dash in ["", "-"]:
            maybe_newline = "\n" if maybe_dash == "" else ""
            with self.subTest(f"text block: with_newline={maybe_dash == ''}"):
                self.assertStringParsed(
                    f"""\
                    |||{maybe_dash}
                    |||
                    """,
                    maybe_newline,
                )

                self.assertStringParsed(
                    f"""\
                    |||{maybe_dash}
                        a
                            b
                    |||
                    """,
                    f"a\n    b{maybe_newline}",
                )

                self.assertStringParsed(
                    f"""\
                    |||{maybe_dash}
                        \\uD83D\\uDE00
                    |||
                    """,
                    f"😀{maybe_newline}",
                )

                self.assertStringParsed(
                    f"""\
                    @|||{maybe_dash}
                        \\uD83D\\uDE00
                    |||
                    """,
                    f"\\uD83D\\uDE00{maybe_newline}",
                )

    def test_field_access(self):
        t = self.fake_file(
            """\
            obj.f1.f2
            ^^^^^^1
            ^^^2^^3^^4
            """
        )

        self.parse(t, "postfix").expect(
            get_field(
                get_field(
                    t.at(2).var_ref("obj"),
                    t.at(3).field_ref("f1"),
                ),
                t.at(4).field_ref("f2"),
            ),
        )

    def test_unary(self):
        with self.subTest("0 operators"):
            t = self.fake_file("true")
            self.parse(t, "unary").expect(t.span.true)

        with self.subTest("1 operator"):
            t = self.fake_file(
                """\
                !true
                |^^^^1
                """
            )

            self.parse(t, "unary").expect(
                T.Unary(t.span, U.Not, t.at(1).true),
            )

    def test_binary_op(self):
        for op in [B.Multiply, B.Divide, B.Modulus]:
            t = self.fake_file(op.value)
            self.parse(t, "mul_op").expect(op)

        for op in [B.Eq, B.NotEq]:
            t = self.fake_file(op.value)
            self.parse(t, "eq_op").expect(op)

    def test_mul_expr(self):
        t = self.fake_file(
            """\
            1 * 2
            ^1  ^2
            """
        )

        self.parse(t, "mul_expr").expect(
            B.Multiply(
                t.at(1).num(1),
                t.at(2).num(2),
            )
        )

    def test_plus_expr(self):
        t = self.fake_file(
            """\
            1 + 2
            ^1  ^2
            """
        )

        self.parse(t, "plus_expr").expect(
            B.Plus(
                t.at(1).num(1),
                t.at(2).num(2),
            )
        )

    def test_binary(self):
        t = self.fake_file(
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

        self.parse(t, "expr").expect(expr)

    def test_slice_spec(self):
        with self.subTest("start : stop : step"):
            t = self.fake_file(
                """\
                0 : 10 : 2
                ^1  ^^2  ^3
                """
            )

            self.parse(t, "start_stop_step").expect(
                (
                    t.at(1).num(0),
                    t.at(2).num(10),
                    t.at(3).num(2),
                )
            )

        with self.subTest("start : stop"):
            t = self.fake_file(
                """\
                0 : 10
                ^1  ^^2
                """
            )

            self.parse(t, "start_stop_step").expect(
                (
                    t.at(1).num(0),
                    t.at(2).num(10),
                    None,
                ),
            )

        with self.subTest("start : stop :"):
            t = self.fake_file(
                """\
                0 : 10 :
                ^1  ^^2
                """
            )

            self.parse(t, "start_stop_step").expect(
                (
                    t.at(1).num(0),
                    t.at(2).num(10),
                    None,
                ),
            )

        with self.subTest("start : : step"):
            t = self.fake_file(
                """\
                0 : : 2
                ^1    ^2
                """
            )

            self.parse(t, "start_stop_step").expect(
                (
                    t.at(1).num(0),
                    None,
                    t.at(2).num(2),
                ),
            )

        with self.subTest(": stop : step"):
            t = self.fake_file(
                """\
                : 10 : 2
                | ^^1  ^2
                """
            )

            self.parse(t, "start_stop_step").expect(
                (
                    None,
                    t.at(1).num(10),
                    t.at(2).num(2),
                ),
            )

        with self.subTest("start"):
            t = self.fake_file("0")

            self.parse(t, "start_stop_step").expect(
                (
                    t.span.num(0),
                    None,
                    None,
                ),
            )

        with self.subTest("start :"):
            t = self.fake_file(
                """\
                0 :
                ^1
                """
            )

            self.parse(t, "start_stop_step").expect(
                (
                    t.at(1).num(0),
                    None,
                    None,
                ),
            )

        with self.subTest("start : :"):
            t = self.fake_file(
                """\
                0 : :
                ^1
                """
            )

            self.parse(t, "start_stop_step").expect(
                (
                    t.at(1).num(0),
                    None,
                    None,
                ),
            )

        with self.subTest(": stop"):
            t = self.fake_file(
                """\
                : 10
                | ^^1
                """
            )

            self.parse(t, "start_stop_step").expect(
                (
                    None,
                    t.at(1).num(10),
                    None,
                ),
            )

        with self.subTest(": stop :"):
            t = self.fake_file(
                """\
                : 10 :
                | ^^1
                """
            )

            self.parse(t, "start_stop_step").expect(
                (
                    None,
                    t.at(1).num(10),
                    None,
                ),
            )

        with self.subTest(": : step"):
            t = self.fake_file(
                """\
                : : 2
                |   ^1
                """
            )

            self.parse(t, "start_stop_step").expect(
                (
                    None,
                    None,
                    t.at(1).num(2),
                ),
            )

        with self.subTest(": :"):
            t = self.fake_file(": :")

            self.parse(t, "start_stop_step").expect(
                (None, None, None),
            )

    def test_field_index(self):
        t = self.fake_file(
            """\
            obj["f"]
            ^^^1^^^2
            """
        )

        self.parse(t, "postfix").expect(
            T.Slice(
                t.span,
                t.at(1).var_ref("obj"),
                t.at(2).str("f"),
            ),
        )

    def test_conditional(self):
        with self.subTest("with alternative"):
            t = self.fake_file(
                """\
                if x then y else z
                |  ^1     ^2     ^3
                """
            )

            self.parse(t, "conditional").expect(
                T.If(
                    t.span,
                    t.at(1).var_ref("x"),
                    t.at(2).var_ref("y"),
                    t.at(3).var_ref("z"),
                ),
            )

        with self.subTest("without alternative"):
            t = self.fake_file(
                """\
                if x then y
                |  ^1     ^2
                """
            )

            self.parse(t, "conditional").expect(
                T.If(
                    t.span,
                    t.at(1).var_ref("x"),
                    t.at(2).var_ref("y"),
                ),
            )

    def test_assert(self):
        t = self.fake_file(
            """\
            assert true
            |      ^^^^1
            """
        )

        self.parse(t, "assertion").expect(
            T.Assert(t.span, t.at(1).true),
        )

        t = self.fake_file(
            """\
            assert true: "never"
            |      ^^^^1 ^^^^^^^2
            """
        )

        self.parse(t, "assertion").expect(
            T.Assert(t.span, t.at(1).true, t.at(2).str("never")),
        )

    def test_assert_expr(self):
        t = self.fake_file(
            """\
            assert true: "never"; false
            ^^^^^^^^^^^^^^^^^^^^1 ^^^^^4
            |      ^^^^2 ^^^^^^^3
            """
        )

        self.parse(t, "expr").expect(
            assert_expr(
                T.Assert(
                    t.at(1),
                    condition=t.at(2).true,
                    message=t.at(3).str("never"),
                ),
                t.at(4).false,
            ),
        )

    def test_import(self):
        rules = ["import_file", "import_str", "import_bin"]
        for import_type, rule in zip(T.ImportType, rules):
            with self.subTest(f"import_type={import_type}"):
                t = self.fake_file(
                    f"""\
                    {import_type}
                        'file'
                    |   ^^^^^^1
                    """
                )

                self.parse(t, rule).expect(
                    T.Import(
                        t.span,
                        import_type,
                        t.at(1).importee("file"),
                    ),
                )

    def test_array(self):
        t = self.fake_file("[]")

        self.parse(t, "array").expect(
            t.span.array(),
        )

        for comma in [",", ""]:
            t = self.fake_file(
                f"""\
                [1{comma}]
                |^1
                """
            )

            self.parse(t, "array").expect(
                t.span.array(t.at(1).num(1)),
            )

            t = self.fake_file(
                f"""\
                [1, 2{comma}]
                |^1 ^2
                """
            )

            self.parse(t, "array").expect(
                t.span.array(t.at(1).num(1), t.at(2).num(2)),
            )

    def test_bind_var(self):
        t = self.fake_file(
            """\
            x = 1
            ^1  ^2
            """
        )

        self.parse(t, "bind").expect(
            bind(
                t.at(1).var("x"),
                t.at(2).num(1),
            ),
        )

    def test_bind_fn(self):
        t = self.fake_file(
            """\
            f(p) = p
            ^1^2   ^3
            |^^^^^^^5
            """
        )

        self.parse(t, "bind").expect(
            bind(
                t.at(1).var("f"),
                T.Fn(
                    t.at(5),
                    params=[t.at(2).param("p")],
                    body=t.at(3).var_ref("p"),
                ),
            ),
        )

    def test_local(self):
        t = self.fake_file(
            """\
            local x = 1, y = 2; x
            |     ^1  ^2 ^3  ^4 ^5"""
        )

        self.parse(t, "local_expr").expect(
            T.Local(
                t.span,
                binds=[
                    bind(t.at(1).var("x"), t.at(2).num(1)),
                    bind(t.at(3).var("y"), t.at(4).num(2)),
                ],
                body=t.at(5).var_ref("x"),
            ),
        )

    def test_fn(self):
        with self.subTest("no parameters"):
            t = self.fake_file(
                """\
                function() true
                |          ^^^^1
                """
            )

            self.parse(t, "anonymous_function").expect(T.Fn(t.span, [], t.at(1).true))

        with self.subTest("parameters with a default value"):
            t = self.fake_file(
                """\
                function(x = 1, y,) x + y
                |        ^1  ^2 ^3  ^4  ^5
                """
            )

            x = t.at(1).param("x", t.at(2).num(1))
            y = t.at(3).param("y")
            x_ref = t.at(4).var_ref("x")
            y_ref = t.at(5).var_ref("y")

            self.parse(t, "anonymous_function").expect(
                T.Fn(t.span, [x, y], B.Plus(x_ref, y_ref))
            )

    def test_list_comp(self):
        t = self.fake_file(
            """\
            [i for i in x if true]
            |  ^^^^^^^^^^1^^^^^^^2
            |^3    ^4   ^5   ^^^^6
            """
        )

        i = t.at(4).var("i")
        i_ref = t.at(3).var_ref("i")
        x = t.at(5).var_ref("x")

        for_ = T.ForSpec(t.at(1), id=i, source=x)
        if_ = T.IfSpec(t.at(2), t.at(6).true)

        self.parse(t, "list_comp").expect(T.ListComp(t.span, i_ref, for_, [if_]))

    def test_paren(self):
        t = self.fake_file(
            """\
            x * (y + z)
            ^1   ^2  ^3
            |   ^^^^^^^4
            """
        )

        x = t.at(1).var_ref("x")
        y = t.at(2).var_ref("y")
        z = t.at(3).var_ref("z")

        self.parse(t, "expr").expect(B.Multiply(x, T.Paren(t.at(4), B.Plus(y, z))))

    def test_fixed_key(self):
        t = self.fake_file("f")
        self.parse(t, "fixed_key").expect(t.span.fixed_key("f"))

        t = self.fake_file("'f'")
        self.parse(t, "fixed_key").expect(t.span.fixed_key("f"))

    def test_computed_key(self):
        t = self.fake_file(
            """\
            [true]
            |^^^^1
            """
        )

        self.parse(t, "computed_key").expect(T.ComputedKey(t.span, t.at(1).true))

    def test_visibility(self):
        for vis in T.Visibility:
            t = self.fake_file(vis.value)
            self.parse(t, "visibility").expect(vis)

    def test_field(self):
        for maybe_plus, visibility in product(["", "+"], T.Visibility):
            field_sep = f"{maybe_plus}{visibility}"
            inherited = maybe_plus == "+"

            with self.subTest(field_sep):
                t = self.fake_file(
                    f"""\
                    f{field_sep}
                    ^1
                        true
                    |   ^^^^2
                    """
                )

                self.parse(t, "field").expect(
                    field(
                        key=t.at(1).fixed_key("f"),
                        value=t.at(2).true,
                        inherited=inherited,
                        visibility=visibility,
                    )
                )

    def test_fn_field(self):
        for maybe_plus, visibility in product(["", "+"], T.Visibility):
            field_sep = f"{maybe_plus}{visibility}"
            inherited = maybe_plus == "+"

            with self.subTest(field_sep):
                t = self.fake_file(
                    f"""\
                    func(a){field_sep}
                    ^^^^1^2
                        ^3:
                        a
                    |   ^:3,4
                    """
                )

                self.parse(t, "field").expect(
                    field(
                        key=t.at(1).fixed_key("func"),
                        value=T.Fn(
                            t.at(3),
                            params=[(t.at(2).param("a"))],
                            body=t.at(4).var_ref("a"),
                        ),
                        inherited=inherited,
                        visibility=visibility,
                    )
                )

    def test_object(self):
        with self.subTest("empty"):
            t = self.fake_file("{}")
            self.parse(t, "object").expect(T.Object(t.span))

        with self.subTest("assert"):
            t = self.fake_file(
                """\
                { assert true }
                | ^1:    ^^^^:1,2
                """
            )

            assert_ = T.Assert(t.at(1), t.at(2).true)
            self.parse(t, "object").expect(
                T.Object(t.span, asserts=[assert_]),
            )

        with self.subTest("object local"):
            t = self.fake_file(
                """\
                { local v = 1, }
                |       ^^^^^1
                |       ^2  ^3"""
            )

            v = t.at(2).var("v")
            bind_v = bind(v, t.at(3).num(1))

            self.parse(t, "object").expect(
                T.Object(t.span, binds=[bind_v]),
            )

        with self.subTest("object local before field"):
            t = self.fake_file(
                """\
                { local v = 1, f: v }
                |       ^^^^^1
                |       ^2  ^3 ^4 ^5
                """
            )

            v = t.at(2).var("v")
            f = t.at(4).fixed_key("f")
            v_ref = t.at(5).var_ref("v")
            bind_v = bind(v, t.at(3).num(1))
            field_f = field(f, v_ref)

            self.parse(t, "object").expect(
                T.Object(
                    t.span,
                    binds=[bind_v],
                    fields=[field_f],
                )
            )

        with self.subTest("object local after field"):
            t = self.fake_file(
                """\
                { f: v, local v = 1, }
                | ^1 ^2       ^^^^^3
                |             ^4  ^5
                """
            )

            f = t.at(1).fixed_key("f")
            v = t.at(4).var("v")
            v_ref = t.at(2).var_ref("v")
            bind_v = bind(v, t.at(5).num(1))
            field_f = field(f, v_ref)

            self.parse(t, "object").expect(
                T.Object(t.span, binds=[bind_v], fields=[field_f]),
            )

        with self.subTest("function field"):
            t = self.fake_file(
                """\
                {
                    func(): true
                    ^^^^1
                |       ^2: ^^^^:2,3
                }
                """
            )

            func = field(
                t.at(1).fixed_key("func"),
                T.Fn(t.at(2), params=[], body=t.at(3).true),
            )

            self.parse(t, "object").expect(
                T.Object(t.span, fields=[func]),
            )

    def test_obj_comp(self):
        t = self.fake_file(
            """\
            {
                local x = 1,
            |         ^1  ^2
                ['f' + y]:: x + y,
            |    ^^^3  ^4   ^5  ^6
                ^^^^^^^^^7
                assert true,
                ^8:    ^^^^:8,9
                for x in [2, 3]
            |       ^10   ^11^12
                ^13:     ^^^^^^:13,14
                if x + y < 4
            |      ^15 ^16 ^17
                ^^^^^^^^^^^^18
            }
            """
        )

        computed_field = field(
            key=T.ComputedKey(
                t.at(7),
                B.Plus(
                    t.at(3).str("f"),
                    t.at(4).var_ref("y"),
                ),
            ),
            value=B.Plus(
                t.at(5).var_ref("x"),
                t.at(6).var_ref("y"),
            ),
            visibility=V.Hidden,
        )

        for_spec = T.ForSpec(
            t.at(13),
            id=t.at(10).var("x"),
            source=t.at(14).array(
                t.at(11).num(2),
                t.at(12).num(3),
            ),
        )

        if_spec = T.IfSpec(
            t.at(18),
            condition=B.LT(
                B.Plus(
                    t.at(15).var_ref("x"),
                    t.at(16).var_ref("y"),
                ),
                t.at(17).num(4),
            ),
        )

        self.parse(t, "object").expect(
            T.ObjComp(
                t.span,
                field=computed_field,
                binds=[bind(t.at(1).var("x"), t.at(2).num(1))],
                asserts=[T.Assert(t.at(8), t.at(9).true)],
                for_spec=for_spec,
                extra_specs=[if_spec],
            )
        )

    def test_call(self):
        t = self.fake_file(
            """\
            func(1, p = 2)
            ^^^^1^2 ^^^^^3
            |       ^4  ^5
            """
        )

        self.parse(t, "postfix").expect(
            T.Call(
                t.span,
                callee=t.at(1).var_ref("func"),
                args=[
                    arg(t.at(2).num(1)),
                    arg(t.at(5).num(2), id=t.at(4).param_ref("p")),
                ],
            )
        )

    def test_extend(self):
        t = self.fake_file(
            """\
            x {}
            ^1^^2
            """
        )

        self.parse(t, "expr").expect(
            B.Plus(
                t.at(1).var_ref("x"),
                T.Object(t.at(2)),
            ),
        )

        t = self.fake_file(
            """\
            local p = {};
            |     ^1  ^^2
            function() p {}
            ^3:        ^4^^:3,5
            """
        )

        self.parse(t, "expr").expect(
            T.Local(
                t.span,
                binds=[bind(t.at(1).var("p"), T.Object(t.at(2)))],
                body=T.Fn(
                    t.at(3),
                    params=[],
                    body=B.Plus(
                        t.at(4).var_ref("p"),
                        T.Object(t.at(5)),
                    ),
                ),
            ),
        )
