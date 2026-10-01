from collections.abc import Callable
from contextlib import contextmanager
from typing import override

from joule import trees as T
from joule.maybe import maybe
from joule.trees.visitor import Visitor


class ScopeResolver(Visitor):
    def __init__(self, doc: T.Document):
        self.doc = doc
        self.var_scope = T.VarScope(doc)

    def resolve(self):
        self.visit(self.doc)
        self.doc.top_level_scope = self.var_scope

    @contextmanager
    def activate(self, scope: T.VarScope):
        prev = self.var_scope
        self.var_scope = scope
        try:
            yield self.var_scope
        finally:
            self.var_scope = prev

    @override
    def visit_bind(self, t: T.Bind):
        self.var_scope.bind(t.id, t.value)
        with self.activate(self.var_scope.nest(owner=t)):
            self.visit(t.value)

    @override
    def visit_fn(self, t: T.Fn):
        # NOTE: Jsonnet function parameter scoping
        #
        # In Jsonnet, function parameters in the same parameter list can reference each
        # other in any order, e.g.:
        #
        #   function(x = z, y = x, z) = x + y + z
        #
        # This requires parameters to be bound before traversing any parameter default
        # value expressions. This is also why parameters must be handled in `visit_fn`
        # instead of `visit_param`.
        with self.activate(self.var_scope.nest(owner=t)):
            for p in t.params:
                self.var_scope.bind(p.id, p)

            for p in t.params:
                if p.default is not None:
                    self.visit(p.default)

            self.visit(t.body)

    @override
    def visit_for_spec(self, t: T.ForSpec, next: Callable[[], None]):
        def new_next():
            with self.activate(self.var_scope.nest(owner=t)) as scope:
                scope.bind(t.id, t)
                next()

        super().visit_for_spec(t, new_next)

    @override
    def visit_local(self, t: T.Local):
        with self.activate(self.var_scope.nest(owner=t)):
            for b in t.binds:
                self.visit_bind(b)
            self.visit(t.body)

    @override
    def visit_obj_comp(self, t: T.ObjComp):
        def next():
            self.visit_computed_key(t, t.field, t.field.key.to(T.ComputedKey))

            with self.activate(self.var_scope.nest(owner=t)):
                for b in t.binds:
                    self.visit_bind(b)
                self.visit(t.field.value)

        self.visit_comp_spec([t.for_spec] + t.extra_specs, next)

    @override
    def visit_object(self, t: T.Object):
        with self.activate(self.var_scope.nest(owner=t)):
            t.field_scope = T.FieldScope.empty(owner=t)
            super().visit_object(t)

    @override
    def visit_static_key(self, obj: T.Object, f: T.Field, k: T.StaticKey):
        assert obj.field_scope is not None
        obj.field_scope.bind(k, f.value)

    @override
    def visit_var_ref_id(self, t: T.Id.VarRef):
        for binding in maybe(self.var_scope.get(t.name)):
            var = binding.id.to(T.Id.Var)
            t.var = var
            var.add_ref(t)
