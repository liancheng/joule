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
                        ^^^^t ^1
                 ^^^^^^^^^^^a
                 ^^^^^^^^^^^^^^A
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.at("a").assert_(t.at("t").true).guard(t.at("1").num(1)),
        )

    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1;
                      ^x  ^1
                x
                ^x.1
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.local(
                [t.at("x").var("x").bind(t.at("1").num(1))],
                t.at("x.1").var_ref("x"),
            ),
        )

    def test_local_with_asserts(self):
        t = FakeDocument(
            dedent(
                """\
                local v1 = 0;
                      ^^v1 ^0
                assert true;
                ^A1:   ^^^^t
                ^^^^^^^^^^^a1
                assert false;
                ^A2:   ^^^^^f
                ^^^^^^^^^^^^a2
                v1 + 2
                     ^2
                     ^:A2
                     ^:A1
                ^^v1.1
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.location.local(
                [t.at("v1").var("v1").bind(t.at("0").num(0))],
                t.at("a1")
                .assert_(t.at("t").true)
                .guard(
                    t.at("a2")
                    .assert_(t.at("f").false)
                    .guard(t.at("v1.1").var_ref("v1") + t.at("2").num(2))
                ),
            ),
        )

    def test_local_bind_fn(self):
        t = FakeDocument(
            dedent(
                """\
                local
                    f1(x) = x + 1,
                    ^^^^^^^^^^^^^fn_f1
                    ^^f1    ^x.1
                       ^x       ^1
                    f2(y, z) = y + z;
                    ^^^^^^^^^^^^^^^^fn_f2
                    ^^f2       ^y.1
                       ^y ^z       ^z.1
                f2(f1(3), z = 4)
                      ^3      ^4
                ^^f2.1    ^z.2
                   ^^f1.1
                ^^^^^^^^^^^^^^^^call1
                   ^^^^^call2
                """
            )
        )

        bind_f1 = (
            t.at("f1")
            .var("f1")
            .bind(
                t.at("fn_f1").fn(
                    params=[
                        t.at("x").var("x").param(),
                    ],
                    body=t.at("x.1").var_ref("x") + t.at("1").num(1),
                )
            )
        )

        bind_f2 = (
            t.at("f2")
            .var("f2")
            .bind(
                t.at("fn_f2").fn(
                    params=[
                        t.at("y").var("y").param(),
                        t.at("z").var("z").param(),
                    ],
                    body=t.at("y.1").var_ref("y") + t.at("z.1").var_ref("z"),
                )
            )
        )

        call_f2 = t.at("call2").call(
            fn=t.at("f1.1").var_ref("f1"),
            args=[t.at("3").num(3).arg()],
        )

        call_f1 = t.at("call1").call(
            fn=t.at("f2.1").var_ref("f2"),
            args=[
                call_f2.arg(),
                t.at("4").num(4).arg(t.at("z.2").arg_ref("z")),
            ],
        )

        self.assertAstEqual(
            t.body,
            t.location.local(
                binds=[bind_f1, bind_f2],
                body=call_f1,
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
                ^a
                  ^^o
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.at("a").var_ref("a") + t.at("o").object(),
        )

    def test_binary_precedences(self):
        t = FakeDocument(
            dedent(
                """\
                a + b * c
                ^a  ^b  ^c
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.at("a").var_ref("a") + (t.at("b").var_ref("b") * t.at("c").var_ref("c")),
        )

        t = FakeDocument(
            dedent(
                """\
                (a + b) * c
                 ^a  ^b   ^c
                """
            )
        )

        self.assertAstEqual(
            t.body,
            Binary(
                t.body.location,
                op=Operator.Multiply,
                lhs=t.at("a").var_ref("a") + t.at("b").var_ref("b"),
                rhs=t.at("c").var_ref("c"),
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

        self.assertAstEqual(
            t.body,
            t.location.list_comp(
                t.at("x1").var_ref("x"),
                t.at("for").for_(
                    t.at("x").var("x"),
                    t.at("arr").array(
                        t.at("1").num(1),
                        t.at("2").num(2),
                    ),
                ),
                t.at("if").if_(
                    t.at("x2").var_ref("x") > t.at("3").num(3),
                ),
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

    object_query = T.Query(
        LANG_JSONNET,
        dedent(
            """\
            (object
              (member
                (field
                  (fieldname) @field_key
                  (_)*) @field)) @object

            (object
              (objforloop)) @object
            """
        ),
    )

    def test_object_field_name(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 'f';
                {
                  [x]: 1
                   ^var_ref
                  ^^^key
                }
                """
            )
        )

        self.assertAstEqual(
            t.query_one(self.object_query, "field_key"),
            t.at("key").computed_key(t.at("var_ref").var_ref("x")),
        )

        t = FakeDocument(
            dedent(
                """\
                { x: 1 }
                  ^key
                """
            )
        )

        self.assertAstEqual(
            t.query_one(self.object_query, "field_key"),
            t.at("key").fixed_id_key("x"),
        )

        t = FakeDocument(
            dedent(
                """\
                { 'x': 1 }
                  ^^^key
                """
            )
        )

        self.assertAstEqual(
            t.query_one(self.object_query, "field_key"),
            t.at("key").fixed_str_key("x"),
        )

    def test_field(self):
        t = FakeDocument(
            dedent(
                """\
                { x: 1 }
                  ^key
                     ^value
                """
            )
        )

        self.assertAstEqual(
            t.query_one(self.object_query, "field"),
            t.at("key").fixed_id_key("x").with_value(t.at("value").num(1)),
        )

    def test_hidden_field(self):
        t = FakeDocument(
            dedent(
                """\
                { x+::: 1 }
                  ^key  ^value
                """
            )
        )

        self.assertAstEqual(
            t.query_one(self.object_query, "field"),
            t.at("key")
            .fixed_id_key("x")
            .with_value(
                t.at("value").num(1),
                visibility=Visibility.Forced,
                inherited=True,
            ),
        )

    def test_function_field(self):
        t = FakeDocument(
            dedent(
                """\
                { f(p, q = 0):: p + q }
                  ^^^^^^^^^^^^^^^^^^^F
                  ^f^p ^q  ^0   ^p.1^q.1
                """
            )
        )

        self.assertAstEqual(
            t.query_one(self.object_query, "field"),
            t.at("f")
            .fixed_id_key("f")
            .with_value(
                t.at("F").fn(
                    params=[
                        t.at("p").var("p").param(),
                        t.at("q").var("q").param(t.at("0").num(0)),
                    ],
                    body=t.at("p.1").var_ref("p") + t.at("q.1").var_ref("q"),
                ),
                visibility=Visibility.Hidden,
            ),
        )

    def test_function_field_no_params(self):
        t = FakeDocument(
            dedent(
                """\
                { f():: 1 }
                  ^^^^^^^field
                  ^key  ^1
                """
            )
        )

        self.assertAstEqual(
            t.query_one(self.object_query, "field"),
            t.at("key")
            .fixed_id_key("f")
            .with_value(
                t.at("field").fn(
                    params=[],
                    body=t.at("1").num(1),
                ),
                visibility=Visibility.Hidden,
            ),
        )

    def test_obj_comp(self):
        t = FakeDocument(
            dedent(
                """\
                {
                    ['f' + x]: 0
                    ^^^^^^^^^k ^0
                     ^^^f  ^x.1
                    ^^^^^^^^^^^^F
                    for x in [1, 2]
                        ^x    ^1 ^2
                             ^^^^^^a
                    ^^^^^^^^^^^^^^^fs
                    if x > 3
                    ^^^^^^^^is
                       ^x.2^3
                }
                """
            )
        )

        self.assertAstEqual(
            t.query_one(self.object_query, "object"),
            ObjComp(
                location=t.body.location,
                binds=[],
                field=t.at("k")
                .computed_key(t.at("f").string("f") + t.at("x.1").var_ref("x"))
                .with_value(t.at("0").num(0)),
                for_spec=t.at("fs").for_(
                    t.at("x").var("x"),
                    t.at("a").array(
                        t.at("1").num(1),
                        t.at("2").num(2),
                    ),
                ),
                comp_spec=[
                    t.at("is").if_(t.at("x.2").var_ref("x") > t.at("3").num(3)),
                ],
            ),
        )

    @unittest.skip("tree-sitter-jsonnet does not handle `objforloop` with local.")
    def test_obj_comp_with_local(self):
        FakeDocument(
            dedent(
                """\
                {
                    local y = 3,
                    ['f' + x]: x,
                    local z = 4,
                    for x in [1, 2]
                    if x > 1
                }
                """
            )
        )

    def test_narrowest_enclosing_node(self):
        t = FakeDocument(
            dedent(
                """\
                {
                  f: local x = 1;
                  ^field:    ^eq
                  ^key         ^num
                   ^colon  ^var ^semicolon
                     ^local:
                  x
                  ^var_ref
                  ^:field
                  ^:local
                }
                """
            )
        )

        self.assertAstEqual(
            t.node_at(t.at("var").start),
            t.at("var").var("x"),
        )

        self.assertAstEqual(
            t.node_at(t.at("eq").start),
            t.at("var").var("x").bind(t.at("num").num(1)),
        )

        self.assertAstEqual(
            t.node_at(t.at("local").start),
            t.at("local").local(
                binds=[t.at("var").var("x").bind(t.at("num").num(1))],
                body=t.at("var_ref").var_ref("x"),
            ),
        )

        local = t.at("local").local(
            binds=[t.at("var").var("x").bind(t.at("num").num(1))],
            body=t.at("var_ref").var_ref("x"),
        )

        self.assertAstEqual(
            t.node_at(t.at("semicolon").end),
            local,
        )

        self.assertAstEqual(
            t.node_at(t.at("colon").end),
            t.at("key").fixed_id_key("f").with_value(local),
        )

    def test_slice(self):
        t = FakeDocument(
            dedent(
                """\
                local x = { f: 1, g: 2 };
                x['f']
                ^^^^^^s
                  ^^^f
                ^x
                """
            )
        )

        self.assertAstEqual(
            t.node_at("s"),
            t.at("s").slice(
                t.at("x").var_ref("x"),
                t.at("f").string("f"),
            ),
        )
