import re
from functools import cached_property, partial, reduce
from typing import Callable

import lsprotocol.types as L
import parsy as P

from joule import ast as A
from joule.ast import BinaryOp as B
from joule.ast import UnaryOp as U


def lookback(parser: P.Parser):
    @P.Parser
    def parse(stream, index) -> P.Result:
        if index < 1:
            return P.Result.failure(index, "not enough items to look back.")
        else:
            result = parser(stream, index - 1)
            if result.status:
                return P.Result.success(index, result.value)
            else:
                return result

    return parse


inline_whitespace = P.char_from(" \t").desc("inline whitespace")

whitespace = (
    P.whitespace.at_least(1)
    # Single-line comment
    | P.regex(r"(//|#)[^\n]*")
    # C-style multi-line comment
    | P.regex(r"/\*.*\*/", re.DOTALL)
).desc("whitespace")

word_char = P.regex("[_0-9a-zA-Z]")

blank = whitespace.at_least(1).desc("blank")
maybe_blank = (lookback(word_char) << P.peek(word_char) << blank) | whitespace.many()

dot = P.string(".")
dot_sep = maybe_blank << dot << maybe_blank

lparen = P.string("(")
rparen = P.string(")")

lbracket = P.string("[")
rbracket = P.string("]")

lbrace = P.string("{")
rbrace = P.string("}")

comma = P.string(",")
comma_sep = maybe_blank << comma << maybe_blank

colon = P.string(":")
colon_sep = maybe_blank << colon << maybe_blank

semicolon = P.string(";")
semicolon_sep = maybe_blank << semicolon << maybe_blank

eq = P.string("=")
eq_sep = maybe_blank << eq << maybe_blank

in_ = P.string("in")
in_sep = maybe_blank << in_ << maybe_blank

if_ = P.string("if")
then_ = P.string("then")
else_ = P.string("else")
for_ = P.string("for")
local = P.string("local")

newline = P.string("\n").desc("newline")


def decode_codepoint(esc: str) -> str:
    high = int(esc[2:6], 16)
    low = int(esc[8:12], 16) if len(esc) == 12 else None

    if 0xD800 <= high <= 0xDFFF:
        # High 16 bit as surrogate: non-BMP code point
        assert low is not None, "Invalid escaped non-BMP code point"
        return chr(0x10000 + (high - 0xD800) * 0x400 + (low - 0xDC00))
    elif low is None:
        # BMP code point
        return chr(high)
    else:
        return chr(high) + chr(low)


codepoint_esc = P.regex(r"\\u[0-9a-fA-F]{4}(\\u[0-9a-fA-F]{4})?").map(decode_codepoint)

single_char_esc = P.alt(
    *(
        P.string(f"\\{esc}").result(value)
        for esc, value in zip("\"'\\/bnfrt", "\"'\\/\b\n\f\r\t")
    )
)

keywords = [
    "assert",
    "else",
    "error",
    "false",
    "for",
    "function",
    "if",
    "import",
    "importstr",
    "importbin",
    "in",
    "local",
    "null",
    "tailstrict",
    "then",
    "self",
    "super",
    "true",
]


def enclosed(element: P.Parser, open: P.Parser, sep: P.Parser, close: P.Parser):
    @P.generate
    def gen():
        open_ = yield open << maybe_blank
        elements = yield (element << maybe_blank << sep << maybe_blank).many()
        last = yield (element << maybe_blank).map(lambda e: [e]).optional([])
        close_ = yield close
        elements.extend(last)
        return open_, elements, close_

    return gen


LineInfo = tuple[int, int]

PostfixBuilder = Callable[[L.Location, A.AST], A.AST]

AtomBuilder = Callable[[L.Location], A.AST]

IdBuilder = Callable[[L.Location, str], A.AST]

ObjMember = A.Assert | A.Field | A.Bind


