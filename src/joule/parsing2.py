import re
from functools import partial, reduce
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
        @P.generate
        def gen():
            start = yield P.line_info
            yield P.string(pattern)
            end = yield P.line_info
            return fn(self._location(start, end))

        return gen

    def _id(self, fn: IdBuilder):
        @P.generate
        def gen():
            start = yield P.line_info
            not_keywords = f"(?!{'|'.join(keywords)})"
            name = yield P.regex(rf"{not_keywords}[_a-zA-Z][_a-zA-Z0-9]*")
            end = yield P.line_info
            return fn(self._location(start, end), name)

        return gen

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

    @property
    def and_expr(self):
        return self.left_binary(self.bitor_expr, B.And).desc("and_expr")

    @property
    def arg(self):
        @P.generate
        def gen():
            start = yield P.line_info
            id = yield (self.param_ref_id << eq_sep).optional()
            value = yield self.expr
            end = yield P.line_info
            return A.Arg(self._location(start, end), value, id)

        return gen.desc(A.Arg.__name__)

    @property
    def array(self):
        @P.generate
        def gen():
            start = yield P.line_info
            _, values, _ = yield enclosed(self.expr, lbracket, comma, rbracket)
            end = yield P.line_info
            return A.Array(self._location(start, end), values)

        return gen.desc(A.Array.__name__)

    @property
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

    @property
    def assert_expr(self):
        @P.generate
        def gen():
            start = yield P.line_info
            assertion = yield self.assert_ << semicolon_sep
            body = yield self.expr
            end = yield P.line_info
            return A.AssertExpr(self._location(start, end), assertion, body)

        return gen.desc(A.AssertExpr.__name__)

    @property
    def bitand_expr(self):
        return self.left_binary(self.eq_expr, B.BitAnd)

    @property
    def bitor_expr(self):
        return self.left_binary(self.bitxor_expr, B.BitOr)

    @property
    def bitxor_expr(self):
        return self.left_binary(self.bitand_expr, B.BitXor)

    @property
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

    @property
    def boolean(self):
        true = self._atom("true", partial(A.Bool, value=True)).desc("true")
        false = self._atom("false", partial(A.Bool, value=False)).desc("false")
        return (true | false).desc(A.Bool.__name__)

    @property
    def cmp_expr(self):
        return self.in_expr | self.left_binary(self.shift_expr, B.LE, B.GE, B.LT, B.GT)

    @property
    def comp_spec(self):
        @P.generate
        def gen():
            for_spec = yield self.for_spec
            specs = yield (maybe_blank >> (self.if_spec | self.for_spec)).many()
            specs.insert(0, for_spec)
            return specs

        return gen

    @property
    def document(self):
        @P.generate
        def gen():
            body: A.Expr = yield self.expr
            return A.Document(body.location, body)

        return gen

    @property
    def dollar(self):
        return self._atom("$", A.Dollar).desc(A.Dollar.__name__)

    @property
    def eq_expr(self):
        return self.left_binary(self.cmp_expr, B.Eq, B.NotEq)

    @property
    def expr(self):
        return self.left_binary(self.and_expr, B.Or)

    @property
    def field_id(self):
        return self._id(A.Id.Field).desc(A.Id.Field.__name__)

    @property
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
            id = yield self.string.map(A.Id.Field.from_string) | self.field_id
            return A.FixedKey(id.location, id)

        return fixed_key | computed_key

    @property
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

    @property
    def field_ref_id(self):
        return self._id(A.Id.FieldRef).desc(A.Id.FieldRef.__name__)

    @property
    def for_spec(self):
        @P.generate
        def gen():
            start = yield P.line_info
            id = yield for_ >> blank >> self.var_id
            source = yield in_sep >> self.expr
            end = yield P.line_info
            return A.ForSpec(self._location(start, end), id, source)

        return gen

    @property
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

    @property
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

    @property
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

    @property
    def in_expr(self):
        @P.generate
        def gen():
            start = yield P.line_info
            lhs = yield self.shift_expr << maybe_blank << in_ << maybe_blank
            rhs = yield self.shift_expr
            end = yield P.line_info
            return A.Binary(self._location(start, end), B.In, lhs, rhs)

        return gen

    @property
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

    @property
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

    @property
    def mul_expr(self):
        return self.left_binary(self.unary, B.Multiply, B.Divide, B.Modulus)

    @property
    def null(self):
        return self._atom("null", A.Null).desc(A.Null.__name__)

    @property
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

    @property
    def obj_comp(self):
        @P.generate
        def gen():
            start = yield P.line_info
            _, members, comp_spec = yield enclosed(
                self.obj_member,
                open=lbrace,
                sep=comma,
                close=self.comp_spec << maybe_blank << rbrace,
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

            match fields, comp_spec:
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
                case _:
                    raise RuntimeError("Malformed object comprehension")

        return gen

    @property
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

    @property
    def object(self):
        @P.generate
        def gen():
            start = yield P.line_info
            _, members, _ = yield enclosed(self.obj_member, lbrace, comma, rbrace)
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

            return A.Object(
                self._location(start, end),
                binds=binds,
                asserts=asserts,
                fields=fields,
            )

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

    @property
    def param(self):
        @P.generate
        def gen():
            start = yield P.line_info
            id = yield self.var_id
            default = yield (eq_sep >> self.expr).optional()
            end = yield P.line_info
            return A.Param(self._location(start, end), id, default)

        return gen.desc(A.Param.__name__)

    @property
    def param_ref_id(self):
        return self._id(A.Id.ParamRef).desc(A.Id.ParamRef.__name__)

    @property
    def params(self):
        @P.generate
        def gen():
            _, params, _ = yield enclosed(self.param, lparen, comma, rparen)
            return params

        return gen

    @property
    def paren(self):
        @P.generate
        def gen():
            yield lparen << maybe_blank
            expr = yield self.expr
            yield maybe_blank << rparen
            return expr

        return gen

    @property
    def plus_expr(self):
        return self.left_binary(self.mul_expr, B.Plus, B.Minus)

    @property
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
            obj = yield maybe_blank >> (self.object | self.obj_comp)
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

    @property
    def primary(self):
        return (
            P.alt(
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
                self.obj_comp,
                self.object,
                self.paren,
                self.self_,
                self.string,
                self.super_,
            )
            | self.var_ref_id
        )

    @property
    def self_(self):
        return self._atom("self", A.Self).desc(A.Self.__name__)

    @property
    def shift_expr(self):
        return self.left_binary(self.plus_expr, B.ShiftLeft, B.ShiftRight)

    @property
    def string(self):
        @P.generate
        def gen():
            start = yield P.line_info
            verbatim: bool = yield P.string("@").result(True).optional(False)

            single_char_esc = P.alt(
                *(
                    P.string(f"\\{esc}").result(value)
                    for esc, value in zip("\"'\\/bnfrt", "\"'\\/\b\n\f\r\t")
                )
            )

            @P.generate
            def codepoint_esc():
                u = P.string("\\u")
                hex4 = P.regex("[0-9a-fA-F]{4}").map(partial(int, base=16))
                high: int = yield u >> hex4

                if 0xD800 <= high <= 0xDFFF:
                    # High 16 bit as surrogate: non-BMP code point
                    low: int = yield u >> hex4
                    return chr(0x10000 + (high - 0xD800) * 0x400 + (low - 0xDC00))
                else:
                    # BMP code point
                    return chr(high)

            def escape(quote: str):
                return (
                    P.string(quote * 2).result(quote).desc("escaped quote")
                    if verbatim and quote in ["'", '"']
                    else single_char_esc | codepoint_esc
                )

            @P.generate
            def inline_string():
                quote: str = yield P.char_from("\"'")
                end_quote = P.string(quote)

                esc = escape(quote)
                not_esc = esc.should_fail("not escaped character")
                not_quote = end_quote.should_fail("not quote")
                any = P.regex(f"[^{quote}]", re.DOTALL)

                char = esc | (not_esc >> not_quote >> any)
                content: str = yield char.many().concat() << end_quote
                return content

            @P.generate
            def indented_content():
                indent: str = yield inline_whitespace.at_least(1).concat()

                esc = single_char_esc | codepoint_esc
                not_esc = esc.should_fail("not escaped character")
                char = P.regex(".") if verbatim else esc | not_esc >> P.regex(".")

                first_line: str = yield char.many().concat() << newline
                line = P.string(indent) >> char.many().concat() << newline
                lines: list[str] = yield line.many()
                lines.insert(0, first_line)

                return lines, indent

            @P.generate
            def text_block():
                # Text block starting quote with optional verbatim mark.
                yield P.string("|||")

                # Starting quote variants:
                # - "|||": Preserves the last newline of the text block
                # - "|||-": Removes the last newline of the text block
                last_newline = yield P.string("-").result("").optional("\n") << newline

                # Optional indented text block lines. `lines` is a list of text block
                # lines without either the leading indentation or the trailing newline.
                lines, indent = yield indented_content.optional(("", None))

                # When the indented text block is non-empty, the ending quote must not
                # start with the same indentation as the text block.
                no_indent = (
                    P.peek(P.string(indent)).should_fail("different indentation")
                    if indent
                    else P.success(())
                )

                yield no_indent >> inline_whitespace.many() >> P.string("|||")

                return "\n".join(lines) + last_newline

            value = yield inline_string | text_block
            end = yield P.line_info
            return A.Str(self._location(start, end), value)

        return gen.desc(A.Str.__name__)

    def string_not_from(self, *strs: str):
        return P.seq(*(P.string(s).should_fail(f"not {s}") for s in strs))

    @property
    def super_(self):
        return self._atom("super", A.Super).desc(A.Super.__name__)

    @property
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

    @property
    def var_id(self):
        return self._id(A.Id.Var).desc(A.Id.Var.__name__)

    @property
    def var_ref_id(self):
        return self._id(A.Id.VarRef).desc(A.Id.VarRef.__name__)
