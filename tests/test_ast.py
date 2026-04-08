import unittest
from textwrap import dedent

import tree_sitter as T

from joule import ast as A
from joule.parsing import LANG_JSONNET

from .dsl import FakeDocument


class TestAST(unittest.TestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.maxDiff = None

    def assertAstEqual(self, tree_or_source: A.AST | str, expected: A.AST | str):
        match tree_or_source, expected:
            case A.AST() as tree, str() as expected:
                self.assertMultiLineEqual(tree.pretty_tree, expected.strip())
            case A.AST() as tree, A.AST() as expected if tree != expected:
                self.assertAstEqual(tree, expected.pretty_tree)
            case str() as source, A.AST() as expected:
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
                |   `-- value="f"
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
            A.Num(t.location, 1),
        )

    def test_string(self):
        for literal, expected in [
            ("'hello\\nworld'", "hello\nworld"),
            ('"hello\\nworld"', "hello\nworld"),
            ("@'hello\\nworld'", "hello\nworld"),
            ('@"hello\\nworld"', "hello\nworld"),
            (
                dedent(
                    """\
                    |||
                        hello
                    |||
                    """
                ),
                "hello\n",
            ),
        ]:
            t = FakeDocument(literal)
            self.assertAstEqual(
                t.body,
                A.Str(t.location, expected),
            )

            self.assertEqual(t.body.to(A.Str).value, expected)

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
            A.Num(t.at(1), 1),
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
            A.Assert(
                t.at(1),
                condition=A.Bool(t.at(2), True),
            ).guard(A.Num(t.at(3), 1)),
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
            A.Local(
                t.at(4),
                binds=[
                    A.Id.Var(t.at(1), "x").bind(A.Num(t.at(2), 1)),
                ],
                body=A.Id.VarRef(t.at(3), "x"),
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
            A.Local(
                t.at(1),
                binds=[
                    A.Id.Var(t.at(2), "v").bind(A.Num(t.at(3), 0)),
                ],
                body=A.Assert(t.at(4), condition=A.Bool(t.at(5), True)).guard(
                    A.Assert(t.at(6), condition=A.Bool(t.at(7), False)).guard(
                        A.Id.VarRef(t.at(8), "v") + A.Num(t.at(9), 2)
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

        bind_f = A.Id.Var(t.at(2), "f").bind(
            A.Fn(
                t.at(1),
                params=[A.Id.Var(t.at(3), "x").param()],
                body=A.Id.VarRef(t.at(4), "x") + A.Num(t.at(5), 1),
            )
        )

        g = A.Id.Var(t.at(7), "g")
        y_param = A.Id.Var(t.at(8), "y").param()
        y_ref = A.Id.VarRef(t.at(10), "y")
        z_param = A.Id.Var(t.at(9), "z").param()
        z_ref = A.Id.VarRef(t.at(11), "z")

        bind_g = g.bind(
            A.Fn(
                t.at(6),
                params=[y_param, z_param],
                body=y_ref + z_ref,
            )
        )

        call_g = A.Call(
            t.at(13),
            callee=A.Id.VarRef(t.at(18), "f"),
            args=[A.Num(t.at(15), 3).arg()],
        )

        call_f = A.Call(
            t.at(12),
            callee=A.Id.VarRef(t.at(14), "g"),
            args=[
                call_g.arg(),
                A.Num(t.at(17), 4).arg(A.Id.ParamRef(t.at(16), "z")),
            ],
        )

        self.assertAstEqual(
            t.body,
            A.Local(
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
            A.Local(
                t.location,
                binds=[
                    A.Id.Var(t.at(1), "x").bind(A.Num(t.at(2), 1)),
                    A.Id.Var(t.at(3), "y").bind(A.Num(t.at(4), 2)),
                ],
                body=A.Id.VarRef(t.at(5), "x") + A.Id.VarRef(t.at(6), "y"),
            ),
        )

    def test_empty_array(self):
        t = FakeDocument("[]")

        self.assertAstEqual(
            t.body,
            A.Array(t.location, []),
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
            A.Array(
                t.at(1),
                values=[
                    A.Num(t.at(2), 1),
                    A.Bool(t.at(3), True),
                    A.Str(t.at(4), "3"),
                ],
            ),
        )

    def test_binary(self):
        for op in A.Operator:
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
                A.Id.VarRef(t.at(1), "a").bin_op(op, A.Id.VarRef(t.at(2), "b")),
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
            A.Id.VarRef(t.at(1), "a") + A.Object(t.at(2)),
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

        a = A.Id.VarRef(t.at(1), "a")
        b = A.Id.VarRef(t.at(2), "b")
        c = A.Id.VarRef(t.at(3), "c")

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
            A.Binary(
                t.body.location,
                op=A.Operator.Multiply,
                lhs=A.Id.VarRef(t.at(1), "a") + A.Id.VarRef(t.at(2), "b"),
                rhs=A.Id.VarRef(t.at(3), "c"),
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
            A.ListComp(
                t.at(1),
                expr=A.Id.VarRef(t.at(2), "x"),
                for_spec=A.ForSpec(
                    t.at(3),
                    id=A.Id.Var(t.at(4), "x"),
                    source=A.Array(
                        t.at(5),
                        values=[
                            A.Num(t.at(6), 1),
                            A.Num(t.at(7), 2),
                        ],
                    ),
                ),
                comp_spec=[
                    A.IfSpec(
                        t.at(8),
                        condition=A.Id.VarRef(t.at(9), "x") > A.Num(t.at(10), 3),
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
            A.Fn(
                t.at(1),
                params=[
                    A.Id.Var(t.at(2), "x").param(),
                    A.Id.Var(t.at(3), "y").param(A.Num(t.at(4), 2)),
                ],
                body=A.Id.VarRef(t.at(5), "x") + A.Id.VarRef(t.at(6), "y"),
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
            A.Fn(
                t.at(1),
                params=[],
                body=A.Num(t.at(2), 1),
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
            A.Import(
                t.at(1),
                type=A.ImportType.Default,
                importee=A.Importee(t.at(2), "test.jsonnet"),
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
            A.Import(
                t.at(1),
                type=A.ImportType.Bin,
                importee=A.Importee(t.at(2), "bin"),
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
            A.Import(
                t.at(1),
                type=A.ImportType.Str,
                importee=A.Importee(t.at(2), "test.jsonnet"),
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
            A.Assert(t.at(1), condition=A.Bool(t.at(2), True)).guard(
                A.Bool(t.at(3), False)
            ),
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
            A.Assert(
                t.at(3),
                condition=A.Bool(t.at(1), True),
                message=A.Str(t.at(2), "never"),
            ).guard(A.Bool(t.at(4), False)),
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
            A.Local(
                t.at(1),
                binds=[
                    A.Id.Var(t.at(2), "x").bind(
                        A.Assert(t.at(3), condition=A.Bool(t.at(4), True)).guard(
                            A.Bool(t.at(5), False)
                        )
                    )
                ],
                body=A.Id.VarRef(t.at(6), "x"),
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

        assert1 = A.Assert(t.at(1), condition=A.Bool(t.at(4), True))
        assert2 = A.Assert(t.at(5), condition=A.Bool(t.at(2), False))

        self.assertAstEqual(
            t.body,
            assert1.guard(
                assert2.guard(
                    A.Id.VarRef(t.at(3), "x"),
                ),
            ),
        )

    def assertAstEqualByQuery(
        self, doc: FakeDocument, query: T.Query, capture: str, expected: A.AST
    ):
        captures = T.QueryCursor(query).captures(doc.cst)
        [node] = captures[capture]
        self.assertAstEqual(A.AST.from_cst(doc.uri, node), expected)

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
            t.node_at(2).to(A.ComputedKey),
            A.ComputedKey(t.at(2), expr=A.Id.VarRef(t.at(1), "x")),
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
            A.FixedKey(t.at(1), A.Id.Field(t.at(1), "x")),
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
            A.FixedKey(t.at(1), A.Id.Field(t.at(1), "x")),
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
            t.node_at(1).to(A.Field),
            A.FixedKey(t.at(2), A.Id.Field(t.at(2), "x")).map_to(A.Num(t.at(3), 1)),
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
            t.node_at(1).to(A.Field),
            A.FixedKey(t.at(2), A.Id.Field(t.at(2), "x")).map_to(
                A.Num(t.at(3), 1),
                visibility=A.Visibility.Forced,
                inherited=True,
            ),
        )

    def test_fn_field(self):
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
            t.node_at(1).to(A.Field),
            A.FixedKey(t.at(3), A.Id.Field(t.at(3), "func")).map_to(
                A.Fn(
                    t.at(2),
                    params=[
                        A.Id.Var(t.at(4), "p").param(),
                        A.Id.Var(t.at(5), "q").param(A.Num(t.at(6), 0)),
                    ],
                    body=A.Id.VarRef(t.at(7), "p") + A.Id.VarRef(t.at(8), "q"),
                ),
                visibility=A.Visibility.Hidden,
            ),
        )

    def test_fn_field_no_params(self):
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
            t.node_at(1).to(A.Field),
            A.FixedKey(t.at(3), A.Id.Field(t.at(3), "f")).map_to(
                A.Fn(
                    t.at(2),
                    params=[],
                    body=A.Num(t.at(4), 1),
                ),
                visibility=A.Visibility.Hidden,
            ),
        )

    def test_fn_body_with_assert(self):
        t = FakeDocument(
            dedent(
                """\
                function() assert true; 1
                ^1:        ^^^^^^^^^^^2 ^:1,3
                                  ^^^^4
                """
            )
        )

        self.assertAstEqual(
            t.body.to(A.Fn),
            A.Fn(
                t.at(1),
                params=[],
                body=A.Assert(t.at(2), condition=A.Bool(t.at(4), True)).guard(
                    A.Num(t.at(3), 1)
                ),
            ),
        )

    def test_fn_field_body_with_assert(self):
        t = FakeDocument(
            dedent(
                """\
                { f(): assert true; 1 }
                  ^^^^^^^^^^^^^^^^^^^1
                  ^2
                   ^3: ^^^^^^^^^^^4 ^:3,5
                              ^^^^6
                """
            )
        )

        self.assertAstEqual(
            t.node_at(1).to(A.Field),
            A.FixedKey(t.at(2), A.Id.Field(t.at(2), "f")).map_to(
                A.Fn(
                    t.at(3),
                    params=[],
                    body=A.Assert(t.at(4), condition=A.Bool(t.at(6), True)).guard(
                        A.Num(t.at(5), 1)
                    ),
                )
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

        key = A.ComputedKey(
            t.at(7),
            expr=A.Str(t.at(3), "f") + A.Id.VarRef(t.at(4), "y"),
        )

        value = A.Id.VarRef(t.at(5), "x") + A.Id.VarRef(t.at(6), "y")

        array = A.Array(
            t.at(14),
            values=[
                A.Num(t.at(11), 2),
                A.Num(t.at(12), 3),
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
                A.Id.VarRef(t.at(15), "x") + A.Id.VarRef(t.at(16), "y")
                < A.Num(t.at(17), 4)
            ),
        )

        self.assertAstEqual(
            t.body,
            A.ObjComp(
                location=t.body.location,
                field=key.map_to(value, A.Visibility.Hidden),
                binds=[
                    A.Id.Var(t.at(1), "x").bind(A.Num(t.at(2), 1)),
                ],
                asserts=[A.Assert(t.at(8), condition=A.Bool(t.at(9), True))],
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

        var = A.Id.Var(t.at(4), "x")
        self.assertAstEqual(t.node_at(t.start_of(4)), var)

        bind = var.bind(A.Num(t.at(7), 1))
        self.assertAstEqual(t.node_at(t.start_of(5)), bind)

        local = A.Local(t.at(2), binds=[bind], body=A.Id.VarRef(t.at(8), "x"))
        self.assertAstEqual(t.node_at(t.start_of(2)), local)
        self.assertAstEqual(t.node_at(t.end_of(6)), local)

        field = A.FixedKey(t.at(1), A.Id.Field(t.at(1), "f")).map_to(local)
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
            t.node_at(1).to(A.Slice),
            A.Slice(
                t.at(1),
                array=A.Id.VarRef(t.at(2), "x"),
                begin=A.Str(t.at(3), "f"),
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
            t.node_at(1).to(A.Field),
            A.FixedKey(t.at(2), A.Id.Field(t.at(2), "g")).map_to(
                A.Dollar(t.at(3)).get(A.Id.FieldRef(t.at(4), "f")),
            ),
        )
