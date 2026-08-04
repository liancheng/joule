import bisect
import dataclasses as D
from collections.abc import Callable
from functools import cached_property
from itertools import accumulate, chain
from textwrap import dedent

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

    def array(self, *values: T.Expr) -> T.Array:
        return Array(self, list(values))


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
        return T.Point(line=line, character=column)

    def offset_of(self, point: T.Point) -> int:
        return self.line_offsets[point.line] + point.character


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

    def at(self, mark: int) -> SpanDSL:
        span = self.spans[mark]
        return SpanDSL(span.start, span.end)

    def start_of(self, mark: int) -> T.Point:
        return self.at(mark).start

    def end_of(self, mark: int) -> T.Point:
        return self.at(mark).end