class Parser:
    def __init__(self, uri: A.URI) -> None:
        self.uri = uri

    def _atom(self, pattern: str, fn: AtomBuilder):
        return P.seq(
            P.line_info,
            P.string(pattern),
            P.line_info,
        ).combine(lambda start, _, end: fn(self._location(start, end)))

    def _id(self, fn: IdBuilder):
        not_keywords = f"(?!{'|'.join(keywords)})"

        def make_id(start, name, end):
            return fn(self._location(start, end), name)

        return P.seq(
            P.line_info,
            P.regex(rf"{not_keywords}[_a-zA-Z][_a-zA-Z0-9]*"),
            P.line_info,
        ).combine(make_id)

    def left_binary(self, operand: P.Parser, *operators: A.BinaryOp | A.UnaryOp):
        operator = P.alt(*map(self.operator, operators))

        @P.generate
        def gen():
            start = yield P.line_info
            lhs = yield operand
            maybe_operator = (maybe_blank >> operator).optional()

            op = yield maybe_operator
            while op is not None:
                rhs = yield maybe_blank >> operand
                end = yield P.line_info
                lhs = A.Binary(self._location(start, end), op, lhs, rhs)
                op = yield maybe_operator

            return lhs

        return gen

    def _position(self, pos: LineInfo) -> L.Position:
        line, char = pos
        return L.Position(line, char)

    def _location(self, start, end) -> L.Location:
        return L.Location(self.uri, L.Range(self._position(start), self._position(end)))

    def _op_from(self, *ops: A.BinaryOp | A.UnaryOp):
        return P.alt(*map(self.operator, ops))

    @cached_property
    def and_expr(self):
        return self.left_binary(self.bitor_expr, B.And).desc("and_expr")

    @cached_property
    def arg(self):
        @P.generate
        def gen():
            start = yield P.line_info
            id = yield (self.param_ref_id << eq_sep).optional()
            value = yield self.expr
            end = yield P.line_info
            return A.Arg(self._location(start, end), value, id)

        return gen.desc(A.Arg.__name__)

    @cached_property
    def array(self):
        @P.generate
        def gen():
            start = yield P.line_info
            _, values, _ = yield enclosed(self.expr, lbracket, comma, rbracket)
            end = yield P.line_info
            return A.Array(self._location(start, end), values)

        return gen.desc(A.Array.__name__)

    @cached_property
    def assert_(self):
        @P.generate
        def gen():
            start = yield P.line_info
            yield P.string("assert")
            condition = yield self.expr
            message = yield (colon_sep >> self.expr).optional()
            end = yield P.line_info
            return A.Assert(self._location(start, end), condition, message)

        return gen.desc(A.Assert.__name__)

    @cached_property
    def assert_expr(self):
        @P.generate
        def gen():
            start = yield P.line_info
            assertion = yield self.assert_ << semicolon_sep
            body = yield self.expr
            end = yield P.line_info
            return A.AssertExpr(self._location(start, end), assertion, body)

        return gen.desc(A.AssertExpr.__name__)

    @cached_property
    def bitand_expr(self):
        return self.left_binary(self.eq_expr, B.BitAnd)

    @cached_property
    def bitor_expr(self):
        return self.left_binary(self.bitxor_expr, B.BitOr)

    @cached_property
    def bitxor_expr(self):
        return self.left_binary(self.bitand_expr, B.BitXor)

    @cached_property
    def bind(self):
        @P.generate
        def function():
            start = yield P.line_info
            params = yield self.params
            yield eq_sep
            body = yield self.expr
            end = yield P.line_info
            return A.Fn(self._location(start, end), params, body)

        @P.generate
        def gen():
            start = yield P.line_info
            id = yield self.var_id
            value = yield (eq_sep >> self.expr) | function
            end = yield P.line_info
            return A.Bind(self._location(start, end), id, value)

        return gen.desc(A.Bind.__name__)

    @cached_property
    def boolean(self):
        true = self._atom("true", partial(A.Bool, value=True)).desc("true")
        false = self._atom("false", partial(A.Bool, value=False)).desc("false")
        return (true | false).desc(A.Bool.__name__)

    @cached_property
    def cmp_expr(self):
        return self.in_expr | self.left_binary(self.shift_expr, B.LE, B.GE, B.LT, B.GT)

    @cached_property
    def comp_spec(self):
        @P.generate
        def gen():
            for_spec = yield self.for_spec
            specs = yield (maybe_blank >> (self.if_spec | self.for_spec)).many()
            specs.insert(0, for_spec)
            return specs

        return gen

    @cached_property
    def document(self):
        @P.generate
        def gen():
            body: A.Expr = yield maybe_blank >> self.expr << maybe_blank
            return A.Document(body.location, body)

        return gen

    @cached_property
    def dollar(self):
        return self._atom("$", A.Dollar).desc(A.Dollar.__name__)

    @cached_property
    def eq_expr(self):
        return self.left_binary(self.cmp_expr, B.Eq, B.NotEq)

    @cached_property
    def expr(self):
        return self.left_binary(self.and_expr, B.Or)

    @cached_property
    def field_id(self):
        return self._id(A.Id.Field).desc(A.Id.Field.__name__)

    @cached_property
    def field_key(self):
        @P.generate
        def computed_key():
            start = yield P.line_info
            yield lbracket << maybe_blank
            key = yield self.expr
            yield maybe_blank << rbracket
            end = yield P.line_info
            return A.ComputedKey(self._location(start, end), key)

        @P.generate
        def fixed_key():
            id = yield self.field_id | self.string.map(A.Id.Field.from_string)
            return A.FixedKey(id.location, id)

        return fixed_key | computed_key

    @cached_property
    def field(self):
        @P.generate
        def field_sep():
            inherited = yield P.string("+").result(True).optional(False)
            yield maybe_blank
            visibility = yield P.from_enum(A.Visibility)
            return inherited, visibility

        @P.generate
        def fn_field_value():
            start = yield P.line_info
            params = yield self.params << maybe_blank
            inherited, visibility = yield field_sep << maybe_blank
            body = yield self.expr
            end = yield P.line_info
            return A.Fn(self._location(start, end), params, body), inherited, visibility

        @P.generate
        def expr_field_value():
            inherited, visibility = yield field_sep << maybe_blank
            value = yield self.expr
            return value, inherited, visibility

        @P.generate
        def gen():
            start = yield P.line_info
            key = yield self.field_key << maybe_blank
            value, inherited, visibility = yield expr_field_value | fn_field_value
            end = yield P.line_info
            location = self._location(start, end)
            return A.Field(location, key, value, visibility, inherited)

        return gen

    @cached_property
    def field_ref_id(self):
        return self._id(A.Id.FieldRef).desc(A.Id.FieldRef.__name__)

    @cached_property
    def for_spec(self):
        @P.generate
        def gen():
            start = yield P.line_info
            id = yield for_ >> blank >> self.var_id
            source = yield in_sep >> self.expr
            end = yield P.line_info
            return A.ForSpec(self._location(start, end), id, source)

        return gen

    @cached_property
    def function(self):
        @P.generate
        def gen():
            start = yield P.line_info
            yield P.string("function") << maybe_blank
            params: list[A.Param] = yield self.params << maybe_blank
            body: A.Expr = yield self.expr
            end = yield P.line_info
            return A.Fn(self._location(start, end), params, body)

        return gen.desc(A.Fn.__name__)

    @cached_property
    def if_(self):
        @P.generate
        def gen():
            start = yield P.line_info
            condition = yield if_ >> blank >> self.expr
            consequence = yield blank >> then_ >> blank >> self.expr
            alternative = yield (blank >> else_ >> blank >> self.expr).optional()
            end = yield P.line_info
            return A.If(self._location(start, end), condition, consequence, alternative)

        return gen

    @cached_property
    def if_spec(self):
        @P.generate
        def gen():
            start = yield P.line_info
            condition = yield if_ >> blank >> self.expr
            end = yield P.line_info
            return A.IfSpec(self._location(start, end), condition)

        return gen

    def import_(self, type: A.ImportType):
        @P.generate
        def gen():
            start = yield P.line_info
            yield P.string(type.value) << blank
            importee: A.Str = yield self.string
            end = yield P.line_info
            return A.Import(
                self._location(start, end),
                type,
                A.Importee(importee.location, importee.value),
            )

        return gen.desc(A.Import.__name__)

    @cached_property
    def in_expr(self):
        @P.generate
        def gen():
            start = yield P.line_info
            lhs = yield self.shift_expr << maybe_blank << in_ << maybe_blank
            rhs = yield self.shift_expr
            end = yield P.line_info
            return A.Binary(self._location(start, end), B.In, lhs, rhs)

        return gen

    @cached_property
    def list_comp(self):
        @P.generate
        def gen():
            start = yield P.line_info
            expr = yield lbracket >> maybe_blank >> self.expr
            comp_specs = yield maybe_blank >> self.comp_spec << maybe_blank << rbracket
            for_spec, *comp_spec = comp_specs
            end = yield P.line_info
            return A.ListComp(self._location(start, end), expr, for_spec, comp_spec)

        return gen.desc(A.ListComp.__name__)

    @cached_property
    def local(self):
        @P.generate
        def gen():
            start = yield P.line_info
            yield local << blank
            binds = yield self.bind.sep_by(comma_sep)
            yield semicolon_sep
            body = yield self.expr
            end = yield P.line_info
            return A.Local(self._location(start, end), binds, body)

        return gen.desc(A.Local.__name__)

    @cached_property
    def mul_expr(self):
        return self.left_binary(self.unary, B.Multiply, B.Divide, B.Modulus)

    @cached_property
    def null(self):
        return self._atom("null", A.Null).desc(A.Null.__name__)

    @cached_property
    def num(self):
        bin = P.regex("0[bB]") >> P.regex("[01]+").map(partial(int, base=2))
        oct = P.regex("0[oO]") >> P.regex("[0-7]+").map(partial(int, base=8))
        hex = P.regex("0[xX]") >> P.regex("[0-9a-fA-F]+").map(partial(int, base=16))

        @P.generate
        def dec():
            sign = P.char_from("-+")
            zero = P.string("0")
            digit1 = P.regex("[1-9]")
            digits = P.regex("[0-9]").at_least(1).concat()
            maybe_digits = digits.optional("")

            signed_integer = sign.optional("") + digits
            exp = P.char_from("eE") + signed_integer
            maybe_exp = exp.optional("")
            integral = sign.optional("") + (zero | (digit1 + maybe_digits))
            frac = dot + maybe_digits
            maybe_frac = frac.optional("")

            value = yield integral + maybe_frac + maybe_exp
            return float(value)

        @P.generate
        def gen():
            start = yield P.line_info
            value = yield bin | oct | hex | dec
            end = yield P.line_info
            return A.Num(self._location(start, end), float(value))

        return gen.desc(A.Num.__name__)

    @cached_property
    def obj_member(self):
        @P.generate
        def obj_local():
            bind = yield local >> blank >> self.bind
            return bind

        @P.generate
        def gen():
            member = yield P.alt(self.field, obj_local, self.assert_)
            return member

        return gen

    @cached_property
    def object(self):
        @P.generate
        def gen():
            start = yield P.line_info
            _, members, maybe_comp_spec = yield enclosed(
                self.obj_member,
                open=lbrace,
                sep=comma,
                close=(self.comp_spec << maybe_blank).optional() << rbrace,
            )
            end = yield P.line_info

            binds: list[A.Bind] = []
            asserts: list[A.Assert] = []
            fields: list[A.Field] = []

            for member in members:
                match member:
                    case A.Bind() as m:
                        binds.append(m)
                    case A.Assert() as m:
                        asserts.append(m)
                    case A.Field() as m:
                        fields.append(m)

            match fields, maybe_comp_spec:
                # An object comprehension can have:
                #  - Exactly 1 field
                #  - At least 1 for-spec
                #  - 0 or more if-spec
                case [field], [A.ForSpec() as first_spec, *other_specs]:
                    location = self._location(start, end)
                    return A.ObjComp(
                        location,
                        field=field,
                        binds=binds,
                        asserts=asserts,
                        for_spec=first_spec,
                        comp_spec=other_specs,
                    )
                case _, None:
                    return A.Object(
                        self._location(start, end),
                        binds=binds,
                        asserts=asserts,
                        fields=fields,
                    )
                case _:
                    raise RuntimeError("Malformed object comprehension")

        return gen

    def operator(self, op: A.UnaryOp | A.BinaryOp):
        parser = P.string(op.value).result(op)

        match op:
            case B.Divide:
                return self.string_not_from("//", "/*") >> parser
            case B.LT:
                return self.string_not_from(B.LE.value, B.ShiftLeft.value) >> parser
            case B.GT:
                return self.string_not_from(B.GE.value, B.ShiftRight.value) >> parser
            case B.BitAnd:
                return self.string_not_from(B.And.value) >> parser
            case B.BitOr:
                return self.string_not_from("|||", B.Or.value) >> parser
            case U.Not:
                return self.string_not_from(B.NotEq.value) >> parser
            case _:
                return parser

    @cached_property
    def param(self):
        @P.generate
        def gen():
            start = yield P.line_info
            id = yield self.var_id
            default = yield (eq_sep >> self.expr).optional()
            end = yield P.line_info
            return A.Param(self._location(start, end), id, default)

        return gen.desc(A.Param.__name__)

    @cached_property
    def param_ref_id(self):
        return self._id(A.Id.ParamRef).desc(A.Id.ParamRef.__name__)

    @cached_property
    def params(self):
        @P.generate
        def gen():
            _, params, _ = yield enclosed(self.param, lparen, comma, rparen)
            return params

        return gen

    @cached_property
    def paren(self):
        @P.generate
        def gen():
            yield lparen << maybe_blank
            expr = yield self.expr
            yield maybe_blank << rparen
            return expr

        return gen

    @cached_property
    def plus_expr(self):
        return self.left_binary(self.mul_expr, B.Plus, B.Minus)

    @cached_property
    def postfix(self):
        @P.generate
        def call():
            _, args, _ = yield enclosed(self.arg, lparen, comma, rparen)
            return partial(A.Call, args=args)

        @P.generate
        def field_access():
            ref = yield dot_sep >> self.field_ref_id
            return partial(A.FieldAccess, field=ref)

        @P.generate
        def slice():
            begin = yield lbracket >> maybe_blank >> self.expr
            end = None
            step = None

            maybe_colon = yield colon_sep.optional()
            if maybe_colon is not None:
                end = yield self.expr

                maybe_colon = yield colon_sep.optional()
                if maybe_colon is not None:
                    step = yield self.expr

            yield rbracket
            return partial(A.Slice, begin=begin, end=end, step=step)

        @P.generate
        def extend():
            obj = yield maybe_blank >> self.object
            return lambda location, lhs: A.Binary(location, op=B.Plus, lhs=lhs, rhs=obj)

        @P.generate
        def gen():
            start = yield P.line_info
            expr = yield self.primary
            ops = yield P.seq(field_access | call | slice | extend, P.line_info).many()

            def build(expr: A.AST, op: tuple[PostfixBuilder, LineInfo]) -> A.AST:
                fn, end = op
                return fn(self._location(start, end), expr)

            return reduce(build, ops, expr)

        return gen

    @cached_property
    def primary(self):
        return P.alt(
            self.array,
            self.assert_expr,
            self.boolean,
            self.dollar,
            self.function,
            self.if_,
            self.import_(A.ImportType.Bin),
            self.import_(A.ImportType.Default),
            self.import_(A.ImportType.Str),
            self.list_comp,
            self.local,
            self.null,
            self.num,
            self.object,
            self.paren,
            self.self_,
            self.string,
            self.super_,
            self.var_ref_id,
        )

    @cached_property
    def self_(self):
        return self._atom("self", A.Self).desc(A.Self.__name__)

    @cached_property
    def shift_expr(self):
        return self.left_binary(self.plus_expr, B.ShiftLeft, B.ShiftRight)

    def _inline_string(self, quote: str, verbatim: bool):
        open_quote = P.string(f"@{quote}") if verbatim else P.string(quote)
        closing_quote = P.string(quote)
        verbatim_esc = P.string(quote * 2).result(quote)
        esc = verbatim_esc if verbatim else (single_char_esc | codepoint_esc)
        any = P.regex(f"[^{quote}]", re.DOTALL)
        char = esc | any
        return open_quote >> char.many().concat() << closing_quote

    def _indented_text(self, verbatim: bool):
        @P.generate
        def gen():
            indent: str = yield inline_whitespace.at_least(1).concat()

            esc = single_char_esc | codepoint_esc
            char = P.regex(".") if verbatim else esc | P.regex(".")

            first_line: str = yield char.many().concat() << newline
            line = P.string(indent) >> char.many().concat() << newline
            lines: list[str] = yield line.many()
            lines.insert(0, first_line)

            return lines, indent

        return gen

    def _text_block(self, verbatim: bool):
        @P.generate
        def gen():
            # Text block starting quote with optional verbatim mark.
            yield P.string("@|||" if verbatim else "|||")

            # Starting quote variants:
            # - "|||": Preserves the last newline of the text block
            # - "|||-": Removes the last newline of the text block
            last_newline = yield P.string("-").result("").optional("\n") << newline

            # Optional indented text block lines. `lines` is a list of text block
            # lines without either the leading indentation or the trailing newline.
            lines, indent = yield self._indented_text(verbatim).optional(("", None))

            # When the indented text block is non-empty, the ending quote must not
            # start with the same indentation as the text block.
            no_indent = (
                P.peek(P.string(indent)).should_fail("different indentation")
                if indent
                else P.success(())
            )

            yield no_indent >> inline_whitespace.many() >> P.string("|||")

            return "\n".join(lines) + last_newline

        return gen

    @cached_property
    def string(self):
        def make_str(start: LineInfo, end: LineInfo, value: str):
            return A.Str(self._location(start, end), value)

        return (
            P.seq(
                start=P.line_info,
                value=(
                    self._inline_string("'", verbatim=False)
                    | self._inline_string('"', verbatim=False)
                    | self._text_block(verbatim=False)
                    | self._inline_string("'", verbatim=True)
                    | self._inline_string('"', verbatim=True)
                    | self._text_block(verbatim=True)
                ),
                end=P.line_info,
            )
            .combine_dict(make_str)
            .desc(A.Str.__name__)
        )

    def string_not_from(self, *strs: str):
        return P.seq(*(P.string(s).should_fail(f"not {s}") for s in strs))

    @cached_property
    def super_(self):
        return self._atom("super", A.Super).desc(A.Super.__name__)

    @cached_property
    def unary(self):
        @P.generate
        def gen():
            start = yield P.line_info
            op = yield self._op_from(*A.UnaryOp).optional()

            if op is None:
                operand = yield maybe_blank >> self.postfix
                return operand
            else:
                operand = yield self.unary
                end = yield P.line_info
                return A.Unary(self._location(start, end), op, operand)

        return gen

    @cached_property
    def var_id(self):
        return self._id(A.Id.Var).desc(A.Id.Var.__name__)

    @cached_property
    def var_ref_id(self):
        return self._id(A.Id.VarRef).desc(A.Id.VarRef.__name__)
