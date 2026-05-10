from functools import reduce
from typing import Any, Sequence

from parsimonious import NodeVisitor
from parsimonious import expressions as E
from parsimonious.nodes import Node
from parsy import Callable

from joule import trees as T
from joule.grammars import load_grammar

from .line_map import LineMap
from .string import StringParser

JSONNET_GRAMMAR = load_grammar("jsonnet.grammar")


def parse_jsonnet(uri: T.URI, source: str, rule: str = "document") -> T.Tree:
    grammar = JSONNET_GRAMMAR if rule == "document" else JSONNET_GRAMMAR.default(rule)
    root = grammar.parse(source)
    return JsonnetParser(uri, root).visit(root)


def parse_document(uri: T.URI, source: str) -> T.Document:
    return parse_jsonnet(uri, source, "document").to(T.Document)


class JsonnetParser(NodeVisitor, LineMap):
    def __init__(self, uri: T.URI, node: Node):
        LineMap.__init__(self, node.full_text)
        self.uri = uri

    def start_of(self, node: Node) -> T.Point:
        return self.point_of(node.start)

    def end_of(self, node: Node) -> T.Point:
        return self.point_of(node.end)

    def span_of(self, node: Node) -> T.Span:
        return T.Span(self.start_of(node), self.end_of(node))

    def generic_visit(self, node: Node, visited_children: Sequence[Any]):
        match node.expr:
            case E.OneOf():
                return visited_children[0]
            case E.Quantifier() as q if q.max == float("inf"):
                return visited_children
            case E.Quantifier() as q if q.min == 0 and q.max == 1:
                return next(iter(visited_children), None)
            case _:
                return node

    def visit_document(self, node: Node, children: Sequence[Any]):
        _, body, _ = children
        return T.Document(self.span_of(node), self.uri, body)

    @staticmethod
    def make_atom(fn: Callable[[T.Span], T.Expr]):
        def apply(self, node: Node, _: Sequence[Node]):
            return fn(self.span_of(node))

        return apply

    visit_dollar = make_atom(T.Dollar)
    visit_null = make_atom(T.Null)
    visit_super = make_atom(T.Super)
    visit_self = make_atom(T.Self)

    @staticmethod
    def make_id(fn: Callable[[T.Span, str], T.Expr]):
        def apply(self, node: Node, children: Sequence[Node]):
            del node
            _, id = children
            return fn(self.span_of(id), id.text)

        return apply

    visit_field_id = make_id(T.Id.Field)
    visit_field_ref_id = make_id(T.Id.FieldRef)
    visit_param_ref_id = make_id(T.Id.ParamRef)
    visit_var_id = make_id(T.Id.Var)
    visit_var_ref_id = make_id(T.Id.VarRef)

    def make_binary_op(self, node: Node, _: Sequence[Any]):
        return T.BinaryOp(node.text)

    visit_multiply = make_binary_op
    visit_divide = make_binary_op
    visit_modulus = make_binary_op

    visit_minus = make_binary_op
    visit_plus = make_binary_op

    visit_shift_left = make_binary_op
    visit_shift_right = make_binary_op

    visit_gt = make_binary_op
    visit_gt_eq = make_binary_op
    visit_lt = make_binary_op
    visit_lt_eq = make_binary_op
    visit_is_in = make_binary_op

    visit_equals = make_binary_op
    visit_not_eq = make_binary_op

    visit_bit_and = make_binary_op
    visit_bit_or = make_binary_op
    visit_bit_xor = make_binary_op

    visit_and = make_binary_op
    visit_or = make_binary_op

    def make_unary(self, node: Node, _: Sequence[Node]):
        def apply(operand: T.Expr) -> T.Unary:
            span = operand.span.merge(self.span_of(node))
            op = T.UnaryOp(node.text)
            return T.Unary(span, op, operand)

        return apply

    visit_bit_not = make_unary
    visit_not = make_unary
    visit_unary_minus = make_unary
    visit_unary_plus = make_unary

    def visit_unary_with_op(self, _: Node, children: Sequence[Any]):
        op_fn, _, operand = children
        return op_fn(operand)

    def make_binary(self, _: Node, children: Sequence[Any]):
        def join(lhs: T.Expr, op_rhs: tuple[T.BinaryOp, T.Expr]):
            op, rhs = op_rhs
            return T.Binary.make(op, lhs, rhs)

        lhs, rhs_list = children
        return reduce(join, rhs_list, lhs)

    def make_binary_rhs(self, node: Node, children: Sequence[Any]):
        del node
        _, op, _, rhs = children
        return op, rhs

    visit_mul_op = make_binary_op
    visit_mul_rhs = make_binary_rhs
    visit_mul_expr = make_binary

    visit_plus_op = make_binary_op
    visit_plus_rhs = make_binary_rhs
    visit_plus_expr = make_binary

    visit_shift_op = make_binary_op
    visit_shift_rhs = make_binary_rhs
    visit_shift_expr = make_binary

    visit_cmp_op = make_binary_op
    visit_cmp_rhs = make_binary_rhs
    visit_cmp_expr = make_binary

    visit_eq_op = make_binary_op
    visit_eq_rhs = make_binary_rhs
    visit_eq_expr = make_binary

    visit_bit_and_rhs = make_binary_rhs
    visit_bit_and_expr = make_binary

    visit_bit_xor_rhs = make_binary_rhs
    visit_bit_xor_expr = make_binary

    visit_bit_or_rhs = make_binary_rhs
    visit_bit_or_expr = make_binary

    visit_and_rhs = make_binary_rhs
    visit_and_expr = make_binary

    visit_or_rhs = make_binary_rhs
    visit_expr = make_binary

    def visit_boolean(self, node: Node, _: Sequence[Any]):
        return T.Bool(self.span_of(node), node.text == "true")

    def visit_decimal_literal(self, node: Node, _: Sequence[Any]):
        return T.Num(self.span_of(node), float(node.text))

    def visit_binary_literal(self, node: Node, _: Sequence[Any]):
        return T.Num(self.span_of(node), float(int(node.text[2:], base=2)))

    def visit_octal_literal(self, node: Node, _: Sequence[Any]):
        return T.Num(self.span_of(node), float(int(node.text[2:], base=8)))

    def visit_hexical_literal(self, node: Node, _: Sequence[Any]):
        return T.Num(self.span_of(node), float(int(node.text[2:], base=16)))

    def visit_inline_string(self, node: Node, _: Sequence[Any]):
        return T.Str(self.span_of(node), StringParser.parse_inline_string(node.text))

    def visit_text_block(self, node: Node, _: Sequence[Any]):
        return T.Str(self.span_of(node), StringParser.parse_text_block(node.text))

    def visit_field_access(self, node: Node, children: Sequence[Any]):
        _, _, _, field_ref = children

        def apply(obj: T.Expr):
            span = obj.span.merge(self.span_of(node))
            return T.FieldAccess(span=span, obj=obj, field=field_ref)

        return apply

    def visit_postfix(self, _: Node, children: Sequence[Any]):
        def join(primary: T.Expr, postfix_fn: Callable[[T.Expr], T.Expr]):
            return postfix_fn(primary)

        primary, postfix_fns = children
        return reduce(join, postfix_fns, primary)

    def visit_postfix_ops(self, _: Node, children: Sequence[Any]):
        return children

    def visit_parenthesized(self, node: Node, children: Sequence[Any]):
        _, _, expr, _, _ = children
        return T.Paren(self.span_of(node), expr)

    def visit_step(self, node: Node, children: Sequence[Any]):
        del node
        _, _, _, step = children
        return step

    def visit_stop_step(self, node: Node, children: Sequence[Any]):
        del node
        _, _, _, stop, step = children
        return stop, step

    def visit_start_stop_step(self, _: Node, children: Sequence[Any]):
        start, (stop, step) = children
        return start, stop, step

    def visit_maybe_stop_step(self, _: Node, children: Sequence[Any]):
        return next(iter(children), (None, None))

    def visit_maybe_start_stop_step(self, _: Node, children: Sequence[Any]):
        return next(iter(children), (None, None, None))

    def visit_slice(self, node: Node, children: Sequence[Any]):
        del node
        _, _, _, (start, stop, step), _, rbracket = children

        def apply(obj: T.Expr) -> T.Slice:
            span = obj.span.merge(self.span_of(rbracket))
            return T.Slice(span, obj, start, stop, step)

        return apply

    def make_delimited_element(self, node: Node, children: Sequence[Any]):
        """Builds 1 delimited element."""
        del node
        _, _, _, expr = children
        return expr

    def make_delimited_elements(self, node: Node, children: Sequence[Any]):
        """Builds 1 or more delimited elements, with or without a trailing delimiter."""
        del node
        head, tail, *_ = children
        return [head, *tail]

    def make_collection(self, node: Node, children: Sequence[Any]):
        """Builds an enclosed collection with zero or more delimited elements, with or
        without a trailing delimiter."""
        del node
        _, _, maybe_elements, _, _ = children
        return maybe_elements or []

    def visit_arg_name(self, node: Node, children: Sequence[Any]):
        del node
        param_ref, *_ = children
        return param_ref

    def visit_arg(self, node: Node, children: Sequence[Any]):
        maybe_id, value = children
        return T.Arg(self.span_of(node), value, maybe_id)

    visit_delimited_arg = make_delimited_element
    visit_args = make_delimited_elements
    visit_arg_list = make_collection

    def visit_call(self, node: Node, children: Sequence[Any]):
        _, arg_list = children

        def apply(callee: T.Expr) -> T.Call:
            span = callee.span.merge(self.span_of(node))
            return T.Call(span, callee=callee, args=arg_list)

        return apply

    def visit_extend(self, node: Node, children: Sequence[Any]):
        del node
        _, rhs = children

        def apply(lhs: T.Expr) -> T.Binary:
            return T.BinaryOp.Plus(lhs, rhs)

        return apply

    def visit_condition(self, node: Node, children: Sequence[Any]):
        del node
        _, condition = children
        return condition

    def visit_consequence(self, node: Node, children: Sequence[Any]):
        del node
        _, _, _, consequence = children
        return consequence

    def visit_alternative(self, node: Node, children: Sequence[Any]):
        del node
        _, _, _, alternative = children
        return alternative

    def visit_conditional(self, node: Node, children: Sequence[Any]):
        _, condition, consequence, maybe_alternative = children
        return T.If(self.span_of(node), condition, consequence, maybe_alternative)

    def visit_assert_message(self, node: Node, children: Sequence[Any]):
        del node
        _, _, _, message = children
        return message

    def visit_assertion(self, node: Node, children: Sequence[Any]):
        _, _, condition, maybe_message = children
        return T.Assert(self.span_of(node), condition, maybe_message)

    def visit_assert_expr(self, node: Node, children: Sequence[Any]):
        assert_, _, _, _, body = children
        return T.AssertExpr(self.span_of(node), assert_, body)

    @staticmethod
    def make_import(import_type: T.ImportType):
        def apply(self, node: Node, children: Sequence[Any]):
            _, _, path = children
            span = self.span_of(node)
            return T.Import(span, import_type, T.Importee.from_string(path))

        return apply

    visit_import_file = make_import(T.ImportType.Default)
    visit_import_str = make_import(T.ImportType.Str)
    visit_import_bin = make_import(T.ImportType.Bin)

    visit_delimited_array_element = make_delimited_element
    visit_array_elements = make_delimited_elements

    def visit_array(self, node: Node, children: Sequence[Any]):
        elements = self.make_collection(node, children)
        return T.Array(self.span_of(node), elements)

    def visit_bind(self, node: Node, children: Sequence[Any]):
        var, _, value = children
        return T.Bind(self.span_of(node), var, value)

    def visit_bind_var(self, node: Node, children: Sequence[Any]):
        del node
        _, _, value = children
        return value

    def visit_bind_fn(self, node: Node, children: Sequence[Any]):
        params, _, _, _, body = children
        return T.Fn(self.span_of(node), params, body)

    visit_delimited_bind = make_delimited_element
    visit_binds = make_delimited_elements

    def visit_local_expr(self, node: Node, children: Sequence[Any]):
        _, _, binds, _, _, _, body = children
        return T.Local(self.span_of(node), binds, body)

    def visit_default(self, node: Node, children: Sequence[Any]):
        del node
        _, _, _, default = children
        return default

    def visit_param(self, _: Node, children: Sequence[Any]):
        var, default = children
        return T.Param.make(var, default)

    visit_delimited_param = make_delimited_element
    visit_params = make_delimited_elements
    visit_param_list = make_collection

    def visit_anonymous_function(self, node: Node, children: Sequence[Any]):
        _, _, params, _, body = children
        return T.Fn(self.span_of(node), params, body)

    def visit_for_spec(self, node: Node, children: Sequence[Any]):
        _, _, var, _, _, _, source = children
        return T.ForSpec(self.span_of(node), var, source)

    def visit_if_spec(self, node: Node, children: Sequence[Any]):
        _, _, condition = children
        return T.IfSpec(self.span_of(node), condition)

    def visit_delimited_spec(self, node: Node, children: Sequence[Any]):
        del node
        _, spec = children
        return spec

    def visit_list_comp(self, node: Node, children: Sequence[Any]):
        _, _, expr, _, for_spec, extra_specs, *_ = children
        return T.ListComp(self.span_of(node), expr, for_spec, extra_specs)

    def visit_computed_key(self, node: Node, children: Sequence[Any]):
        _, _, expr, _, _ = children
        return T.ComputedKey(self.span_of(node), expr)

    def visit_fixed_key(self, node: Node, children: Sequence[Any]):
        match children:
            case [T.Str() as key]:
                return T.FixedKey(key.span, T.Id.Field(key.span, key.value))
            case [T.Id.Field() as key]:
                return T.FixedKey(self.span_of(node), key)
            case _:
                assert False

    def visit_inherited(self, _: Node, children: Sequence[Node]):
        return next(iter(children), None) is not None

    def visit_visibility(self, node: Node, _: Sequence[Node]):
        return T.Visibility(node.text)

    def visit_field_sep(self, node: Node, children: Sequence[Any]):
        del node
        inherited, _, visibility = children
        return inherited, visibility

    def visit_expr_field_value(self, node: Node, children: Sequence[Any]):
        del node
        (inherited, visibility), _, value = children

        def apply(span: T.Span, key: T.FieldKey) -> T.Field:
            return T.Field(span, key, value, inherited, visibility)

        return apply

    def visit_fn_field_value(self, node: Node, children: Sequence[Any]):
        params, _, (inherited, visibility), _, value = children
        fn = T.Fn(self.span_of(node), params, value)

        def apply(span: T.Span, key: T.FieldKey) -> T.Field:
            return T.Field(span, key, fn, inherited, visibility)

        return apply

    def visit_field(self, node: Node, children: Sequence[Any]):
        key, _, value_fn = children
        return value_fn(self.span_of(node), key)

    def visit_object_local(self, node: Node, children: Sequence[Any]):
        del node
        _, _, bind = children
        return bind

    visit_delimited_object_member = make_delimited_element
    visit_object_members = make_delimited_elements

    def visit_object_comp_spec(self, _: Node, children: Sequence[Any]):
        _, for_spec, extra_specs = children
        return for_spec, extra_specs

    def visit_object(self, node: Node, children: Sequence[Any]):
        _, _, members, maybe_comp_spec, _, _ = children

        members = members or []
        binds = []
        asserts = []
        fields = []

        for member in members:
            match member:
                case T.Bind():
                    binds.append(member)
                case T.Assert():
                    asserts.append(member)
                case T.Field():
                    fields.append(member)

        match maybe_comp_spec:
            case T.ForSpec() as for_spec, extra_specs:
                assert len(fields) == 1, (
                    "An object comprehension must have 1 and only 1 field."
                )

                return T.ObjComp(
                    self.span_of(node),
                    field=fields[0],
                    binds=binds,
                    asserts=asserts,
                    for_spec=for_spec,
                    extra_specs=extra_specs,
                )

            case None:
                return T.Object(
                    self.span_of(node),
                    fields=fields,
                    binds=binds,
                    asserts=asserts,
                )

            case _:
                assert False
