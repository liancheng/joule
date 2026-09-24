import bisect
import dataclasses as D
import functools
from collections.abc import Callable
from functools import cached_property
from itertools import accumulate, chain
from textwrap import dedent

from rich.text import Text

from joule import trees as T
from joule.trees import Array
from tests.dsl.marked_span import parse_marked_spans


@D.dataclass(frozen=True)
class SpanDSL(T.Span):
    def __repr__(self) -> str:
        return super().__repr__()

    @staticmethod
    def atom(fn: Callable[[T.Span], T.TreeType]):
        @property
        def apply(self) -> T.TreeType:
            return fn(self)

        return apply

    dollar = atom(T.Dollar)
    null = atom(T.Null)
    self = atom(T.Self)
    super = atom(T.Super)

    @property
    def true(self) -> T.Bool:
        return T.Bool(self, True)

    @property
    def false(self) -> T.Bool:
        return T.Bool(self, False)

    def num(self, value: float) -> T.Num:
        return T.Num(self, float(value))

    def string(self, value: str) -> T.Str:
        return T.Str(self, value)

    def var(self, name: str) -> T.Id.Var:
        return T.Id.Var(self, name)

    def var_ref(self, name: str) -> T.Id.VarRef:
        return T.Id.VarRef(self, name)

    def field_ref(self, name: str) -> T.Id.FieldRef:
        return T.Id.FieldRef(self, name)

    def param_ref(self, name: str) -> T.Id.ParamRef:
        return T.Id.ParamRef(self, name)

    def static_key(self, name: str) -> T.StaticKey:
        return T.StaticKey(self, T.Id.Field(self, name))

    def computed_key(self, expr: T.Expr) -> T.ComputedKey:
        return T.ComputedKey(self, expr)

    def array(self, *values: T.Expr) -> T.Array:
        return Array(self, list(values))


def arg(value: T.Expr, name: T.Id.ParamRef | None = None) -> T.Arg:
    span = value.span if name is None else name.span.merge(value.span)
    return T.Arg(span, value, name)


def bind(var: T.Id.Var, value: T.Expr) -> T.Bind:
    return T.Bind(var.span.merge(value.span), var, value)


def field(
    key: T.FieldKey,
    value: T.Expr,
    inherited: bool = False,
    visibility: T.Visibility = T.Visibility.Default,
) -> T.Field:
    return T.Field(
        key.span.merge(value.span),
        key=key,
        value=value,
        inherited=inherited,
        visibility=visibility,
    )


def param(var: T.Id.Var, default: T.Expr | None = None) -> T.Param:
    span = var.span if default is None else var.span.merge(default.span)
    return T.Param(span, var, default)


class LineMap:
    def __init__(self, text: str) -> None:
        self.text = text

        # Computes the character offset of the first character in each line, used for
        # conversions between 2D points and 1D offsets.
        #
        # NOTE: An LSP range is a half-open intervals `[start, end)`. All text lines but
        # the last end with a newline. Adding an EOF "\0" helps simplify computing the
        # line offsets array.
        lines = (text + "\0").splitlines(keepends=True)
        self.line_offsets: list[int] = list(accumulate(chain([0], map(len, lines))))

    def point_of(self, offset: int) -> T.Point:
        line = bisect.bisect_right(self.line_offsets, offset) - 1
        column = offset - self.line_offsets[line]
        return T.Point(line=line, column=column)

    def offset_of(self, point: T.Point) -> int:
        return self.line_offsets[point.line] + point.column


class FakeDocument(LineMap):
    def __init__(
        self,
        text: str,
        uri: str = "file:///tmp/test.jsonnet",
        marks: bool = True,
    ) -> None:
        text = dedent(text)
        text, self.spans = parse_marked_spans(text) if marks else (text, {})
        super().__init__(text)
        self.uri = uri
        self.document = T.Tree.from_source(text).to(T.Document)
        self.body = self.document.body

    @cached_property
    def span(self) -> SpanDSL:
        return SpanDSL(
            self.point_of(0),
            self.point_of(len(self.text)),
        )

    def at(self, *marks: int) -> SpanDSL:
        merged_span = functools.reduce(
            T.Span.merge,
            (self.spans[mark] for mark in marks),
        )

        return SpanDSL(merged_span.start, merged_span.end)

    def start_of(self, mark: int) -> T.Point:
        return self.at(mark).start

    def end_of(self, mark: int) -> T.Point:
        return self.at(mark).end

    def highlight(self, spans: tuple[T.Span, str] | list[tuple[T.Span, str]]) -> Text:
        """Renders the Jsonnet document with given text ranges highlighted.

        The document is rendered with its URI, a top ruler, an optional bottom ruler
        for long documents, and a line number gutter:

        ```plaintext
        file:///tmp/test.jsonnet    <-- Document URI
           0    5   10   15         <-- Top ruler
          '|''''|''''|''''|'''
        0 |local x = { f: 1 };
        1 |local y = x.f;
        2 |y + 1
        ^^
          Line number gutter
        ```

        NOTE: To be consistent with LSP, both line and column numbers are 0 based.
        """

        def offset_of(pos: T.Point) -> int:
            return self.line_offsets[pos.line] + pos.column

        if isinstance(spans, tuple):
            spans = [spans]

        styled = Text.styled
        rendered = []

        uri_line = styled(self.uri, "grey50")
        rendered.append(uri_line)

        # Renders the ranges.
        rendered_source = styled(self.text, "default")
        for span, style in spans:
            rendered_source.stylize(
                style,
                start=offset_of(span.start),
                end=offset_of(span.end),
            )

        raw_lines = self.text.splitlines()
        width = max(map(len, raw_lines))
        height = len(raw_lines)

        # The width of the line number gutter equals to the max width of the line
        # numbers plus one (for a padding space).
        line_no_width = len(str(height))
        gutter_width = line_no_width + 1

        def render_ruler(width: int, left_padding: int) -> list[Text]:
            # Assuming that the document has 10 lines with a max line width of 18, to
            # render a ruler, produces a sequence with step 5 first:
            #
            #   [0, 5, 10, 15]
            #
            every_5_chars = range(0, (width - 1) // 5 * 5 + 1, 5)

            # Prints each number with a width of 5, right aligned ("." for space):
            #
            #   ["....0", "....5", "...10", "...15"]
            #
            header_segs = [f"{i:>5}" for i in every_5_chars]

            # Joins the segments and chops off the leading spaces, producing:
            #
            #   ".0....5...10...15"
            #
            # The leading space is due to column numbers being 0 based.
            header_line = styled("".join(header_segs)[3:], "grey50")

            # Produces the guide line according to the max line width, e.g.:
            #
            #   "'|''''|''''|''''|''"
            #
            # Again, the leading "'" is due to column numbers being 0 based.
            guide_line = styled(("'|'''" * (width // 5 + 1))[: width + 1], "grey50")

            # Adds left padding for the line number gutter. For a document with 10
            # lines, the gutter width is 3:
            #
            #   "....0....5...10...15"
            #   "...'|''''|''''|''''|'''"
            #
            header_line.pad_left(left_padding)
            guide_line.pad_left(left_padding)

            return [header_line, guide_line]

        # Renders a top horizontal ruler.
        ruler_lines = render_ruler(width, gutter_width)
        rendered.extend(ruler_lines)

        # Renders source lines with line numbers.
        for i, line in enumerate(rendered_source.split()):
            line_no = styled(f"{i:>{line_no_width}} |", "grey50")
            rendered.append(line_no + line)

        # Renders a bottom horizontal ruler for long documents.
        if height > 5:
            rendered.extend(ruler_lines)

        return Text("\n").join(rendered)
