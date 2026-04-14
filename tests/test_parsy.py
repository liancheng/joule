from textwrap import dedent
from typing import Callable

import parsy as P

from joule import ast as A

from . import ASTTestCase
from .dsl import FakeDocument, bind, false, num, param, true


class TestParsy(ASTTestCase):
    def assertParsed(
        self,
        doc: FakeDocument,
        parser_fn: Callable[[A.URI], P.Parser],
        expected: A.AST,
    ):
        self.assertAstEqual(parser_fn(doc.uri).parse(doc.source), expected)

    def test_null(self):
        t = FakeDocument("null")
        self.assertParsed(t, A.Null.parser, A.Null(t.location))

    def test_bool(self):
        t = FakeDocument("true")
        self.assertParsed(t, A.Bool.parser, true(t.location))

        t = FakeDocument("false")
        self.assertParsed(t, A.Bool.parser, false(t.location))

    def test_id(self):
        t = FakeDocument("x")
        self.assertParsed(t, A.Id.Var.parser, A.Id.Var(t.location, "x"))
        self.assertParsed(t, A.Id.VarRef.parser, A.Id.VarRef(t.location, "x"))
        self.assertParsed(t, A.Id.Field.parser, A.Id.Field(t.location, "x"))
        self.assertParsed(t, A.Id.FieldRef.parser, A.Id.FieldRef(t.location, "x"))
        self.assertParsed(t, A.Id.ParamRef.parser, A.Id.ParamRef(t.location, "x"))

    def test_num(self):
        t = FakeDocument("-1")
        self.assertParsed(t, A.Num.parser, A.Num(t.location, -1.0))

    def test_binary(self):
        t = FakeDocument(
            dedent(
                """\
                1 + 2
                ^1  ^2
                ^^^^^3
                """
            )
        )

        self.assertParsed(
            t,
            A.Binary.parser,
            A.Binary(
                t.at(3),
                A.BinaryOp.Plus,
                A.Num(t.at(1), 1.0),
                A.Num(t.at(2), 2.0),
            ),
        )

    def test_unary(self):
        t = FakeDocument(
            dedent(
                """\
                !x
                 ^1
                """
            )
        )

        self.assertParsed(
            t,
            A.Unary.parser,
            A.Unary(
                t.location,
                A.UnaryOp.Not,
                A.Id.VarRef(t.at(1), "x"),
            ),
        )

    def test_wrapped_by_empty(self):
        parser = A.enclosed_list(
            element=P.string("x"),
            left=A.lparen,
            sep=A.comma,
            right=A.rparen,
        )

        self.assertSequenceEqual(parser.parse("()"), [])
        self.assertSequenceEqual(parser.parse("( )"), [])
        self.assertSequenceEqual(parser.parse("(x )"), ["x"])
        self.assertSequenceEqual(parser.parse("( x)"), ["x"])
        self.assertSequenceEqual(parser.parse("( x )"), ["x"])
        self.assertSequenceEqual(parser.parse("(x,)"), ["x"])
        self.assertSequenceEqual(parser.parse("(x, )"), ["x"])
        self.assertSequenceEqual(parser.parse("(x ,)"), ["x"])
        self.assertSequenceEqual(parser.parse("(x, x)"), ["x", "x"])
        self.assertSequenceEqual(parser.parse("(x, x,)"), ["x", "x"])

    def test_array_empty(self):
        t = FakeDocument("[]")
        self.assertParsed(t, A.Array.parser, A.Array(t.location, []))

    def test_array_trailing_comma(self):
        t = FakeDocument(
            dedent(
                """\
                [1, 2,]
                 ^1 ^2
                """
            )
        )

        self.assertParsed(
            t,
            A.Array.parser,
            A.Array(
                t.location,
                [
                    num(t.at(1), 1),
                    num(t.at(2), 2),
                ],
            ),
        )

    def test_array_no_trailing_comma(self):
        t = FakeDocument(
            dedent(
                """\
                [1, 2]
                 ^1 ^2
                """
            )
        )

        self.assertParsed(
            t,
            A.Array.parser,
            A.Array(
                t.location,
                [
                    num(t.at(1), 1),
                    num(t.at(2), 2),
                ],
            ),
        )

    def test_bind_var(self):
        t = FakeDocument(
            dedent(
                """\
                x = 1
                ^1  ^2
                ^^^^^3
                """
            )
        )

        self.assertParsed(
            t,
            A.Bind.parser,
            A.Bind(
                t.at(3),
                id=A.Id.Var(t.at(1), "x"),
                value=num(t.at(2), 1),
            ),
        )

    def test_param(self):
        t = FakeDocument(
            dedent(
                """\
                a = 1
                ^1  ^2
                """
            )
        )

        self.assertParsed(
            t,
            A.Param.parser,
            param(
                A.Id.Var(t.at(1), "a"),
                default=num(t.at(2), 1),
            ),
        )

    def test_params(self):
        t = FakeDocument(
            dedent(
                """\
                (a = 1, b, c = 2)
                 ^1  ^2 ^3 ^4  ^5
                """
            )
        )

        self.assertSequenceEqual(
            A.Fn.params_parser(t.uri).parse(t.source),
            [
                param(
                    A.Id.Var(t.at(1), "a"),
                    default=num(t.at(2), 1),
                ),
                param(
                    A.Id.Var(t.at(3), "b"),
                ),
                param(
                    A.Id.Var(t.at(4), "c"),
                    default=num(t.at(5), 2),
                ),
            ],
        )

    def test_bind_fn(self):
        t = FakeDocument(
            dedent(
                """\
                f(p) = p
                ^1^2   ^3
                 ^^^^^^^5
                ^^^^^^^^6
                """
            )
        )

        self.assertParsed(
            t,
            A.Bind.parser,
            A.Bind(
                t.at(6),
                A.Id.Var(t.at(1), "f"),
                A.Fn(
                    t.at(5),
                    params=[A.Param(t.at(2), id=A.Id.Var(t.at(2), "p"))],
                    body=A.Id.VarRef(t.at(3), "p"),
                ),
            ),
        )

    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1, y = 2; x
                      ^1  ^2 ^3  ^4 ^5
                """
            )
        )

        self.assertParsed(
            t,
            A.Local.parser,
            A.Local(
                t.location,
                binds=[
                    bind(A.Id.Var(t.at(1), "x"), num(t.at(2), 1)),
                    bind(A.Id.Var(t.at(3), "y"), num(t.at(4), 2)),
                ],
                body=A.Id.VarRef(t.at(5), "x"),
            ),
        )
