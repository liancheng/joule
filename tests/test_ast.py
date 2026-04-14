from textwrap import dedent

import tree_sitter as T

from joule import ast as A
from joule.parsing import LANG_JSONNET

from . import ASTTestCase
from .dsl import (
    FakeDocument,
    assert_expr,
    binary,
    bind,
    false,
    field,
    fixed_key,
    get_field,
    num,
    param,
    true,
)


class TestAST(ASTTestCase):
    QUERY = T.Query(
        LANG_JSONNET,
        dedent(
            """\
            (fieldname) @field_key

            (assert) @assert

            (bind
              function: (_)
              params: (_)
              body: (_)) @local_function
            """
        ),
    )

    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.maxDiff = None

    def query(self, doc: FakeDocument, capture: str) -> list[A.AST]:
        return [
            A.AST.from_cst(doc.uri, node)
            for node in T.QueryCursor(self.QUERY).captures(doc.cst)[capture]
        ]

    def query_one(self, doc: FakeDocument, capture: str) -> A.AST:
        return next(iter(self.query(doc, capture)))

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

    def test_null(self):
        t = FakeDocument("null")
        self.assertAstEqual(t.body, A.Null(t.location))

    def test_number(self):
        t = FakeDocument("1")
        self.assertAstEqual(t.body, num(t.location, 1))

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
            num(t.at(1), 1),
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
            assert_expr(
                A.Assert(t.at(1), condition=true(t.at(2))),
                num(t.at(3), 1),
            ),
        )

    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1; x
                ^1:   ^2  ^3 ^4,:1
                """
            )
        )

        self.assertAstEqual(
            t.body,
            A.Local(
                t.at(1),
                binds=[
                    bind(
                        A.Id.Var(t.at(2), "x"),
                        num(t.at(3), 1),
                    ),
                ],
                body=A.Id.VarRef(t.at(4), "x"),
            ),
        )

    def test_local_with_asserts(self):
        t = FakeDocument(
            dedent(
                """\
                local v = 0;
                assert true;
                ^4:    ^^^^:4,5
                assert false;
                ^6:    ^^^^^:6,7
                v + 2
                ^8  ^9
                """
            )
        )

        obtained1, obtained2 = self.query(t, "assert")

        self.assertAstEqual(
            obtained2,
            assert_expr(
                A.Assert(t.at(6), condition=false(t.at(7))),
                binary(
                    A.BinaryOp.Plus,
                    A.Id.VarRef(t.at(8), "v"),
                    num(t.at(9), 2),
                ),
            ),
        )

        self.assertAstEqual(
            obtained1,
            assert_expr(
                A.Assert(t.at(4), condition=true(t.at(5))),
                obtained2.to(A.Expr),
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
                """
            )
        )

        bind_f, bind_g = self.query(t, "local_function")

        self.assertAstEqual(
            bind_f,
            bind(
                A.Id.Var(t.at(2), "f"),
                A.Fn(
                    t.at(1),
                    params=[param(A.Id.Var(t.at(3), "x"))],
                    body=binary(
                        A.BinaryOp.Plus,
                        A.Id.VarRef(t.at(4), "x"),
                        num(t.at(5), 1),
                    ),
                ),
            ),
        )

        self.assertAstEqual(
            bind_g,
            bind(
                A.Id.Var(t.at(7), "g"),
                A.Fn(
                    t.at(6),
                    params=[
                        param(A.Id.Var(t.at(8), "y")),
                        param(A.Id.Var(t.at(9), "z")),
                    ],
                    body=binary(
                        A.BinaryOp.Plus,
                        A.Id.VarRef(t.at(10), "y"),
                        A.Id.VarRef(t.at(11), "z"),
                    ),
                ),
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
                    bind(A.Id.Var(t.at(1), "x"), num(t.at(2), 1)),
                    bind(A.Id.Var(t.at(3), "y"), num(t.at(4), 2)),
                ],
                body=binary(
                    A.BinaryOp.Plus,
                    A.Id.VarRef(t.at(5), "x"),
                    A.Id.VarRef(t.at(6), "y"),
                ),
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
                    num(t.at(2), 1),
                    true(t.at(3)),
                    A.Str(t.at(4), "3"),
                ],
            ),
        )

    def test_binary(self):
        for op in A.BinaryOp:
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
                binary(
                    op,
                    A.Id.VarRef(t.at(1), "a"),
                    A.Id.VarRef(t.at(2), "b"),
                ),
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
            binary(
                A.BinaryOp.Plus,
                A.Id.VarRef(t.at(1), "a"),
                A.Object(t.at(2)),
            ),
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

        self.assertAstEqual(
            t.body,
            binary(
                A.BinaryOp.Plus,
                A.Id.VarRef(t.at(1), "a"),
                binary(
                    A.BinaryOp.Multiply,
                    A.Id.VarRef(t.at(2), "b"),
                    A.Id.VarRef(t.at(3), "c"),
                ),
            ),
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
                op=A.BinaryOp.Multiply,
                lhs=binary(
                    A.BinaryOp.Plus,
                    A.Id.VarRef(t.at(1), "a"),
                    A.Id.VarRef(t.at(2), "b"),
                ),
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
                            num(t.at(6), 1),
                            num(t.at(7), 2),
                        ],
                    ),
                ),
                comp_spec=[
                    A.IfSpec(
                        t.at(8),
                        condition=binary(
                            A.BinaryOp.GT,
                            A.Id.VarRef(t.at(9), "x"),
                            num(t.at(10), 3),
                        ),
                    )
                ],
            ),
        )

    def test_fn(self):
        t = FakeDocument(
            dedent(
                """\
                function(x, y = 2) x + y
                ^1:      ^2 ^3  ^4 ^5  ^:1,6
                """
            )
        )

        self.assertAstEqual(
            t.body,
            A.Fn(
                t.at(1),
                params=[
                    param(A.Id.Var(t.at(2), "x")),
                    param(A.Id.Var(t.at(3), "y"), default=num(t.at(4), 2)),
                ],
                body=binary(
                    A.BinaryOp.Plus,
                    A.Id.VarRef(t.at(5), "x"),
                    A.Id.VarRef(t.at(6), "y"),
                ),
            ),
        )

    def test_fn_no_params(self):
        t = FakeDocument(
            dedent(
                """\
                function() 1
                ^1:        ^:1,2
                """
            )
        )

        self.assertAstEqual(
            t.body,
            A.Fn(
                t.at(1),
                params=[],
                body=num(t.at(2), 1),
            ),
        )

    def test_import(self):
        t = FakeDocument(
            dedent(
                """\
                import 'test.jsonnet'
                ^1:    ^^^^^^^^^^^^^^:1,2
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
                ^1:       ^^^^^:1,2
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
                ^1:       ^^^^^^^^^^^^^^:1,2
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
            assert_expr(
                A.Assert(t.at(1), condition=true(t.at(2))),
                false(t.at(3)),
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
            assert_expr(
                A.Assert(
                    t.at(3),
                    condition=true(t.at(1)),
                    message=A.Str(t.at(2), "never"),
                ),
                false(t.at(4)),
            ),
        )

    def test_assert_expr_in_bind(self):
        t = FakeDocument(
            dedent(
                """\
                local x =
                ^1:   ^2
                    assert true;
                    ^3:    ^^^^:3,4
                    false;
                    ^^^^^5
                x
                ^:1,6
                """
            )
        )

        self.assertAstEqual(
            self.query_one(t, "assert"),
            assert_expr(
                A.Assert(t.at(3), condition=true(t.at(4))),
                false(t.at(5)),
            ),
        )

        self.assertAstEqual(
            t.body,
            A.Local(
                t.at(1),
                binds=[
                    bind(
                        A.Id.Var(t.at(2), "x"),
                        assert_expr(
                            A.Assert(t.at(3), condition=true(t.at(4))),
                            false(t.at(5)),
                        ),
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
                assert true;    assert false;    x
                ^1:    ^^^^:1,4 ^2:    ^^^^^:2,5 ^3
                """
            )
        )

        assert1 = A.Assert(t.at(1), condition=true(t.at(4)))
        assert2 = A.Assert(t.at(2), condition=false(t.at(5)))

        self.assertAstEqual(
            t.body,
            assert_expr(
                assert1,
                assert_expr(
                    assert2,
                    A.Id.VarRef(t.at(3), "x"),
                ),
            ),
        )

    def test_object_field_name(self):
        t1 = FakeDocument(
            dedent(
                """\
                local x = 'f'; { [x]: 1 }
                                  ^1
                                 ^^^2
                """
            )
        )

        self.assertAstEqual(
            t1.node_at(2).to(A.ComputedKey),
            A.ComputedKey(t1.at(2), expr=A.Id.VarRef(t1.at(1), "x")),
        )

        t2 = FakeDocument(
            dedent(
                """\
                { x: 1 }
                  ^1
                """
            )
        )

        self.assertAstEqual(
            self.query_one(t2, "field_key"),
            fixed_key(t2.at(1), "x"),
        )

        t3 = FakeDocument(
            dedent(
                """\
                { 'x': 1 }
                  ^^^1
                """
            )
        )

        self.assertAstEqual(
            self.query_one(t3, "field_key"),
            fixed_key(t3.at(1), "x"),
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
            field(
                fixed_key(t.at(2), "x"),
                num(t.at(3), 1),
            ),
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
            field(
                fixed_key(t.at(2), "x"),
                num(t.at(3), 1),
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
            field(
                fixed_key(t.at(3), "func"),
                A.Fn(
                    t.at(2),
                    params=[
                        param(A.Id.Var(t.at(4), "p")),
                        param(A.Id.Var(t.at(5), "q"), default=num(t.at(6), 0)),
                    ],
                    body=binary(
                        A.BinaryOp.Plus,
                        A.Id.VarRef(t.at(7), "p"),
                        A.Id.VarRef(t.at(8), "q"),
                    ),
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
            field(
                fixed_key(t.at(3), "f"),
                A.Fn(
                    t.at(2),
                    params=[],
                    body=num(t.at(4), 1),
                ),
                visibility=A.Visibility.Hidden,
            ),
        )

    def test_fn_body_with_assert(self):
        t = FakeDocument(
            dedent(
                """\
                function() assert true;    1
                ^1:        ^2:    ^^^^:2,4 ^:1,3
                """
            )
        )

        self.assertAstEqual(
            t.body.to(A.Fn),
            A.Fn(
                t.at(1),
                params=[],
                body=assert_expr(
                    A.Assert(t.at(2), condition=true(t.at(4))),
                    num(t.at(3), 1),
                ),
            ),
        )

    def test_fn_field_body_with_assert(self):
        t = FakeDocument(
            dedent(
                """\
                { f(): assert true;    1 }
                       ^1:    ^^^^:1,2 ^3
                """
            )
        )

        self.assertAstEqual(
            self.query_one(t, "assert"),
            assert_expr(
                A.Assert(t.at(1), condition=true(t.at(2))),
                num(t.at(3), 1),
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
                    ^8:    ^^^^:8,9
                    for x in [2, 3]
                        ^10   ^11^12
                    ^13:     ^^^^^^:13,14
                    if x + y < 4
                       ^15 ^16 ^17
                    ^^^^^^^^^^^^18
                }
                """
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

        self.assertAstEqual(
            t.body,
            A.ObjComp(
                location=t.body.location,
                field=field(key, value, A.Visibility.Hidden),
                binds=[
                    bind(A.Id.Var(t.at(1), "x"), num(t.at(2), 1)),
                ],
                asserts=[A.Assert(t.at(8), condition=true(t.at(9)))],
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

        bind_x = bind(var, num(t.at(7), 1))
        self.assertAstEqual(t.node_at(t.start_of(5)), bind_x)

        local = A.Local(t.at(2), binds=[bind_x], body=A.Id.VarRef(t.at(8), "x"))
        self.assertAstEqual(t.node_at(t.start_of(2)), local)
        self.assertAstEqual(t.node_at(t.end_of(6)), local)

        field_f = field(fixed_key(t.at(1), "f"), local)
        self.assertAstEqual(t.node_at(t.end_of(3)), field_f)

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
            field(
                fixed_key(t.at(2), "g"),
                get_field(
                    A.Dollar(t.at(3)),
                    A.Id.FieldRef(t.at(4), "f"),
                ),
            ),
        )
