import dataclasses as D
from typing import Callable

from joule import trees as T

from .util import side_by_side

__all__ = [
    "side_by_side",
]


@D.dataclass(frozen=True)
class AnchorDSL(T.Anchor):
    def __repr__(self) -> str:
        return super().__repr__()

    @staticmethod
    def make_atom(fn: Callable[[T.Anchor], T.TreeType]):
        @property
        def apply(self) -> T.TreeType:
            return fn(self)

        return apply

    dollar = make_atom(T.Dollar)
    null = make_atom(T.Null)
    self = make_atom(T.Self)
    super = make_atom(T.Super)

    @staticmethod
    def make_id(fn: Callable[[T.Anchor, str], T.TreeType]):
        def apply(self, name: str) -> T.TreeType:
            return fn(self, name)

        return apply

    field = make_id(T.Id.Field)
    field_ref = make_id(T.Id.FieldRef)
    param_ref = make_id(T.Id.ParamRef)
    var = make_id(T.Id.Var)
    var_ref = make_id(T.Id.VarRef)

    @property
    def true(self) -> T.Bool:
        return T.Bool(self, True)

    @property
    def false(self) -> T.Bool:
        return T.Bool(self, False)

    def num(self, value: int | float) -> T.Num:
        return T.Num(self, float(value))

    def str(self, value: str) -> T.Str:
        return T.Str(self, value)

    def importee(self, path: str) -> T.Importee:
        return T.Importee(self, path)

    def fixed_key(self, name: str) -> T.FixedKey:
        return T.FixedKey(self, self.field(name))

    def param(self, name: str, default: T.Expr | None = None) -> T.Param:
        anchor = self if default is None else self.merge(default.span)
        return T.Param(anchor, self.var(name), default)

    def array(self, *values: T.Expr) -> T.Array:
        return T.Array(self, list(values))


def assert_expr(assertion: T.Assert, body: T.Expr) -> T.AssertExpr:
    return T.AssertExpr(assertion.anchor.merge(body.span), assertion, body)


def bind(var: T.Id.Var, value: T.Expr) -> T.Bind:
    return T.Bind(var.anchor.merge(value.span), var, value)


def get_field(obj: T.Expr, field_ref: T.Id.FieldRef) -> T.FieldAccess:
    return T.FieldAccess(obj.anchor.merge(field_ref.span), obj, field_ref)


def field(
    key: T.FieldKey,
    value: T.Expr,
    inherited: bool = False,
    visibility: T.Visibility = T.Visibility.Default,
) -> T.Field:
    return T.Field(
        key.anchor.merge(value.span),
        key,
        value,
        inherited,
        visibility,
    )


def arg(value: T.Expr, id: T.Id.ParamRef | None = None) -> T.Arg:
    anchor = value.anchor if id is None else id.anchor.merge(value.span)
    return T.Arg(anchor, value, id)
