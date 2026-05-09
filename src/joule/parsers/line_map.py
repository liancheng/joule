import bisect
from itertools import accumulate, chain

from joule import trees as T


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
