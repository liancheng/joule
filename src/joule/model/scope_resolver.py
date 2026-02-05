from contextlib import contextmanager

from joule.ast import (
    Id,
    Bind,
    Document,
    Field,
    FixedKey,
    Fn,
    ForSpec,
    ListComp,
    Local,
    ObjComp,
    Object,
    Scope,
    Str,
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
        with self.activate_var_scope(self.var_scope.nest(e)) as scope:
            e.set_var_scope(scope)

            for b in e.binds:
                self.visit_bind(b)

            self.visit(e.body)

    def visit_bind(self, b: Bind):
        super().visit_var(b.id)
        self.var_scope.bind(b.id.name, b.id.location, b.value)

        with self.activate_var_scope(self.var_scope.nest(b)):
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
        with self.activate_var_scope(self.var_scope.nest(e)) as scope:
            e.set_var_scope(scope)

            for p in e.params:
                self.var_scope.bind(p.id.name, p.id.location, p.default)

            for p in e.params:
                if p.default is not None:
                    self.visit(p.default)

            self.visit(e.body)

    def visit_list_comp(self, e: ListComp):
        with self.activate_var_scope(self.var_scope.nest(e)) as scope:
            e.set_var_scope(scope)
            super().visit_list_comp(e)

    def visit_obj_comp(self, e: ObjComp):
        with self.activate_var_scope(self.var_scope.nest(e)) as scope:
            e.set_var_scope(scope)
            super().visit_obj_comp(e)

    def visit_for_spec(self, s: ForSpec):
        self.visit(s.source)
        self.var_scope.bind(s.id.name, s.id.location, s.source)

    def visit_fixed_key(self, e: Object, f: Field, k: FixedKey):
        assert e.field_scope is not None

        match k.id:
            case Id.Field():
                name = k.id.name
            case Str():
                name = k.id.raw

        e.field_scope.bind(name, k.location, f)

    def visit_object(self, e: Object):
        with self.activate_var_scope(self.var_scope.nest(e)) as scope:
            e.set_var_scope(scope)
            e.set_field_scope(Scope.empty(e))
            super().visit_object(e)
