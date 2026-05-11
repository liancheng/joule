from typing import Callable

import joule.trees as T


class Visitor:
    def visit(self, tree: T.Tree):
        match tree:
            case T.Array():
                self.visit_array(tree)
            case T.AssertExpr():
                self.visit_assert_expr(tree)
            case T.Binary():
                self.visit_binary(tree)
            case T.Bool():
                self.visit_bool(tree)
            case T.Call():
                self.visit_call(tree)
            case T.Document():
                self.visit_document(tree)
            case T.Dollar():
                self.visit_dollar(tree)
            case T.FieldAccess():
                self.visit_field_access(tree)
            case T.Fn():
                self.visit_fn(tree)
            case T.Id.VarRef():
                self.visit_var_ref(tree)
            case T.If():
                self.visit_if(tree)
            case T.Import():
                self.visit_import(tree)
            case T.ListComp():
                self.visit_list_comp(tree)
            case T.Local():
                self.visit_local(tree)
            case T.Null():
                self.visit_null(tree)
            case T.Num():
                self.visit_num(tree)
            case T.ObjComp():
                self.visit_obj_comp(tree)
            case T.Object():
                self.visit_object(tree)
            case T.Self():
                self.visit_self(tree)
            case T.Slice():
                self.visit_slice(tree)
            case T.Str():
                self.visit_str(tree)
            case T.Super():
                self.visit_super(tree)
            case T.Unary():
                self.visit_unary(tree)
            case _:
                raise RuntimeError(f"Unrecorgnized tree node:\n{tree.pretty}")

    def visit_arg(self, a: T.Arg):
        if a.id is not None:
            self.visit(a.id)
        self.visit(a.value)

    def visit_array(self, e: T.Array):
        for v in e.values:
            self.visit(v)

    def visit_assert(self, a: T.Assert):
        self.visit(a.condition)
        if a.message is not None:
            self.visit(a.message)

    def visit_assert_expr(self, e: T.AssertExpr):
        self.visit_assert(e.assertion)
        self.visit(e.body)

    def visit_binary(self, e: T.Binary):
        self.visit(e.lhs)
        self.visit(e.rhs)

    def visit_bind(self, b: T.Bind):
        self.visit(b.value)

    def visit_bool(self, e: T.Bool):
        del e

    def visit_call(self, e: T.Call):
        self.visit(e.callee)
        for a in e.args:
            self.visit_arg(a)

    def visit_comp_spec(self, s: list[T.CompSpec], next: Callable[[], None]):
        match s:
            case []:
                next()
            case T.ForSpec() as first, *rest:
                self.visit_for_spec(first, lambda: self.visit_comp_spec(rest, next))
            case T.IfSpec() as first, *rest:
                self.visit_if_spec(first, lambda: self.visit_comp_spec(rest, next))

    def visit_computed_key(self, f: T.Field, k: T.ComputedKey):
        del f
        self.visit(k.expr)

    def visit_document(self, e: T.Document):
        self.visit(e.body)

    def visit_dollar(self, e: T.Dollar):
        del e

    def visit_field_access(self, e: T.FieldAccess):
        self.visit(e.obj)
        self.visit(e.field)

    def visit_field_value(self, f: T.Field):
        self.visit(f.value)

    def visit_fixed_key(self, e: T.Object, f: T.Field, k: T.FixedKey):
        del e, f
        self.visit(k.id)

    def visit_fn(self, e: T.Fn):
        for p in e.params:
            self.visit_param(p)
        self.visit(e.body)

    def visit_for_spec(self, s: T.ForSpec, next: Callable[[], None]):
        self.visit(s.source)
        next()

    def visit_if(self, e: T.If):
        self.visit(e.condition)
        self.visit(e.consequence)
        if e.alternative is not None:
            self.visit(e.alternative)

    def visit_if_spec(self, s: T.IfSpec, next: Callable[[], None]):
        self.visit(s.condition)
        next()

    def visit_import(self, e: T.Import):
        self.visit_str(e.importee)

    def visit_list_comp(self, e: T.ListComp):
        self.visit_comp_spec(
            [e.for_spec] + e.extra_specs,
            lambda: self.visit(e.expr),
        )

    def visit_local(self, e: T.Local):
        for b in e.binds:
            self.visit_bind(b)
        self.visit(e.body)

    def visit_null(self, e: T.Null):
        del e

    def visit_num(self, e: T.Num):
        del e

    def visit_obj_comp(self, e: T.ObjComp):
        def next():
            self.visit_computed_key(e.field, e.field.key.to(T.ComputedKey))
            for b in e.binds:
                self.visit_bind(b)
            for a in e.asserts:
                self.visit_assert(a)
            self.visit(e.field.value)

        self.visit_comp_spec([e.for_spec] + e.extra_specs, next)

    def visit_object(self, e: T.Object):
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
                case T.FixedKey() as key:
                    self.visit_fixed_key(e, f, key)
                case T.ComputedKey() as key:
                    self.visit_computed_key(f, key)

        for b in e.binds:
            self.visit_bind(b)

        for a in e.asserts:
            self.visit_assert(a)

        for f in e.fields:
            self.visit_field_value(f)

    def visit_param(self, p: T.Param):
        if p.default is not None:
            self.visit(p.default)

    def visit_self(self, e: T.Self):
        del e

    def visit_slice(self, e: T.Slice):
        self.visit(e.obj)

        if e.start is not None:
            self.visit(e.start)

        if e.stop is not None:
            self.visit(e.stop)

        if e.step is not None:
            self.visit(e.step)

    def visit_str(self, e: T.Str):
        del e

    def visit_super(self, e: T.Super):
        del e

    def visit_unary(self, e: T.Unary):
        self.visit(e.operand)

    def visit_var_ref(self, e: T.Id.VarRef):
        del e
