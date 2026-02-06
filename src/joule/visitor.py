from typing import Callable

from joule.ast import (
    AST,
    Arg,
    Array,
    Assert,
    AssertExpr,
    Binary,
    Bind,
    Bool,
    Call,
    CompSpec,
    ComputedKey,
    Document,
    Field,
    FieldAccess,
    FixedKey,
    Fn,
    ForSpec,
    Id,
    If,
    IfSpec,
    Import,
    ListComp,
    Local,
    Num,
    ObjComp,
    Object,
    Param,
    Self,
    Slice,
    Str,
    Super,
)


class Visitor:
    def visit(self, tree: AST):
        match tree:
            case Document():
                self.visit_document(tree)
            case Id.VarRef():
                self.visit_var_ref(tree)
            case Str():
                self.visit_str(tree)
            case Num():
                self.visit_num(tree)
            case Bool():
                self.visit_bool(tree)
            case Array():
                self.visit_array(tree)
            case Binary():
                self.visit_binary(tree)
            case Local():
                self.visit_local(tree)
            case Fn():
                self.visit_fn(tree)
            case Call():
                self.visit_call(tree)
            case ListComp():
                self.visit_list_comp(tree)
            case Import():
                self.visit_import(tree)
            case AssertExpr():
                self.visit_assert_expr(tree)
            case If():
                self.visit_if(tree)
            case ObjComp():
                self.visit_obj_comp(tree)
            case Object():
                self.visit_object(tree)
            case FieldAccess():
                self.visit_field_access(tree)
            case Self():
                self.visit_self(tree)
            case Super():
                self.visit_super(tree)

    def visit_document(self, e: Document):
        self.visit(e.body)

    def visit_var_ref(self, e: Id.VarRef):
        del e

    def visit_str(self, e: Str):
        del e

    def visit_num(self, e: Num):
        del e

    def visit_bool(self, e: Bool):
        del e

    def visit_array(self, e: Array):
        for v in e.values:
            self.visit(v)

    def visit_binary(self, e: Binary):
        self.visit(e.lhs)
        self.visit(e.rhs)

    def visit_local(self, e: Local):
        for b in e.binds:
            self.visit_bind(b)
        self.visit(e.body)

    def visit_bind(self, b: Bind):
        self.visit(b.value)

    def visit_fn(self, e: Fn):
        for p in e.params:
            self.visit_param(p)
        self.visit(e.body)

    def visit_param(self, p: Param):
        if p.default is not None:
            self.visit(p.default)

    def visit_call(self, e: Call):
        self.visit(e.fn)
        for a in e.args:
            self.visit_arg(a)

    def visit_arg(self, a: Arg):
        if a.name is not None:
            self.visit(a.name)
        self.visit(a.value)

    def visit_import(self, e: Import):
        self.visit_str(e.path)

    def visit_assert_expr(self, e: AssertExpr):
        self.visit_assert(e.assertion)
        self.visit(e.body)

    def visit_assert(self, a: Assert):
        self.visit(a.condition)
        if a.message is not None:
            self.visit(a.message)

    def visit_if(self, e: If):
        self.visit(e.condition)
        self.visit(e.consequence)
        if e.alternative is not None:
            self.visit(e.alternative)

    def visit_list_comp(self, e: ListComp):
        self.visit_comp_spec(
            [e.for_spec] + e.comp_spec,
            lambda: self.visit(e.expr),
        )

    def visit_obj_comp(self, e: ObjComp):
        def next():
            self.visit_computed_key(e.field, e.field.key.to(ComputedKey))
            for b in e.binds:
                self.visit_bind(b)
            for a in e.asserts:
                self.visit_assert(a)
            self.visit(e.field.value)

        self.visit_comp_spec([e.for_spec] + e.comp_spec, next)

    def visit_comp_spec(self, s: CompSpec, next: Callable[[], None]):
        match s:
            case []:
                next()
            case ForSpec() as first, *rest:
                self.visit_for_spec(first, lambda: self.visit_comp_spec(rest, next))
            case IfSpec() as first, *rest:
                self.visit_if_spec(first, lambda: self.visit_comp_spec(rest, next))

    def visit_for_spec(self, s: ForSpec, next: Callable[[], None]):
        self.visit(s.source)
        next()

    def visit_if_spec(self, s: IfSpec, next: Callable[[], None]):
        self.visit(s.condition)
        next()

    def visit_object(self, e: Object):
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
                case FixedKey() as key:
                    self.visit_fixed_key(e, f, key)
                case ComputedKey() as key:
                    self.visit_computed_key(f, key)

        for b in e.binds:
            self.visit_bind(b)

        for a in e.assertions:
            self.visit_assert(a)

        for f in e.fields:
            self.visit_field_value(f)

    def visit_fixed_key(self, e: Object, f: Field, k: FixedKey):
        del e, f
        self.visit(k.id)

    def visit_computed_key(self, f: Field, k: ComputedKey):
        del f
        self.visit(k.expr)

    def visit_field_value(self, f: Field):
        self.visit(f.value)

    def visit_field_access(self, e: FieldAccess):
        self.visit(e.obj)
        self.visit(e.field)

    def visit_slice(self, e: Slice):
        self.visit(e.array)
        self.visit(e.begin)

        if e.end is not None:
            self.visit(e.end)

        if e.step is not None:
            self.visit(e.step)

    def visit_self(self, e: Self):
        del e

    def visit_super(self, e: Super):
        del e
