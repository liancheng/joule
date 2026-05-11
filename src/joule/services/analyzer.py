from contextlib import contextmanager
from typing import Callable

import joule.trees as T
from joule.maybe import maybe
from joule.trees.visitor import Visitor


class Analyzer(Visitor):
    """Analyzes semantic information of a document.

    Collects the following semantic information by visiting tree recursively and caches
    collected information in corresponding tree nodes:

    * Variable scopes
    * Object field scopes
    * Importees
    * Field references
    * Function calls
    """

    @classmethod
    def analyze(cls, doc: T.Document) -> T.Document:
        analyzer = cls(doc)
        analyzer.visit(doc)
        doc.top_level_scope = analyzer.var_scope
        doc.analysis_phase = T.AnalysisPhase.ScopeResolved
        return doc

    def __init__(self, doc: T.Document) -> None:
        self.doc: T.Document = doc
        # Tracks the currently active variable scope.
        self.var_scope: T.VarScope = T.VarScope(doc)

    @contextmanager
    def nested_var_scope(self, owner: T.Tree):
        prev = self.var_scope
        self.var_scope = prev.nest(owner)
        try:
            yield self.var_scope
        finally:
            self.var_scope = prev

    def visit_bind(self, b: T.Bind):
        self.var_scope.bind(b.id, b.value)
        with self.nested_var_scope(owner=b):
            self.visit(b.value)

    def visit_call(self, e: T.Call):
        super().visit_call(e)
        self.doc.calls.append(e)

    def visit_field_access(self, e: T.FieldAccess):
        super().visit_field_access(e)
        self.doc.field_refs.append(e.field)

    def visit_fixed_key(self, e: T.Object, f: T.Field, k: T.FixedKey):
        assert e.field_scope is not None
        e.field_scope.bind(k, f)

    def visit_fn(self, e: T.Fn):
        with self.nested_var_scope(owner=e):
            # Binds all parameters before binding default values, if any, so that any
            # default value can reference any parameters in the same parameter list.
            for p in e.params:
                self.var_scope.bind(p.id, p)

            for p in e.params:
                if p.default is not None:
                    self.visit(p.default)

            self.visit(e.body)

    def visit_for_spec(self, s: T.ForSpec, next: Callable[[], None]):
        def new_next():
            with self.nested_var_scope(owner=s) as scope:
                scope.bind(s.id, s)
                next()

        super().visit_for_spec(s, new_next)

    def visit_import(self, e: T.Import):
        self.doc.importees.append(e.importee)

    def visit_local(self, e: T.Local):
        with self.nested_var_scope(owner=e):
            for b in e.binds:
                self.visit_bind(b)

            self.visit(e.body)

    def visit_obj_comp(self, e: T.ObjComp):
        def next():
            self.visit_computed_key(e.field, e.field.key.to(T.ComputedKey))

            with self.nested_var_scope(owner=e):
                for b in e.binds:
                    self.visit_bind(b)
                for a in e.asserts:
                    self.visit_assert(a)
                self.visit(e.field.value)

        self.visit_comp_spec([e.for_spec] + e.extra_specs, next)

    def visit_object(self, e: T.Object):
        with self.nested_var_scope(owner=e):
            e.field_scope = T.FieldScope.empty(e)
            super().visit_object(e)

    def visit_var_ref(self, e: T.Id.VarRef):
        for binding in maybe(self.var_scope.get(e.name)):
            var = binding.id.to(T.Id.Var)
            e.var = var
            var.references.append(e)
