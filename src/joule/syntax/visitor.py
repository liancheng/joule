from collections.abc import Callable

from joule.syntax import trees as T


class Visitor:
    def visit(self, t: T.Tree) -> None:
        match t:
            case T.Arg():
                self.visit_arg(t)
            case T.Assert():
                self.visit_assert(t)
            case T.Bind():
                self.visit_bind(t)
            case T.Document():
                self.visit_document(t)
            case T.Expr():
                self.visit_expr(t)
            case T.Id.Field():
                self.visit_field_id(t)
            case T.Id.FieldRef():
                self.visit_field_ref_id(t)
            case T.Id.ParamRef():
                self.visit_param_ref_id(t)
            case T.Id.Var():
                self.visit_var_id(t)
            case T.Param():
                self.visit_param(t)
            case T.Slice():
                self.visit_slice(t)

    def visit_arg(self, t: T.Arg):
        if t.id is not None:
            self.visit_param_ref_id(t.id)
        self.visit_expr(t.value)

    def visit_array(self, t: T.Array):
        for v in t.values:
            self.visit_expr(v)

    def visit_assert(self, t: T.Assert):
        self.visit_expr(t.condition)
        if t.message is not None:
            self.visit_expr(t.message)

    def visit_assert_expr(self, t: T.AssertedExpr):
        self.visit_assert(t.assertion)
        self.visit_expr(t.body)

    def visit_binary(self, t: T.Binary):
        self.visit_expr(t.lhs)
        self.visit_expr(t.rhs)

    def visit_bind(self, t: T.Bind):
        self.visit_var_id(t.id)
        self.visit_expr(t.value)

    def visit_bool(self, t: T.Bool):
        pass

    def visit_call(self, t: T.Call):
        self.visit_expr(t.fn)
        for a in t.args:
            self.visit_arg(a)

    def visit_computed_key(self, f: T.Field, k: T.ComputedKey):
        del f
        self.visit_expr(k.expr)

    def visit_comp_spec(self, t: list[T.CompSpec], next: Callable[[], None]):
        match t:
            case []:
                next()
            case T.ForSpec() as first, *rest:
                self.visit_for_spec(first, lambda: self.visit_comp_spec(rest, next))
            case T.IfSpec() as first, *rest:
                self.visit_if_spec(first, lambda: self.visit_comp_spec(rest, next))

    def visit_document(self, t: T.Document):
        self.visit_expr(t.body)

    def visit_dollar(self, t: T.Dollar):
        pass

    def visit_error(self, t: T.Error):
        self.visit_expr(t.expr)

    def visit_expr(self, t: T.Expr):
        match t:
            case T.Array():
                self.visit_array(t)
            case T.ArrayComp():
                self.visit_array_comp(t)
            case T.AssertedExpr():
                self.visit_assert_expr(t)
            case T.Binary():
                self.visit_binary(t)
            case T.Bool():
                self.visit_bool(t)
            case T.Call():
                self.visit_call(t)
            case T.Dollar():
                self.visit_dollar(t)
            case T.Error():
                self.visit_error(t)
            case T.FieldAccess():
                self.visit_field_access(t)
            case T.Fn():
                self.visit_fn(t)
            case T.Id.VarRef():
                self.visit_var_ref_id(t)
            case T.If():
                self.visit_if(t)
            case T.Import():
                self.visit_import(t)
            case T.Importee():
                self.visit_importee(t)
            case T.Index():
                self.visit_index(t)
            case T.Local():
                self.visit_local(t)
            case T.Malformed():
                self.visit_malformed(t)
            case T.Null():
                self.visit_null(t)
            case T.Num():
                self.visit_num(t)
            case T.ObjComp():
                self.visit_obj_comp(t)
            case T.Object():
                self.visit_object(t)
            case T.Paren():
                self.visit_paren(t)
            case T.Self():
                self.visit_self(t)
            case T.Str():
                self.visit_str(t)
            case T.Super():
                self.visit_super(t)
            case T.Unary():
                self.visit_unary(t)
            case T.Unknown():
                self.visit_unknown(t)

    def visit_field_access(self, t: T.FieldAccess):
        self.visit_expr(t.target)
        self.visit_field_ref_id(t.field)

    def visit_field_id(self, t: T.Id.Field):
        pass

    def visit_field_value(self, t: T.Field):
        self.visit_expr(t.value)

    def visit_field_ref_id(self, t: T.Id.FieldRef):
        pass

    def visit_fn(self, t: T.Fn):
        for p in t.params:
            self.visit_param(p)
        self.visit_expr(t.body)

    def visit_for_spec(self, t: T.ForSpec, next: Callable[[], None]):
        self.visit_var_id(t.id)
        self.visit_expr(t.source)
        next()

    def visit_if(self, t: T.If):
        self.visit_expr(t.condition)
        self.visit_expr(t.consequence)
        if t.alternative is not None:
            self.visit_expr(t.alternative)

    def visit_if_spec(self, t: T.IfSpec, next: Callable[[], None]):
        self.visit_expr(t.condition)
        next()

    def visit_import(self, t: T.Import):
        self.visit_importee(t.importee)

    def visit_importee(self, t: T.Importee):
        pass

    def visit_index(self, t: T.Index):
        self.visit_expr(t.target)
        self.visit(t.index)

    def visit_array_comp(self, t: T.ArrayComp):
        self.visit_comp_spec(
            [t.for_spec] + t.extra_specs,
            next=lambda: self.visit_expr(t.expr),
        )

    def visit_local(self, t: T.Local):
        for b in t.binds:
            self.visit_bind(b)
        self.visit_expr(t.body)

    def visit_malformed(self, t: T.Malformed):
        pass

    def visit_null(self, t: T.Null):
        pass

    def visit_num(self, t: T.Num):
        pass

    def visit_obj_comp(self, t: T.ObjComp):
        def next():
            self.visit_computed_key(t.field, t.field.key.to(T.ComputedKey))
            for b in t.binds:
                self.visit_bind(b)
            self.visit(t.field.value)

        self.visit_comp_spec([t.for_spec] + t.extra_specs, next)

    def visit_object(self, t: T.Object):
        # The following traversal order is important:
        #
        #  * Field keys
        #  * Object local bindings
        #  * Object local assertions
        #  * Field values
        #
        # This is because the scope of Jsonnet object local bindings does not cover
        # computed field keys, but covers assertions and field values.
        for f in t.fields:
            match f.key:
                case T.StaticKey():
                    self.visit_static_key(t, f, f.key)
                case _:
                    self.visit_computed_key(f, f.key)

        for b in t.binds:
            self.visit_bind(b)

        for a in t.asserts:
            self.visit_assert(a)

        for f in t.fields:
            self.visit_field_value(f)

    def visit_param(self, t: T.Param):
        self.visit_var_id(t.id)
        if t.default is not None:
            self.visit_expr(t.default)

    def visit_param_ref_id(self, t: T.Id.ParamRef):
        pass

    def visit_paren(self, t: T.Paren):
        self.visit_expr(t.expr)

    def visit_self(self, t: T.Self):
        pass

    def visit_slice(self, t: T.Slice):
        if t.start is not None:
            self.visit_expr(t.start)
        if t.end is not None:
            self.visit_expr(t.end)
        if t.step is not None:
            self.visit_expr(t.step)

    def visit_static_key(self, obj: T.Object, f: T.Field, k: T.StaticKey):
        del obj, f
        self.visit_field_id(k.id)

    def visit_str(self, t: T.Str):
        pass

    def visit_super(self, t: T.Super):
        pass

    def visit_unary(self, t: T.Unary):
        self.visit_expr(t.operand)

    def visit_unknown(self, t: T.Unknown):
        pass

    def visit_var_id(self, t: T.Id.Var):
        pass

    def visit_var_ref_id(self, t: T.Id.VarRef):
        pass
