import dataclasses as D

import parsy as P

from joule.ast import URI, Anchor, Point, Span


@D.dataclass
class Mark:
    id: int
    open: bool
    close: bool

    def __post_init__(self):
        assert not self.open or not self.close


@D.dataclass
class MarkedSpan:
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

closed_mark = P.seq(
    id=uint,
    open=P.success(False),
    close=P.success(False),
).combine_dict(Mark)

mark = open_mark | close_mark | closed_mark

marked_span = P.seq(
    start=P.whitespace.optional() >> P.index,
    length=P.string("^").at_least(1).map(len),
    marks=mark.sep_by(P.string(","), min=1),
).combine_dict(MarkedSpan)

marked_spans = marked_span.at_least(1)


def parse_marked_spans(source: str) -> tuple[str, dict[int, Span]]:
    line_no = -1
    source_lines: list[str] = []
    open_marks: dict[int, Point] = {}
    spans: dict[int, Span] = {}

    for line in source.splitlines():
        if not line.strip().startswith("^"):
            line_no += 1
            source_lines.append(line)
        else:
            for span in marked_spans.parse(line):
                for mark in span.marks:
                    match mark:
                        # Opening mark like "1:".
                        case Mark(id, open=True, close=False):
                            assert id not in open_marks, f"Duplicate mark: {id}"
                            start = Point(line_no, span.start)
                            open_marks[id] = start

                        # Closing mark like ":1".
                        case Mark(id, open=False, close=True):
                            assert id in open_marks, f"Open mark not found: {id}"
                            start = open_marks[id]
                            end = Point(line_no, span.start + span.length)
                            spans[id] = Span(start, end)
                            open_marks.pop(id)

                        # Closed mark like "1"
                        case Mark(id, open=False, close=False):
                            start = Point(line_no, span.start)
                            end = Point(line_no, span.start + span.length)
                            spans[id] = Span(start, end)

                        case _:
                            raise RuntimeError(f"Invalid mark: mark={mark}")

    pending_marks = ", ".join([str(k) for k in open_marks.keys()])
    assert len(open_marks) == 0, f"Closing mark(s) missing: {pending_marks}"

    return "\n".join(source_lines), spans


def parse_marked_anchors(source: str, uri: URI) -> tuple[str, dict[int, Anchor]]:
    source, spans = parse_marked_spans(source)
    return source, {id: Anchor(uri, span) for id, span in spans.items()}
