from contextlib import contextmanager
from typing import Callable

from joule.ast import (
    Bind,
    ComputedKey,
    Document,
    Field,
    FixedKey,
    Fn,
    ForSpec,
    Id,
    Local,
    ObjComp,
    Object,
    Scope,
)
from joule.visitor import Visitor


class ScopeResolver(Visitor):
    def resolve(self, tree: Document) -> Document:
        self.var_scope: Scope = Scope(tree)
        tree.set_var_scope(self.var_scope)
        self.visit(tree)
        return tree

    @contextmanager
    def activate_var_scope(self, scope: Scope):
        prev = self.var_scope
        self.var_scope = scope
        try:
            yield self.var_scope
        finally:
            self.var_scope = prev

    def visit_local(self, e: Local):
        with self.activate_var_scope(self.var_scope.nest(owner=e)) as scope:
            e.set_var_scope(scope)

            for b in e.binds:
                self.visit_bind(b)

            self.visit(e.body)

    def visit_bind(self, b: Bind):
        self.var_scope.bind_var(b.id, b.value)
        with self.activate_var_scope(self.var_scope.nest(owner=b)):
            self.visit(b.value)

    def visit_var_ref(self, e: Id.VarRef):
        e.bound_in = self.var_scope

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
        with self.activate_var_scope(self.var_scope.nest(owner=e)) as scope:
            e.set_var_scope(scope)

            for p in e.params:
                self.var_scope.bind_var(p.id, p)

            for p in e.params:
                if p.default is not None:
                    self.visit(p.default)

            self.visit(e.body)

    def visit_fixed_key(self, e: Object, f: Field, k: FixedKey):
        assert e.field_scope is not None
        e.field_scope.bind_field(k, f)

    def visit_object(self, e: Object):
        with self.activate_var_scope(self.var_scope.nest(owner=e)) as scope:
            e.set_var_scope(scope)
            e.set_field_scope(Scope.empty(e))
            super().visit_object(e)

    def visit_for_spec(self, s: ForSpec, next: Callable[[], None]):
        self.visit(s.source)
        with self.activate_var_scope(self.var_scope.nest(owner=s)) as scope:
            s.set_var_scope(scope)
            scope.bind_var(s.id, s)
            next()

    def visit_obj_comp(self, e: ObjComp):
        def next():
            self.visit_computed_key(e.field, e.field.key.to(ComputedKey))

            with self.activate_var_scope(self.var_scope.nest(owner=e)) as scope:
                e.set_var_scope(scope)
                for b in e.binds:
                    self.visit_bind(b)
                for a in e.asserts:
                    self.visit_assert(a)
                self.visit(e.field.value)

        self.visit_comp_spec([e.for_spec] + e.comp_spec, next)
