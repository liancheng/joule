from functools import cached_property
from textwrap import dedent

from joule import trees as T
from joule.maybe import must
from joule.parsers import LineMap
from joule.parsers.jsonnet import parse_document
from joule.services.analyzer import Analyzer

from . import SpanDSL
from .marked_spans import parse_marked_spans


class FakeFile(LineMap):
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


class FakeDocument(FakeFile):
    def __init__(self, source: str, uri: str = "file:///tmp/test.jsonnet") -> None:
        super().__init__(source, uri)
        self.document: T.Document = Analyzer.analyze(parse_document(self.text, uri))
        self.body = self.document.body

    def node_at(self, mark: int) -> T.Tree:
        return must(self.document.node_at(self.at(mark)))
