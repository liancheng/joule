import unittest
from textwrap import dedent

import tree_sitter as T

from joule.ast import (
    AST,
    Binary,
    ObjComp,
    Operator,
    Visibility,
)
from joule.parsing import LANG_JSONNET

from .dsl import FakeDocument


class TestAST(unittest.TestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.maxDiff = None

    def assertAstEqual(self, tree_or_source: AST | str, expected: AST | str):
        match tree_or_source, expected:
            case AST() as tree, str() as expected:
                self.assertMultiLineEqual(tree.pretty_tree, expected.strip())
            case AST() as tree, AST() as expected if tree != expected:
                self.assertAstEqual(tree, expected.pretty_tree)
            case str() as source, AST() as expected:
                self.assertAstEqual(FakeDocument(source).body, expected.pretty_tree)
            case str() as source, str():
                self.assertAstEqual(FakeDocument(source).body, expected)

    def test_pretty_tree(self):
        self.assertAstEqual(
            "1",
            dedent(
                """\
                Num [0:0-0:1]
                `-- value=1.0
                """
            ),
        )

        self.assertAstEqual(
            "'f' + 1",
            dedent(
                """\
                Binary [0:0-0:7]
                |-- op="+"
                |-- lhs=Str [0:0-0:3]
                |   `-- raw="f"
                `-- rhs=Num [0:6-0:7]
                .   `-- value=1.0
                """
            ),
        )

        self.assertAstEqual(
            "[1, 2, 3]",
            dedent(
                """\
                Array [0:0-0:9]
                `-- values=[...]
                .   |-- [0]=Num [0:1-0:2]
                .   |   `-- value=1.0
                .   |-- [1]=Num [0:4-0:5]
                .   |   `-- value=2.0
                .   `-- [2]=Num [0:7-0:8]
                .   .   `-- value=3.0
                """,
            ),
        )

        self.assertAstEqual(
            "local x = 1; x + 2",
            dedent(
                """\
                Local [0:0-0:18]
                |-- binds=[...]
                |   `-- [0]=Bind [0:6-0:11]
                |   .   |-- id=Id [0:6-0:7]
                |   .   |   |-- name="x"
                |   .   |   `-- kind="var"
                |   .   `-- value=Num [0:10-0:11]
                |   .   .   `-- value=1.0
                `-- body=Binary [0:13-0:18]
                .   |-- op="+"
                .   |-- lhs=Id [0:13-0:14]
                .   |   |-- name="x"
                .   |   `-- kind="varref"
                .   `-- rhs=Num [0:17-0:18]
                .   .   `-- value=2.0
                """
            ),
        )

    def test_number(self):
        t = FakeDocument("1")

        self.assertAstEqual(
            t.body,
            t.location.num(1),
        )

    def test_string(self):
        for literal, expected in [
            ("'hello\\nworld'", "hello\\nworld"),
            ('"hello\\nworld"', "hello\\nworld"),
            ("@'hello\\nworld'", "hello\\nworld"),
            ('@"hello\\nworld"', "hello\\nworld"),
            ("|||\n  hello\n|||", "\n  hello\n"),
        ]:
            t = FakeDocument(literal)
            self.assertAstEqual(
                t.body,
                t.location.string(expected),
            )

    def test_paren(self):
        t = FakeDocument(
            dedent(
                """\
                (1)
                 ^1
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.at("1").num(1),
        )

        t = FakeDocument(
            dedent(
                """\
                (assert true; 1)
                 ^^^^^^^^^^^1
                        ^^^^2 ^3
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.at("1").assert_(t.at("2").true).guard(t.at("3").num(1)),
        )

    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1; x
                      ^1  ^2 ^3
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.local(
                binds=[
                    t.at("1").var("x").bind(t.at("2").num(1)),
                ],
                body=t.at("3").var_ref("x"),
            ),
        )

    def test_local_with_asserts(self):
        t = FakeDocument(
            dedent(
                """\
                local v = 0;
                      ^v  ^0
                assert true;
                ^^^^^^^^^^^a
                       ^^^^t
                assert false;
                ^^^^^^^^^^^^b
                       ^^^^^f
                v + 2
                ^v1 ^2
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.local(
                binds=[
                    t.at("v").var("v").bind(t.at("0").num(0)),
                ],
                body=t.at("a")
                .assert_(t.at("t").true)
                .guard(
                    t.at("b")
                    .assert_(t.at("f").false)
                    .guard(t.at("v1").var_ref("v") + t.at("2").num(2))
                ),
            ),
        )

    def test_local_bind_fn(self):
        t = FakeDocument(
            dedent(
                """\
                local
                    f(x) = x + 1,
                    ^^^^^^^^^^^^fn_f
                    ^f^x   ^x1 ^1
                    g(y, z) = y + z;
                    ^^^^^^^^^^^^^^^fn_g
                    ^g^y ^z   ^y1 ^z1
                g(f(3), z = 4)
                ^^^^^^^^^^^^^^call1
                  ^^^^call2
                ^g1 ^3  ^z2 ^4
                  ^f1
                """
            )
        )

        bind_f = (
            t.at("f")
            .var("f")
            .bind(
                t.at("fn_f").fn(
                    params=[t.at("x").var("x").param()],
                    body=t.at("x1").var_ref("x") + t.at("1").num(1),
                )
            )
        )

        g = t.at("g").var("g")
        y_param = t.at("y").var("y").param()
        y_ref = t.at("y1").var_ref("y")
        z_param = t.at("z").var("z").param()
        z_ref = t.at("z1").var_ref("z")

        bind_g = g.bind(
            t.at("fn_g").fn(
                params=[y_param, z_param],
                body=y_ref + z_ref,
            )
        )

        call_g = t.at("call2").call(
            fn=t.at("f1").var_ref("f"),
            args=[t.at("3").num(3).arg()],
        )

        call_f = t.at("call1").call(
            fn=t.at("g1").var_ref("g"),
            args=[
                call_g.arg(),
                t.at("4").num(4).arg(t.at("z2").arg_ref("z")),
            ],
        )

        self.assertAstEqual(
            t.body,
            t.location.local(
                binds=[bind_f, bind_g],
                body=call_f,
            ),
        )

    def test_local_multi_binds(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1, y = 2;
                      ^x  ^1 ^y  ^2
                x + y
                ^x.1^y.1
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.local(
                binds=[
                    t.at("x").var("x").bind(t.at("1").num(1)),
                    t.at("y").var("y").bind(t.at("2").num(2)),
                ],
                body=t.at("x.1").var_ref("x") + t.at("y.1").var_ref("y"),
            ),
        )

    def test_empty_array(self):
        t = FakeDocument("[]")

        self.assertAstEqual(
            t.body,
            t.location.array(),
        )

    def test_array(self):
        t = FakeDocument(
            dedent(
                """\
                [1, true, /* ! */ '3']
                 ^1 ^^^^t         ^^^s
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.array(
                t.at("1").num(1),
                t.at("t").true,
                t.at("s").string("3"),
            ),
        )

    def test_binary(self):
        for op in Operator:
            t = FakeDocument(
                dedent(
                    f"""\
                    a /* ! */
                    ^a
                    {op.value}
                    /* ! */ b
                            ^b
                    """
                )
            )

            self.assertAstEqual(
                t.body,
                t.at("a").var_ref("a").bin_op(op, t.at("b").var_ref("b")),
            )

    def test_implicit_plus(self):
        t = FakeDocument(
            dedent(
                """\
                a {}
                ^a^^o
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.at("a").var_ref("a") + t.at("o").object(),
        )

    def test_binary_precedence(self):
        t = FakeDocument(
            dedent(
                """\
                a + b * c
                ^a  ^b  ^c
                """
            )
        )

        a = t.at("a").var_ref("a")
        b = t.at("b").var_ref("b")
        c = t.at("c").var_ref("c")

        self.assertAstEqual(
            t.body,
            a + (b * c),
        )

    def test_binary_precedence_with_paren(self):
        t = FakeDocument(
            dedent(
                """\
                (a + b) * c
                 ^a  ^b   ^c
                """
            )
        )

        a = t.at("a").var_ref("a")
        b = t.at("b").var_ref("b")
        c = t.at("c").var_ref("c")

        self.assertAstEqual(
            t.body,
            Binary(
                t.body.location,
                op=Operator.Multiply,
                lhs=a + b,
                rhs=c,
            ),
        )

    def test_list_comp(self):
        t = FakeDocument(
            dedent(
                """\
                [x for x in [1, 2] if x > 3]
                             ^1 ^2        ^3
                 ^x1   ^x   ^^^^^^arr ^x2
                                   ^^^^^^^^if
                   ^^^^^^^^^^^^^^^for
                """
            )
        )

        x = t.at("x").var("x")
        x_ref1 = t.at("x1").var_ref("x")
        x_ref2 = t.at("x2").var_ref("x")

        _1 = t.at("1").num(1)
        _2 = t.at("2").num(2)
        _3 = t.at("3").num(3)

        self.assertAstEqual(
            t.body,
            t.location.list_comp(
                x_ref1,
                t.at("for").for_(x, t.at("arr").array(_1, _2)),
                t.at("if").if_(x_ref2 > _3),
            ),
        )

    def test_fn(self):
        t = FakeDocument(
            dedent(
                """\
                function(x, y = 2) x + y
                         ^x ^y  ^2 ^x1 ^y1
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.fn(
                params=[
                    t.at("x").var("x").param(),
                    t.at("y").var("y").param(t.at("2").num(2)),
                ],
                body=t.at("x1").var_ref("x") + t.at("y1").var_ref("y"),
            ),
        )

    def test_fn_no_params(self):
        t = FakeDocument(
            dedent(
                """\
                function() 1
                           ^1
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.fn(
                params=[],
                body=t.at("1").num(1),
            ),
        )

    def test_import(self):
        t = FakeDocument(
            dedent(
                """\
                import 'test.jsonnet'
                       ^^^^^^^^^^^^^^path
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.import_(
                t.at("path").string("test.jsonnet"),
            ),
        )

    def test_importbin(self):
        t = FakeDocument(
            dedent(
                """\
                importbin 'bin'
                          ^^^^^path
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.importbin(
                t.at("path").string("bin"),
            ),
        )

    def test_importstr(self):
        t = FakeDocument(
            dedent(
                """\
                importstr 'test.jsonnet'
                          ^^^^^^^^^^^^^^path
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.importstr(
                t.at("path").string("test.jsonnet"),
            ),
        )

    def test_assert_expr_without_message(self):
        t = FakeDocument(
            dedent(
                """\
                assert true; false
                       ^^^^t ^^^^^f
                ^^^^^^^^^^^a
                """
            )
        )

        self.assertAstEqual(
            t.body, t.at("a").assert_(t.at("t").true).guard(t.at("f").false)
        )

    def test_assert_expr_with_message(self):
        t = FakeDocument(
            dedent(
                """\
                assert true: 'never';
                       ^^^^t ^^^^^^^m
                ^^^^^^^^^^^^^^^^^^^^a
                /* ! */
                false
                ^^^^^f
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.at("a")
            .assert_(t.at("t").true, t.at("m").string("never"))
            .guard(t.at("f").false),
        )

    def test_assert_expr_in_bind(self):
        t = FakeDocument(
            dedent(
                """\
                local x =
                      ^x
                    assert true;
                    ^^^^^^^^^^^a
                           ^^^^t
                    false;
                    ^^^^^f
                x
                ^x1
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.local(
                binds=[
                    t.at("x")
                    .var("x")
                    .bind(t.at("a").assert_(t.at("t").true).guard(t.at("f").false))
                ],
                body=t.at("x1").var_ref("x"),
            ),
        )

    def test_nested_assert_expr(self):
        # Assertions are right associated.
        t = FakeDocument(
            dedent(
                """\
                assert true; assert false; x
                ^^^^^^^^^^^a1       ^^^^^f ^x
                       ^^^^t ^^^^^^^^^^^^a2
                """
            )
        )

        assert1 = t.at("a1").assert_(condition=t.at("t").true)
        assert2 = t.at("a2").assert_(condition=t.at("f").false)

        self.assertAstEqual(
            t.body,
            assert1.guard(
                assert2.guard(
                    t.at("x").var_ref("x"),
                ),
            ),
        )

    def assertAstEqualByQuery(
        self, doc: FakeDocument, query: T.Query, capture: str, expected: AST
    ):
        captures = T.QueryCursor(query).captures(doc.root)
        [node] = captures[capture]
        self.assertAstEqual(AST.from_cst(doc.uri, node), expected)

    def test_object_field_name(self):
        ts_query = T.Query(LANG_JSONNET, "(fieldname) @field_key")

        t = FakeDocument(
            dedent(
                """\
                local x = 'f'; { [x]: 1 }
                                  ^x
                                 ^^^k
                """
            )
        )

        self.assertAstEqual(
            t.node_at("k"),
            t.at("k").computed_key(t.at("x").var_ref("x")),
        )

        t = FakeDocument(
            dedent(
                """\
                { x: 1 }
                  ^x
                """
            )
        )

        self.assertAstEqual(
            t.query_one(ts_query, "field_key"),
            t.at("x").fixed_id_key("x"),
        )

        t = FakeDocument(
            dedent(
                """\
                { 'x': 1 }
                  ^^^k
                """
            )
        )

        self.assertAstEqual(
            t.query_one(ts_query, "field_key"),
            t.at("k").fixed_str_key("x"),
        )

    def test_field(self):
        t = FakeDocument(
            dedent(
                """\
                { x: 1 }
                  ^^^^1
                  ^2 ^3
                """
            )
        )

        self.assertAstEqual(
            t.node_at("1"),
            t.at("2").fixed_id_key("x").with_value(t.at("3").num(1)),
        )

    def test_hidden_field(self):
        t = FakeDocument(
            dedent(
                """\
                { x+::: 1 }
                  ^^^^^^^1
                  ^2    ^3
                """
            )
        )

        self.assertAstEqual(
            t.node_at("1"),
            t.at("2")
            .fixed_id_key("x")
            .with_value(
                t.at("3").num(1),
                visibility=Visibility.Forced,
                inherited=True,
            ),
        )

    def test_function_field(self):
        t = FakeDocument(
            dedent(
                """\
                { f(p, q = 0):: p + q }
                  ^^^^^^^^^^^^^^^^^^^1
                   ^^^^^^^^^^^^^^^^^^2
                  ^3^4 ^5  ^6   ^7  ^8
                """
            )
        )

        self.assertAstEqual(
            t.node_at("1"),
            t.at("3")
            .fixed_id_key("f")
            .with_value(
                t.at("2").fn(
                    params=[
                        t.at("4").var("p").param(),
                        t.at("5").var("q").param(t.at("6").num(0)),
                    ],
                    body=t.at("7").var_ref("p") + t.at("8").var_ref("q"),
                ),
                visibility=Visibility.Hidden,
            ),
        )

    def test_function_field_no_params(self):
        t = FakeDocument(
            dedent(
                """\
                { f():: 1 }
                  ^^^^^^^f
                   ^^^^^^fn
                  ^k    ^1
                """
            )
        )

        self.assertAstEqual(
            t.node_at("f"),
            t.at("k")
            .fixed_id_key("f")
            .with_value(
                t.at("fn").fn(params=[], body=t.at("1").num(1)),
                visibility=Visibility.Hidden,
            ),
        )

    def test_obj_comp(self):
        t = FakeDocument(
            dedent(
                """\
                {
                    local x = 1,
                          ^1  ^2
                    ['f' + y]: x + y,
                     ^^^3  ^4  ^5  ^6
                    ^^^^^^^^^7
                    assert true,
                           ^^^^8
                    ^^^^^^^^^^^9
                    for x in [2, 3]
                        ^10   ^11^12
                             ^^^^^^13
                    ^^^^^^^^^^^^^^^14
                    if x + y < 4
                       ^15 ^16 ^17
                    ^^^^^^^^^^^^18
                }
                """
            )
        )

        field = (
            t.at("7")
            .computed_key(t.at("3").string("f") + t.at("4").var_ref("y"))
            .with_value(t.at("5").var_ref("x") + t.at("6").var_ref("y"))
        )

        assertion = t.at("9").assert_(t.at("8").true)

        bind = t.at("1").var("x").bind(t.at("2").num(1))

        array = t.at("13").array(
            t.at("11").num(2),
            t.at("12").num(3),
        )

        for_spec = t.at("14").for_(t.at("10").var("x"), array)

        if_spec = t.at("18").if_(
            t.at("15").var_ref("x") + t.at("16").var_ref("y") < t.at("17").num(4)
        )

        self.assertAstEqual(
            t.body,
            ObjComp(
                location=t.body.location,
                field=field,
                binds=[bind],
                asserts=[assertion],
                for_spec=for_spec,
                comp_spec=[if_spec],
            ),
        )

    def test_narrowest_enclosing_node(self):
        t = FakeDocument(
            dedent(
                """\
                {
                  f: local x = 1; x
                  ^1 ^^^^^^^^^^^^^^2
                   ^3      ^4^5 ^6
                               ^7 ^8
                }
                """
            )
        )

        var = t.at("4").var("x")
        bind = var.bind(t.at("7").num(1))
        local = t.at("2").local(binds=[bind], body=t.at("8").var_ref("x"))
        field = t.at("1").fixed_id_key("f").with_value(local)

        self.assertAstEqual(t.node_at(t.at("2").start), local)
        self.assertAstEqual(t.node_at(t.at("3").end), field)
        self.assertAstEqual(t.node_at(t.at("4").start), var)
        self.assertAstEqual(t.node_at(t.at("5").start), bind)
        self.assertAstEqual(t.node_at(t.at("6").end), local)

    def test_slice(self):
        t = FakeDocument(
            dedent(
                """\
                local x = { f: 1, g: 2 }; x['f']
                                          ^^^^^^1
                                          ^2^^^3
                """
            )
        )

        self.assertAstEqual(
            t.node_at("1"),
            t.at("1").slice(
                t.at("2").var_ref("x"),
                t.at("3").string("f"),
            ),
        )
