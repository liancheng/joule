from functools import cached_property
from itertools import accumulate, chain

import lsprotocol.types as L
from rich.text import Text

from joule import ast as A
from joule.maybe import must
from joule.model import ScopeResolver
from joule.parsing import parse_jsonnet

from .marked_range import parse_marked_locations


class FakeFile:
    def __init__(self, source: str, uri: str = "file:///tmp/test.jsonnet") -> None:
        self.uri = uri
        self.source, self.locations = parse_marked_locations(source, uri)
        self.lines = self.source.splitlines(keepends=True)

        # When the source ends with a newline, `str.splitlines` does not preserve the
        # last empty line.
        if source.endswith("\n"):
            self.lines.append("")

        # Computes the character offset of the first character in each line, used for
        # converting 2D positions to 1D offsets.
        self.line_offsets: list[int] = list(
            accumulate(chain([0], map(len, self.lines)))
        )

    @cached_property
    def location(self) -> L.Location:
        return L.Location(
            self.uri,
            L.Range(
                L.Position(0, 0),
                L.Position(len(self.lines) - 1, len(self.lines[-1])),
            ),
        )

    def at(self, mark: int) -> L.Location:
        return self.locations[mark]

    def start_of(self, mark: int) -> L.Position:
        return self.at(mark).range.start

    def end_of(self, mark: int) -> L.Position:
        return self.at(mark).range.end

    def highlight(
        self, ranges: tuple[L.Range, str] | list[tuple[L.Range, str]]
    ) -> Text:
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

        def offset_of(pos: L.Position) -> int:
            return self.line_offsets[pos.line] + pos.character

        if isinstance(ranges, tuple):
            ranges = [ranges]

        styled = Text.styled
        rendered = []

        uri_line = styled(self.uri, "grey50")
        rendered.append(uri_line)

        # Renders the ranges.
        rendered_source = styled(self.source, "default")
        for span, style in ranges:
            rendered_source.stylize(
                style,
                start=offset_of(span.start),
                end=offset_of(span.end),
            )

        raw_lines = self.source.splitlines()
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


class FakeDocument(FakeFile):
    def __init__(self, source: str, uri: str = "file:///tmp/test.jsonnet") -> None:
        super().__init__(source, uri)
        self.cst = parse_jsonnet(self.source)
        self.ast = ScopeResolver().resolve(A.Document.from_cst(self.uri, self.cst))
        self.body = self.ast.body

    @cached_property
    def location(self) -> L.Location:
        return self.body.location

    def node_at(self, target: int | L.Position | L.Range) -> A.AST:
        if isinstance(target, int):
            target = self.at(target).range
        return must(self.body.node_at(target))
