from contextlib import contextmanager
from typing import Callable

from joule.ast import (
    AnalysisPhase,
    Bind,
    ComputedKey,
    Document,
    Field,
    FieldAccess,
    FieldScope,
    FixedKey,
    Fn,
    ForSpec,
    Id,
    Local,
    ObjComp,
    Object,
    VarScope,
)
from joule.maybe import maybe
from joule.visitor import Visitor


class ScopeResolver(Visitor):
    """An AST visitor that creates scopes and bind variables and object fields."""

    def resolve(self, tree: Document) -> Document:
        self.tree = tree
        self.var_scope: VarScope = VarScope(tree)
        self.visit(tree)

        tree.top_level_scope = self.var_scope
        tree.analysis_phase = AnalysisPhase.ScopeResolved

        return tree

    @contextmanager
    def activate_var_scope(self, scope: VarScope):
        prev = self.var_scope
        self.var_scope = scope
        try:
            yield self.var_scope
        finally:
            self.var_scope = prev

    def visit_bind(self, b: Bind):
        self.var_scope.bind(b.id, b.value)
        with self.activate_var_scope(self.var_scope.nest(owner=b)):
            self.visit(b.value)

    def visit_field_access(self, e: FieldAccess):
        super().visit_field_access(e)
        self.tree.field_refs.append(e.field)

    def visit_fixed_key(self, e: Object, f: Field, k: FixedKey):
        assert e.field_scope is not None
        e.field_scope.bind(k, f)

    def visit_fn(self, e: Fn):
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
        with self.activate_var_scope(self.var_scope.nest(owner=e)):
            for p in e.params:
                self.var_scope.bind(p.id, p)

            for p in e.params:
                if p.default is not None:
                    self.visit(p.default)

            self.visit(e.body)

    def visit_for_spec(self, s: ForSpec, next: Callable[[], None]):
        def new_next():
            with self.activate_var_scope(self.var_scope.nest(owner=s)) as scope:
                scope.bind(s.id, s)
                next()

        super().visit_for_spec(s, new_next)

    def visit_local(self, e: Local):
        with self.activate_var_scope(self.var_scope.nest(owner=e)):
            for b in e.binds:
                self.visit_bind(b)

            self.visit(e.body)

    def visit_obj_comp(self, e: ObjComp):
        def next():
            self.visit_computed_key(e.field, e.field.key.to(ComputedKey))

            with self.activate_var_scope(self.var_scope.nest(owner=e)):
                for b in e.binds:
                    self.visit_bind(b)
                for a in e.asserts:
                    self.visit_assert(a)
                self.visit(e.field.value)

        self.visit_comp_spec([e.for_spec] + e.comp_spec, next)

    def visit_object(self, e: Object):
        with self.activate_var_scope(self.var_scope.nest(owner=e)):
            e.field_scope = FieldScope.empty(e)
            super().visit_object(e)

    def visit_var_ref(self, e: Id.VarRef):
        for binding in maybe(self.var_scope.get(e.name)):
            var = binding.id.to(Id.Var)
            e.var = var
            var.references.append(e)
