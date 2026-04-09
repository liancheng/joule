import dataclasses as D

import lsprotocol.types as L
import parsy as P

from joule.ast import URI


@D.dataclass
class Mark:
    id: int | None
    open: bool
    close: bool

    def __post_init__(self):
        if self.open:
            assert self.id is not None
            assert not self.close


@D.dataclass
class MarkedRange:
    start: int
    length: int
    marks: list[Mark]


uint = P.string("0").map(int) | (P.regex("[1-9]") + P.regex("[0-9]*")).map(int)

open_mark = P.seq(
    id=uint,
    open=P.string(":").result(True),
    close=P.success(False),
).combine_dict(Mark)

close_mark = P.seq(
    open=P.success(False),
    close=P.string(":").result(True),
    id=uint,
).combine_dict(Mark)

close_last = P.seq(
    id=P.success(None),
    open=P.success(False),
    close=P.string(":").result(True),
).combine_dict(Mark)

closed_mark = P.seq(
    id=uint,
    open=P.success(False),
    close=P.success(False),
).combine_dict(Mark)

mark = open_mark | close_mark | close_last | closed_mark

marked_range = P.seq(
    start=P.whitespace.optional() >> P.index,
    length=P.string("^").at_least(1).map(len),
    marks=mark.sep_by(P.string(","), min=1),
).combine_dict(MarkedRange)

marked_ranges = marked_range.at_least(1)


def parse_marked_ranges(source: str) -> tuple[str, dict[int, L.Range]]:
    line_no = -1
    source_lines: list[str] = []
    open_marks: dict[int, L.Position] = {}
    last: int | None = None
    ranges: dict[int, L.Range] = {}

    for line in source.splitlines():
        try:
            for span in marked_ranges.parse(line):
                for mark in span.marks:
                    # Opening mark like "1:".
                    if mark.open and mark.id is not None:
                        assert mark.id not in open_marks, f"Duplicate mark: {mark.id}"
                        start_pos = L.Position(line_no, span.start)
                        open_marks[mark.id] = start_pos
                        last = mark.id

                    # Closing mark like ":1".
                    elif mark.close and mark.id:
                        assert mark.id in open_marks, f"Open mark not found: {mark.id}"
                        start_pos = open_marks[mark.id]
                        end_pos = L.Position(line_no, span.start + span.length)
                        ranges[mark.id] = L.Range(start_pos, end_pos)
                        open_marks.pop(mark.id)

                    # Colon mark ":", closing the last mark with ID.
                    elif mark.close and last:
                        start_pos = open_marks[last]
                        end_pos = L.Position(line_no, span.start + span.length)
                        ranges[last] = L.Range(start_pos, end_pos)
                        open_marks.pop(last)
                        last = None

                    # Closed mark like "1".
                    elif mark.id:
                        start_pos = L.Position(line_no, span.start)
                        end_pos = L.Position(line_no, span.start + span.length)
                        ranges[mark.id] = L.Range(start_pos, end_pos)

                    else:
                        assert False, f"Invalid mark: mark={mark}, last={last}"

        except P.ParseError:
            line_no += 1
            source_lines.append(line)

    pending_marks = ", ".join([str(k) for k in open_marks.keys()])
    assert len(open_marks) == 0, f"Closing mark(s) missing: {pending_marks}"

    return "\n".join(source_lines), ranges


def parse_marked_locations(source: str, uri: URI) -> tuple[str, dict[int, L.Location]]:
    source, ranges = parse_marked_ranges(source)
    return source, {id: L.Location(uri, span) for id, span in ranges.items()}
