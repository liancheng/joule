from joule import ast as A

from .util import side_by_side

__all__ = [
    "side_by_side",
]


def true(at: A.Anchor):
    return A.Bool(at, True)


def false(at: A.Anchor):
    return A.Bool(at, False)


def num(at: A.Anchor, value: int | float):
    return A.Num(at, float(value))


def assert_expr(assertion: A.Assert, body: A.Expr) -> A.AssertExpr:
    return A.AssertExpr(assertion.anchor.merge(body.anchor), assertion, body)


def bind(var: A.Id.Var, value: A.Expr) -> A.Bind:
    return A.Bind(var.anchor.merge(value.anchor), var, value)


def param(var: A.Id.Var, default: A.Expr | None = None) -> A.Param:
    location = var.anchor.merge(default.anchor) if default else var.anchor
    return A.Param(location, var, default)


def binary(op: A.BinaryOp, lhs: A.Expr, rhs: A.Expr) -> A.Binary:
    return A.Binary(lhs.anchor.merge(rhs.anchor), op, lhs, rhs)


def get_field(obj: A.Expr, field_ref: A.Id.FieldRef) -> A.FieldAccess:
    return A.FieldAccess(obj.anchor.merge(field_ref.anchor), obj, field_ref)


def fixed_key(at: A.Anchor, name: str) -> A.FixedKey:
    return A.FixedKey(at, A.Id.Field(at, name))


def field(
    key: A.FieldKey,
    value: A.Expr,
    visibility: A.Visibility = A.Visibility.Default,
    inherited: bool = False,
) -> A.Field:
    return A.Field(
        key.anchor.merge(value.anchor),
        key,
        value,
        visibility,
        inherited,
    )


def arg(value: A.Expr, id: A.Id.ParamRef | None = None) -> A.Arg:
    return (
        A.Arg(value.anchor, value)
        if id is None
        else A.Arg(id.anchor.merge(value.anchor), value, id)
    )
