from typing import NamedTuple

import parsy as P

from joule.syntax.trees import Point, Span

__all__ = ["parse"]


class SpanMark(NamedTuple):
    start: int
    length: int
    ids: list[int]


SPAN_MARKS = (
    P.seq(
        start=P.whitespace.optional() >> P.index,
        length=P.string("^").at_least(1).map(len),
        ids=P.regex("0|[1-9][0-9]*").map(int).sep_by(P.string(","), min=1),
    )
    .combine_dict(SpanMark)
    .at_least(1)
)


SOURCE_LEADER = ":   "
MARK_LEADER = ">   "


def parse(source: str) -> tuple[str, dict[int, Span]]:
    line_no = -1
    source_lines: list[str] = []
    spans: dict[int, Span] = {}

    for line in source.splitlines():
        if line.startswith(SOURCE_LEADER):
            line_no += 1
            source_lines.append(line[4:])

        elif line.startswith(MARK_LEADER):
            span_marks: list[SpanMark] = SPAN_MARKS.parse(line[len(MARK_LEADER) :])
            spans |= {
                mark_id: Span(
                    Point.pack(line_no, mark.start),
                    Point.pack(line_no, mark.start + mark.length),
                )
                for mark in span_marks
                for mark_id in mark.ids
            }

        else:
            raise ValueError(
                "Each line in a document with marked spans annotations must start "
                'with either ":   " for a source line or ">   " for an annotated line.'
            )

    return "\n".join(source_lines), spans
