import unittest
from textwrap import dedent

import tree_sitter as T

from joule.ast import (
    AST,
    Array,
    Binary,
    ComputedKey,
    Field,
    Local,
    Num,
    ObjComp,
    Operator,
    Slice,
    Str,
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
                |   .   |-- id=Id.Var [0:6-0:7]
                |   .   |   `-- name="x"
                |   .   `-- value=Num [0:10-0:11]
                |   .   .   `-- value=1.0
                `-- body=Binary [0:13-0:18]
                .   |-- op="+"
                .   |-- lhs=Id.VarRef [0:13-0:14]
                .   |   `-- name="x"
                .   `-- rhs=Num [0:17-0:18]
                .   .   `-- value=2.0
                """
            ),
        )

    def test_number(self):
        t = FakeDocument("1")

        self.assertAstEqual(
            t.body,
            Num(t.location, 1),
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
                Str(t.location, expected),
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
            t.num(at=1, value=1),
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
            t.assert_(at=1, condition=t.true(at=2)).guard(t.num(at=3, value=1)),
        )

    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1; x
                      ^1  ^2 ^3
                ^^^^^^^^^^^^^^4
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.local(
                at=4,
                binds=[
                    t.var(at=1, name="x").bind(t.num(at=2, value=1)),
                ],
                body=t.var_ref(at=3, name="x"),
            ),
        )

    def test_local_with_asserts(self):
        t = FakeDocument(
            dedent(
                """\
                local v = 0;
                ^1:   ^2  ^3
                assert true;
                ^^^^^^^^^^^4
                       ^^^^5
                assert false;
                ^^^^^^^^^^^^6
                       ^^^^^7
                v + 2
                ^8  ^9
                    ^:1
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.local(
                at=1,
                binds=[
                    t.var(at=2, name="v").bind(t.num(at=3, value=0)),
                ],
                body=t.assert_(at=4, condition=t.true(at=5)).guard(
                    t.assert_(at=6, condition=t.false(at=7)).guard(
                        t.var_ref(at=8, name="v") + t.num(at=9, value=2)
                    )
                ),
            ),
        )

    def test_local_bind_fn(self):
        t = FakeDocument(
            dedent(
                """\
                local
                    f(x) = x + 1,
                    ^^^^^^^^^^^^1
                    ^2^3   ^4  ^5
                    g(y, z) = y + z;
                    ^^^^^^^^^^^^^^^6
                    ^7^8 ^9   ^10 ^11
                g(f(3), z = 4)
                ^^^^^^^^^^^^^^12
                  ^^^^13
                ^14 ^15 ^16 ^17
                  ^18
                """
            )
        )

        bind_f = t.var(at=2, name="f").bind(
            t.fn(
                at=1,
                params=[t.var(at=3, name="x").param()],
                body=t.var_ref(at=4, name="x") + t.num(at=5, value=1),
            )
        )

        g = t.var(at=7, name="g")
        y_param = t.var(at=8, name="y").param()
        y_ref = t.var_ref(at=10, name="y")
        z_param = t.var(at=9, name="z").param()
        z_ref = t.var_ref(at=11, name="z")

        bind_g = g.bind(
            t.fn(
                at=6,
                params=[y_param, z_param],
                body=y_ref + z_ref,
            )
        )

        call_g = t.call(
            at=13,
            fn=t.var_ref(at=18, name="f"),
            args=[t.num(at=15, value=3).arg()],
        )

        call_f = t.call(
            at=12,
            fn=t.var_ref(at=14, name="g"),
            args=[
                call_g.arg(),
                t.num(at=17, value=4).arg(t.param_ref(at=16, name="z")),
            ],
        )

        self.assertAstEqual(
            t.body,
            Local(
                t.location,
                binds=[bind_f, bind_g],
                body=call_f,
            ),
        )

    def test_local_multi_binds(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1, y = 2;
                      ^1  ^2 ^3  ^4
                x + y
                ^5  ^6
                """
            )
        )

        self.assertAstEqual(
            t.body,
            Local(
                t.location,
                binds=[
                    t.var(at=1, name="x").bind(t.num(at=2, value=1)),
                    t.var(at=3, name="y").bind(t.num(at=4, value=2)),
                ],
                body=t.var_ref(at=5, name="x") + t.var_ref(at=6, name="y"),
            ),
        )

    def test_empty_array(self):
        t = FakeDocument("[]")

        self.assertAstEqual(
            t.body,
            Array(t.location, []),
        )

    def test_array(self):
        t = FakeDocument(
            dedent(
                """\
                [1, true, /* ! */ '3']
                ^^^^^^^^^^^^^^^^^^^^^^1
                 ^2 ^^^^3         ^^^4
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.array(
                at=1,
                values=[
                    t.num(at=2, value=1),
                    t.true(at=3),
                    t.string(at=4, value="3"),
                ],
            ),
        )

    def test_binary(self):
        for op in Operator:
            t = FakeDocument(
                dedent(
                    f"""\
                    a {op.value} b
                    ^1{" " * len(op.value)} ^2
                    """
                )
            )

            self.assertAstEqual(
                t.body,
                t.var_ref(at=1, name="a").bin_op(op, t.var_ref(at=2, name="b")),
            )

    def test_implicit_plus(self):
        t = FakeDocument(
            dedent(
                """\
                a {}
                ^1^^2
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.var_ref(at=1, name="a") + t.object(at=2),
        )

    def test_binary_precedence(self):
        t = FakeDocument(
            dedent(
                """\
                a + b * c
                ^1  ^2  ^3
                """
            )
        )

        a = t.var_ref(at=1, name="a")
        b = t.var_ref(at=2, name="b")
        c = t.var_ref(at=3, name="c")

        self.assertAstEqual(
            t.body,
            a + (b * c),
        )

    def test_binary_precedence_with_paren(self):
        t = FakeDocument(
            dedent(
                """\
                (a + b) * c
                 ^1  ^2   ^3
                """
            )
        )

        self.assertAstEqual(
            t.body,
            Binary(
                t.body.location,
                op=Operator.Multiply,
                lhs=t.var_ref(at=1, name="a") + t.var_ref(at=2, name="b"),
                rhs=t.var_ref(at=3, name="c"),
            ),
        )

    def test_list_comp(self):
        t = FakeDocument(
            dedent(
                """\
                [
                ^1:
                    x for x in [1, 2]
                    ^2^3: ^4   ^5:  ^:5,:3
                                ^6 ^7
                    if x > 3
                    ^8:^9  ^10,:8
                ]
                ^:1
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.list_comp(
                at=1,
                expr=t.var_ref(at=2, name="x"),
                for_spec=t.for_(
                    at=3,
                    id=t.var(at=4, name="x"),
                    source=t.array(
                        at=5,
                        values=[
                            t.num(at=6, value=1),
                            t.num(at=7, value=2),
                        ],
                    ),
                ),
                comp_spec=[
                    t.if_(
                        at=8,
                        condition=t.var_ref(at=9, name="x") > t.num(at=10, value=3),
                    )
                ],
            ),
        )

    def test_fn(self):
        t = FakeDocument(
            dedent(
                """\
                function(x, y = 2) x + y
                ^1:      ^2 ^3  ^4 ^5  ^6,:
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.fn(
                at=1,
                params=[
                    t.var(at=2, name="x").param(),
                    t.var(at=3, name="y").param(t.num(at=4, value=2)),
                ],
                body=t.var_ref(at=5, name="x") + t.var_ref(at=6, name="y"),
            ),
        )

    def test_fn_no_params(self):
        t = FakeDocument(
            dedent(
                """\
                function() 1
                ^1:        ^2,:
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.fn(
                at=1,
                params=[],
                body=t.num(at=2, value=1),
            ),
        )

    def test_import(self):
        t = FakeDocument(
            dedent(
                """\
                import 'test.jsonnet'
                ^1:    ^^^^^^^^^^^^^^2,:
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.import_(
                at=1,
                path=t.string(at=2, value="test.jsonnet"),
            ),
        )

    def test_importbin(self):
        t = FakeDocument(
            dedent(
                """\
                importbin 'bin'
                ^1:       ^^^^^2,:
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.importbin(
                at=1,
                path=t.string(at=2, value="bin"),
            ),
        )

    def test_importstr(self):
        t = FakeDocument(
            dedent(
                """\
                importstr 'test.jsonnet'
                ^1:       ^^^^^^^^^^^^^^2,:
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.importstr(
                at=1,
                path=t.string(at=2, value="test.jsonnet"),
            ),
        )

    def test_assert_expr_without_message(self):
        t = FakeDocument(
            dedent(
                """\
                assert true; false
                ^^^^^^^^^^^1
                       ^^^^2 ^^^^^3
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.assert_(at=1, condition=t.true(at=2)).guard(t.false(at=3)),
        )

    def test_assert_expr_with_message(self):
        t = FakeDocument(
            dedent(
                """\
                assert true: 'never';
                       ^^^^1 ^^^^^^^2
                ^^^^^^^^^^^^^^^^^^^^3
                /* ! */
                false
                ^^^^^4
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.assert_(
                at=3,
                condition=t.true(at=1),
                message=t.string(at=2, value="never"),
            ).guard(t.false(at=4)),
        )

    def test_assert_expr_in_bind(self):
        t = FakeDocument(
            dedent(
                """\
                local x =
                ^1:   ^2
                    assert true;
                    ^3:    ^^^^4,:
                    false;
                    ^^^^^5
                x
                ^:1,6
                """
            )
        )

        self.assertAstEqual(
            t.body,
            t.local(
                at=1,
                binds=[
                    t.var(at=2, name="x").bind(
                        t.assert_(at=3, condition=t.true(at=4)).guard(t.false(at=5))
                    )
                ],
                body=t.var_ref(at=6, name="x"),
            ),
        )

    def test_nested_assert_expr(self):
        # Assertions are right associated.
        t = FakeDocument(
            dedent(
                """\
                assert true; assert false; x
                ^^^^^^^^^^^1        ^^^^^2 ^3
                       ^^^^4 ^^^^^^^^^^^^5
                """
            )
        )

        assert1 = t.assert_(at=1, condition=t.true(at=4))
        assert2 = t.assert_(at=5, condition=t.false(at=2))

        self.assertAstEqual(
            t.body,
            assert1.guard(
                assert2.guard(
                    t.var_ref(at=3, name="x"),
                ),
            ),
        )

    def assertAstEqualByQuery(
        self, doc: FakeDocument, query: T.Query, capture: str, expected: AST
    ):
        captures = T.QueryCursor(query).captures(doc.cst)
        [node] = captures[capture]
        self.assertAstEqual(AST.from_cst(doc.uri, node), expected)

    def test_object_field_name(self):
        ts_query = T.Query(LANG_JSONNET, "(fieldname) @field_key")

        t = FakeDocument(
            dedent(
                """\
                local x = 'f'; { [x]: 1 }
                                  ^1
                                 ^^^2
                """
            )
        )

        self.assertAstEqual(
            t.node_at(2).to(ComputedKey),
            t.computed_key(at=2, expr=t.var_ref(at=1, name="x")),
        )

        t = FakeDocument(
            dedent(
                """\
                { x: 1 }
                  ^1
                """
            )
        )

        self.assertAstEqual(
            t.query_one(ts_query, "field_key"),
            t.fixed_id_key(at=1, name="x"),
        )

        t = FakeDocument(
            dedent(
                """\
                { 'x': 1 }
                  ^^^1
                """
            )
        )

        self.assertAstEqual(
            t.query_one(ts_query, "field_key"),
            t.fixed_str_key(at=1, name="x"),
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
            t.node_at(1).to(Field),
            t.fixed_id_key(at=2, name="x").map_to(t.num(at=3, value=1)),
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
            t.node_at(1).to(Field),
            t.fixed_id_key(at=2, name="x").map_to(
                t.num(at=3, value=1),
                visibility=Visibility.Forced,
                inherited=True,
            ),
        )

    def test_function_field(self):
        t = FakeDocument(
            dedent(
                """\
                { func(p, q = 0):: p + q }
                  ^1: ^2:              ^:2,:1
                  ^^^^3^4 ^5  ^6   ^7  ^8
                """
            )
        )

        self.assertAstEqual(
            t.node_at(1).to(Field),
            t.fixed_id_key(at=3, name="func").map_to(
                t.fn(
                    at=2,
                    params=[
                        t.var(at=4, name="p").param(),
                        t.var(at=5, name="q").param(t.num(at=6, value=0)),
                    ],
                    body=t.var_ref(at=7, name="p") + t.var_ref(at=8, name="q"),
                ),
                visibility=Visibility.Hidden,
            ),
        )

    def test_function_field_no_params(self):
        t = FakeDocument(
            dedent(
                """\
                { f():: 1 }
                  ^^^^^^^1
                   ^^^^^^2
                  ^3    ^4
                """
            )
        )

        self.assertAstEqual(
            t.node_at(1).to(Field),
            t.fixed_id_key(at=3, name="f").map_to(
                t.fn(
                    at=2,
                    params=[],
                    body=t.num(at=4, value=1),
                ),
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
                    ['f' + y]:: x + y,
                     ^^^3  ^4   ^5  ^6
                    ^^^^^^^^^7
                    assert true,
                    ^8:    ^^^^9,:
                    for x in [2, 3]
                        ^10   ^11^12
                    ^13:     ^^^^^^14,:
                    if x + y < 4
                       ^15 ^16 ^17
                    ^^^^^^^^^^^^18
                }
                """
            )
        )

        key = t.computed_key(
            at=7,
            expr=t.string(at=3, value="f") + t.var_ref(at=4, name="y"),
        )

        value = t.var_ref(at=5, name="x") + t.var_ref(at=6, name="y")

        array = t.array(
            at=14,
            values=[
                t.num(at=11, value=2),
                t.num(at=12, value=3),
            ],
        )

        for_spec = t.for_(
            at=13,
            id=t.var(at=10, name="x"),
            source=array,
        )

        if_spec = t.if_(
            at=18,
            condition=(
                t.var_ref(at=15, name="x") + t.var_ref(at=16, name="y")
                < t.num(at=17, value=4)
            ),
        )

        self.assertAstEqual(
            t.body,
            ObjComp(
                location=t.body.location,
                field=key.map_to(value, Visibility.Hidden),
                binds=[
                    t.var(at=1, name="x").bind(t.num(at=2, value=1)),
                ],
                asserts=[t.assert_(at=8, condition=t.true(at=9))],
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
                  ^1 ^2:   ^4^5 ^6^:2
                   ^3          ^7 ^8
                }
                """
            )
        )

        var = t.var(at=4, name="x")
        self.assertAstEqual(t.node_at(t.start_of(4)), var)

        bind = var.bind(t.num(at=7, value=1))
        self.assertAstEqual(t.node_at(t.start_of(5)), bind)

        local = t.local(at=2, binds=[bind], body=t.var_ref(at=8, name="x"))
        self.assertAstEqual(t.node_at(t.start_of(2)), local)
        self.assertAstEqual(t.node_at(t.end_of(6)), local)

        field = t.fixed_id_key(at=1, name="f").map_to(local)
        self.assertAstEqual(t.node_at(t.end_of(3)), field)

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
            t.node_at(1).to(Slice),
            t.element_at(
                at=1,
                collection=t.var_ref(at=2, name="x"),
                key=t.string(at=3, value="f"),
            ),
        )

    def test_dollar(self):
        t = FakeDocument(
            dedent(
                """\
                { f: 1, g: $.f }
                        ^^^^^^1
                        ^2 ^3^4
                """
            )
        )

        self.assertAstEqual(
            t.node_at(1).to(Field),
            t.fixed_id_key(at=2, name="g").map_to(
                t.dollar(at=3).get(t.field_ref(at=4, name="f")),
            ),
        )
