from contextlib import contextmanager

from joule.ast import (
    AST,
    Binary,
    Bind,
    Document,
    Field,
    FieldAccess,
    FixedKey,
    Fn,
    ForSpec,
    Id,
    Import,
    Local,
    Object,
    Operator,
    Scope,
    Self,
    Str,
    Super,
)
from joule.util import head_or_none, maybe
from joule.visitor import Visitor


class ScopeBuilder(Visitor):
    def __init__(self, tree: Document) -> None:
        self.tree: Document = tree
        self.current_var_scope: Scope = Scope()
        self.current_self_scope: Scope | None = None
        self.current_super_scope: Scope | None = None

    def build(self) -> AST:
        self.visit(self.tree)
        return self.tree

    @contextmanager
    def var_scope(self, scope: Scope):
        prev = self.current_var_scope
        self.current_var_scope = scope
        try:
            yield self.current_var_scope
        finally:
            self.current_var_scope = prev

    @contextmanager
    def super_scope(self, scope: Scope | None):
        prev = self.current_super_scope
        self.current_super_scope = scope
        try:
            yield self.current_super_scope
        finally:
            self.current_super_scope = prev

    @contextmanager
    def self_scope(self, scope: Scope | None):
        prev = self.current_self_scope
        self.current_self_scope = scope
        try:
            yield self.current_self_scope
        finally:
            self.current_self_scope = prev

    def find_self_scope(self, t: AST, scope: Scope) -> Scope | None:
        match t:
            case Object() if t.field_scope is not None:
                return t.field_scope
            case Document():
                return self.find_self_scope(t.body, Scope())
            case Id():
                return head_or_none(
                    self.find_self_scope(target, binding.scope)
                    for binding in maybe(scope.get(t))
                    for target in maybe(binding.target)
                )
            case Field():
                return head_or_none(
                    self.find_self_scope(t.value, var_scope)
                    for obj in maybe(t.enclosing_obj)
                    for var_scope in maybe(obj.var_scope)
                )
            case FieldAccess():
                return head_or_none(
                    self.find_self_scope(target, binding.scope)
                    for parent_scope in maybe(self.find_self_scope(t.obj, scope))
                    for binding in maybe(parent_scope.get(t.field))
                    for target in maybe(binding.target)
                )
            case Binary(_, _, _, rhs):
                return self.find_self_scope(rhs, self.current_var_scope)
            case Local():
                return head_or_none(
                    self.find_self_scope(t.body, local_scope)
                    for local_scope in maybe(t.var_scope)
                )
            case Binary(_, Operator.Plus, _, rhs):
                return self.find_self_scope(rhs, scope)
            case Self():
                return t.scope
            case Super():
                return t.scope
            case _:
                return None

    def visit_local(self, e: Local):
        for b in e.binds:
            self.visit_bind(b)

        with self.var_scope(self.current_var_scope.nest()) as nested:
            e.var_scope = nested
            self.visit(e.body)

    def visit_bind(self, b: Bind):
        self.current_var_scope.bind(b.id.name, b.id.location, b.value)

        with self.var_scope(self.current_var_scope.nest()):
            self.visit(b.value)

    def visit_fn(self, e: Fn):
        # NOTE: In a Jsonnet function, any parameter's default value expression can
        # reference any other peer parameters, e.g.:
        #
        #   local f(x = y, y, x = z) =
        #       x + y + z;
        #   f(y = 2)
        #
        # This requires all parameters to be bound before traversing any parameter
        # default value expressions. This is also why parameters must be handled in
        # `visit_fn` instead of `visit_param`.
        with self.var_scope(self.current_var_scope.nest()) as scope:
            e.var_scope = scope

            for p in e.params:
                self.current_var_scope.bind(p.id.name, p.id.location, p.default)

            for p in e.params:
                if p.default is not None:
                    self.visit(p.default)

            self.visit(e.body)

    def visit_for_spec(self, s: ForSpec):
        self.current_var_scope.bind(s.id.name, s.id.location, s.container)
        self.visit(s.container)

    def visit_field_key(self, e: Object, f: Field):
        assert e.field_scope is not None

        f.enclosing_obj = e

        match f.key:
            case FixedKey(_, Id(_, name)):
                e.field_scope.bind(name, f.key.location, f)
            case FixedKey(_, Str(_, raw)):
                e.field_scope.bind(raw, f.key.location, f)

    def visit_field_value(self, e: Object, f: Field):
        del e
        self.visit(f.value)

    def visit_import(self, e: Import):
        del e

    def visit_object(self, e: Object):
        e.var_scope = self.current_var_scope
        e.field_scope = Scope.empty()

        with self.self_scope(e.field_scope):
            super().visit_object(e)

    def visit_field_access(self, e: FieldAccess):
        self.visit(e.obj)

    def visit_self(self, e: Self):
        e.scope = self.current_self_scope

    def visit_super(self, e: Super):
        e.scope = self.current_super_scope

    def visit_binary(self, e: Binary):
        self.visit(e.lhs)
        base_self = self.find_self_scope(e.lhs, self.current_var_scope)
        with self.super_scope(base_self):
            self.visit(e.rhs)
