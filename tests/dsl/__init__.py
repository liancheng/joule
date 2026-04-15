import lsprotocol.types as L

from joule import ast as A

from .fake_document import FakeDocument
from .util import side_by_side

__all__ = [
    "FakeDocument",
    "side_by_side",
]


def true(at: L.Location):
    return A.Bool(at, True)


def false(at: L.Location):
    return A.Bool(at, False)


def num(at: L.Location, value: int | float):
    return A.Num(at, float(value))


def assert_expr(assertion: A.Assert, body: A.Expr) -> A.AssertExpr:
    return A.AssertExpr(A.merge_locations(assertion, body), assertion, body)


def bind(var: A.Id.Var, value: A.Expr) -> A.Bind:
    return A.Bind(A.merge_locations(var, value), var, value)


def param(var: A.Id.Var, default: A.Expr | None = None) -> A.Param:
    location = A.merge_locations(var, default) if default else var.location
    return A.Param(location, var, default)


def binary(op: A.BinaryOp, lhs: A.Expr, rhs: A.Expr) -> A.Binary:
    return A.Binary(A.merge_locations(lhs, rhs), op, lhs, rhs)


def get_field(obj: A.Expr, field_ref: A.Id.FieldRef) -> A.FieldAccess:
    return A.FieldAccess(A.merge_locations(obj, field_ref), obj, field_ref)


def fixed_key(at: L.Location, name: str) -> A.FixedKey:
    return A.FixedKey(at, A.Id.Field(at, name))


def field(
    key: A.FieldKey,
    value: A.Expr,
    visibility: A.Visibility = A.Visibility.Default,
    inherited: bool = False,
) -> A.Field:
    return A.Field(
        A.merge_locations(key, value),
        key,
        value,
        visibility,
        inherited,
    )


def arg(value: A.Expr, id: A.Id.ParamRef | None = None) -> A.Arg:
    return (
        A.Arg(value.location, value)
        if id is None
        else A.Arg(A.merge_locations(id, value), value, id)
    )
