from typing import Callable

from joule import ast as A


class Visitor:
    def visit(self, tree: A.AST):
        match tree:
            case A.Array():
                self.visit_array(tree)
            case A.AssertExpr():
                self.visit_assert_expr(tree)
            case A.Binary():
                self.visit_binary(tree)
            case A.Bool():
                self.visit_bool(tree)
            case A.Call():
                self.visit_call(tree)
            case A.Document():
                self.visit_document(tree)
            case A.Dollar():
                self.visit_dollar(tree)
            case A.FieldAccess():
                self.visit_field_access(tree)
            case A.Fn():
                self.visit_fn(tree)
            case A.Id.VarRef():
                self.visit_var_ref(tree)
            case A.If():
                self.visit_if(tree)
            case A.Import():
                self.visit_import(tree)
            case A.ListComp():
                self.visit_list_comp(tree)
            case A.Local():
                self.visit_local(tree)
            case A.Num():
                self.visit_num(tree)
            case A.ObjComp():
                self.visit_obj_comp(tree)
            case A.Object():
                self.visit_object(tree)
            case A.Self():
                self.visit_self(tree)
            case A.Slice():
                self.visit_slice(tree)
            case A.Str():
                self.visit_str(tree)
            case A.Super():
                self.visit_super(tree)

    def visit_arg(self, a: A.Arg):
        if a.id is not None:
            self.visit(a.id)
        self.visit(a.value)

    def visit_array(self, e: A.Array):
        for v in e.values:
            self.visit(v)

    def visit_assert(self, a: A.Assert):
        self.visit(a.condition)
        if a.message is not None:
            self.visit(a.message)

    def visit_assert_expr(self, e: A.AssertExpr):
        self.visit_assert(e.assertion)
        self.visit(e.body)

    def visit_binary(self, e: A.Binary):
        self.visit(e.lhs)
        self.visit(e.rhs)

    def visit_bind(self, b: A.Bind):
        self.visit(b.value)

    def visit_bool(self, e: A.Bool):
        del e

    def visit_call(self, e: A.Call):
        self.visit(e.fn)
        for a in e.args:
            self.visit_arg(a)

    def visit_comp_spec(self, s: A.CompSpec, next: Callable[[], None]):
        match s:
            case []:
                next()
            case A.ForSpec() as first, *rest:
                self.visit_for_spec(first, lambda: self.visit_comp_spec(rest, next))
            case A.IfSpec() as first, *rest:
                self.visit_if_spec(first, lambda: self.visit_comp_spec(rest, next))

    def visit_computed_key(self, f: A.Field, k: A.ComputedKey):
        del f
        self.visit(k.expr)

    def visit_document(self, e: A.Document):
        self.visit(e.body)

    def visit_dollar(self, e: A.Dollar):
        del e

    def visit_field_access(self, e: A.FieldAccess):
        self.visit(e.obj)
        self.visit(e.field)

    def visit_field_value(self, f: A.Field):
        self.visit(f.value)

    def visit_fixed_key(self, e: A.Object, f: A.Field, k: A.FixedKey):
        del e, f
        self.visit(k.id)

    def visit_fn(self, e: A.Fn):
        for p in e.params:
            self.visit_param(p)
        self.visit(e.body)

    def visit_for_spec(self, s: A.ForSpec, next: Callable[[], None]):
        self.visit(s.source)
        next()

    def visit_if(self, e: A.If):
        self.visit(e.condition)
        self.visit(e.consequence)
        if e.alternative is not None:
            self.visit(e.alternative)

    def visit_if_spec(self, s: A.IfSpec, next: Callable[[], None]):
        self.visit(s.condition)
        next()

    def visit_import(self, e: A.Import):
        self.visit_str(e.importee)

    def visit_list_comp(self, e: A.ListComp):
        self.visit_comp_spec(
            [e.for_spec] + e.comp_spec,
            lambda: self.visit(e.expr),
        )

    def visit_local(self, e: A.Local):
        for b in e.binds:
            self.visit_bind(b)
        self.visit(e.body)

    def visit_num(self, e: A.Num):
        del e

    def visit_obj_comp(self, e: A.ObjComp):
        def next():
            self.visit_computed_key(e.field, e.field.key.to(A.ComputedKey))
            for b in e.binds:
                self.visit_bind(b)
            for a in e.asserts:
                self.visit_assert(a)
            self.visit(e.field.value)

        self.visit_comp_spec([e.for_spec] + e.comp_spec, next)

    def visit_object(self, e: A.Object):
        # The following traversal order is important:
        #
        #  * Field keys
        #  * Object local bindings
        #  * Object local assertions
        #  * Field values
        #
        # This is because the scope of Jsonnet object local bindings does not cover
        # computed field keys, but covers assertions and field values.
        for f in e.fields:
            match f.key:
                case A.FixedKey() as key:
                    self.visit_fixed_key(e, f, key)
                case A.ComputedKey() as key:
                    self.visit_computed_key(f, key)

        for b in e.binds:
            self.visit_bind(b)

        for a in e.assertions:
            self.visit_assert(a)

        for f in e.fields:
            self.visit_field_value(f)

    def visit_param(self, p: A.Param):
        if p.default is not None:
            self.visit(p.default)

    def visit_self(self, e: A.Self):
        del e

    def visit_slice(self, e: A.Slice):
        self.visit(e.array)
        self.visit(e.begin)

        if e.end is not None:
            self.visit(e.end)

        if e.step is not None:
            self.visit(e.step)

    def visit_str(self, e: A.Str):
        del e

    def visit_super(self, e: A.Super):
        del e

    def visit_var_ref(self, e: A.Id.VarRef):
        del e
