import dataclasses as D
from typing import Callable

from joule import ast as A

from .util import side_by_side

__all__ = [
    "side_by_side",
]


@D.dataclass(frozen=True)
class AnchorDSL(A.Anchor):
    def __repr__(self) -> str:
        return super().__repr__()

    @staticmethod
    def make_atom(fn: Callable[[A.Anchor], A.AstType]):
        @property
        def apply(self) -> A.AstType:
            return fn(self)

        return apply

    dollar = make_atom(A.Dollar)
    null = make_atom(A.Null)
    self = make_atom(A.Self)
    super = make_atom(A.Super)

    @staticmethod
    def make_id(fn: Callable[[A.Anchor, str], A.AstType]):
        def apply(self, name: str) -> A.AstType:
            return fn(self, name)

        return apply

    field = make_id(A.Id.Field)
    field_ref = make_id(A.Id.FieldRef)
    param_ref = make_id(A.Id.ParamRef)
    var = make_id(A.Id.Var)
    var_ref = make_id(A.Id.VarRef)

    @property
    def true(self) -> A.Bool:
        return A.Bool(self, True)

    @property
    def false(self) -> A.Bool:
        return A.Bool(self, False)

    def num(self, value: int | float) -> A.Num:
        return A.Num(self, float(value))

    def str(self, value: str) -> A.Str:
        return A.Str(self, value)

    def importee(self, path: str) -> A.Importee:
        return A.Importee(self, path)

    def fixed_key(self, name: str) -> A.FixedKey:
        return A.FixedKey(self, self.field(name))

    def param(self, name: str, default: A.Expr | None = None) -> A.Param:
        anchor = self if default is None else self.merge(default.span)
        return A.Param(anchor, self.var(name), default)

    def array(self, *values: A.Expr) -> A.Array:
        return A.Array(self, list(values))


def assert_expr(assertion: A.Assert, body: A.Expr) -> A.AssertExpr:
    return A.AssertExpr(assertion.anchor.merge(body.span), assertion, body)


def bind(var: A.Id.Var, value: A.Expr) -> A.Bind:
    return A.Bind(var.anchor.merge(value.span), var, value)


def get_field(obj: A.Expr, field_ref: A.Id.FieldRef) -> A.FieldAccess:
    return A.FieldAccess(obj.anchor.merge(field_ref.span), obj, field_ref)


def field(
    key: A.FieldKey,
    value: A.Expr,
    inherited: bool = False,
    visibility: A.Visibility = A.Visibility.Default,
) -> A.Field:
    return A.Field(
        key.anchor.merge(value.span),
        key,
        value,
        inherited,
        visibility,
    )


def arg(value: A.Expr, id: A.Id.ParamRef | None = None) -> A.Arg:
    anchor = value.anchor if id is None else id.anchor.merge(value.span)
    return A.Arg(anchor, value, id)
