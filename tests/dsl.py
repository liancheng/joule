import re
from itertools import accumulate, chain
from pathlib import Path
from textwrap import dedent

import lsprotocol.types as L
import tree_sitter as T
from rich.text import Text

from joule.ast import (
    AST,
    Arg,
    Array,
    Assert,
    Bind,
    Bool,
    Call,
    ComputedKey,
    Document,
    Expr,
    Field,
    FixedKey,
    Fn,
    ForSpec,
    Id,
    IfSpec,
    Import,
    ListComp,
    Local,
    Num,
    Object,
    Param,
    Slice,
    Str,
)
from joule.parsing import parse_jsonnet
from joule.server import WorkspaceIndex
from joule.util import head, maybe

LOCATION_MARK_PATTERN = re.compile(
    dedent(
        """\
        (?P<indent>[ ]*)
        (?P<range>\\^+)
        (?P<mark>:?[a-zA-Z0-9-_.]+:?)
        """
    ),
    re.VERBOSE,
)

LOCATION_MARK_LINE_PATTERN = re.compile(
    f"({LOCATION_MARK_PATTERN.pattern})+",
    re.VERBOSE,
)


def side_by_side(lhs: Text | str, rhs: Text | str) -> Text:
    if isinstance(lhs, str):
        lhs = Text(lhs)

    if isinstance(rhs, str):
        rhs = Text(rhs)

    lhs_lines = lhs.split()
    rhs_lines = rhs.split()

    empty = Text.styled("", "default")
    shorter = lhs_lines if len(lhs_lines) < len(rhs_lines) else rhs_lines
    shorter.extend([empty] * abs(len(lhs_lines) - len(rhs_lines)))

    max_width = max(map(len, lhs.plain.splitlines()))
    sep = Text.styled(" : ", "grey50")

    return Text("\n").join(
        [
            lhs_line + padding + sep + rhs_line
            for lhs_line, rhs_line in zip(lhs_lines, rhs_lines)
            if (padding := " " * (max_width - len(lhs_line))) is not None
        ]
    )


class LocationDSL(L.Location):
    @property
    def start(self):
        return self.range.start

    @property
    def end(self):
        return self.range.end

    def id(self, name: str, kind: Id.Kind) -> Id:
        return Id(self, name, kind)

    def var(self, name: str) -> Id:
        return self.id(name, Id.Kind.Var)

    def var_ref(self, name: str) -> Id:
        return self.id(name, Id.Kind.VarRef)

    def arg_ref(self, name: str) -> Id:
        return self.id(name, Id.Kind.ArgRef)

    def num(self, value: float | int) -> Num:
        return Num(self, float(value))

    @property
    def true(self) -> Bool:
        return Bool(self, True)

    @property
    def false(self) -> Bool:
        return Bool(self, False)

    def string(self, value: str) -> Str:
        return Str(self, value)

    def fixed_id_key(self, name: str) -> FixedKey:
        return FixedKey(self, self.id(name, Id.Kind.Field))

    def fixed_str_key(self, name: str) -> FixedKey:
        return FixedKey(self, self.string(name))

    def computed_key(self, expr: Expr) -> ComputedKey:
        return ComputedKey(self, expr)

    def fn(self, params: list[Param], body: Expr) -> Fn:
        return Fn(self, params, body)

    def call(self, fn: Expr, args: list[Arg]) -> Call:
        return Call(self, fn, args)

    def slice(
        self,
        expr: Expr,
        begin: Expr,
        end: Expr | None = None,
        step: Expr | None = None,
    ) -> Slice:
        return Slice(self, expr, begin, end, step)

    def array(self, *values: Expr) -> Array:
        return Array(self, list(values))

    def object(self, *objinside: Bind | Assert | Field) -> Object:
        binds = []
        asserts = []
        fields = []

        for ast in objinside:
            match ast:
                case Bind():
                    binds.append(ast)
                case Assert():
                    asserts.append(ast)
                case Field():
                    fields.append(ast)

        return Object(self, binds, asserts, fields)

    def if_(self, condition: Expr) -> IfSpec:
        return IfSpec(self, condition)

    def for_(self, id: Id, container: Expr) -> ForSpec:
        return ForSpec(self, id, container)

    def assert_(self, condition: Expr, message: Expr | None = None) -> Assert:
        return Assert(self, condition, message)

    def local(self, binds: list[Bind], body: Expr) -> Local:
        return Local(self, binds, body)

    def import_(self, path: Str) -> Import:
        return Import(self, "import", path)

    def importbin(self, path: Str) -> Import:
        return Import(self, "importbin", path)

    def importstr(self, path: Str) -> Import:
        return Import(self, "importstr", path)

    def list_comp(
        self,
        expr: Expr,
        for_spec: ForSpec,
        *comp_spec: ForSpec | IfSpec,
    ) -> ListComp:
        return ListComp(self, expr, for_spec, list(comp_spec))


class FakeDocument:
    def __init__(self, source: str, uri: str = "file:///tmp/test.jsonnet") -> None:
        self.uri = uri
        self.source, self.locations = self._preprocess(source)
        self.root = parse_jsonnet(self.source)
        self.body = Document.from_cst(self.uri, self.root).body
        self.lines = self.source.splitlines(keepends=True)

        # Appends the last empty line if needed.
        if source.endswith("\n"):
            self.lines.append("")

        # Computes the character offset of the first character in each line, used for
        # converting line-character positions to offsets.
        self.line_offsets: list[int] = list(
            accumulate(chain([0], map(len, self.lines)))
        )

    def _preprocess(self, source: str) -> tuple[str, dict[str, L.Location]]:
        line_no = -1
        source_lines: list[str] = []
        open_marks: dict[str, L.Position] = {}
        locations: dict[str, L.Location] = {}

        for line in source.splitlines():
            if not re.fullmatch(LOCATION_MARK_LINE_PATTERN, line):
                line_no += 1
                source_lines.append(line)
            else:
                for m in list(re.finditer(LOCATION_MARK_PATTERN, line)):
                    start_char, end_char = m.span("range")
                    raw_mark: str = m.group("mark")
                    mark: str = raw_mark.strip(":")

                    match raw_mark.endswith(":"), raw_mark.startswith(":"):
                        # Opening marks like `x:`
                        case True, False:
                            assert mark not in open_marks, f"Duplicate mark: {mark}"
                            start = L.Position(line_no, start_char)
                            open_marks[mark] = start
                        # Closing marks like `:x`
                        case False, True:
                            assert mark in open_marks, f"No matching open mark: {mark}"
                            start = open_marks.pop(mark)
                            end = L.Position(line_no, end_char)
                            locations[mark] = L.Location(self.uri, L.Range(start, end))
                        # `x` and `:x:` are equivalent
                        case _:
                            start = L.Position(line_no, start_char)
                            end = L.Position(line_no, end_char)
                            locations[mark] = L.Location(self.uri, L.Range(start, end))

        assert len(open_marks) == 0, (
            f"Closing mark(s) missing: {', '.join(open_marks.keys())}"
        )

        return "\n".join(source_lines), locations

    @property
    def location(self) -> LocationDSL:
        return LocationDSL(self.body.location.uri, self.body.location.range)

    def at(self, mark: str) -> LocationDSL:
        location = self.locations[mark]
        return LocationDSL(location.uri, location.range)

    def query_one(self, query: T.Query, capture: str) -> AST:
        node = head(T.QueryCursor(query).captures(self.root).get(capture, []))
        return AST.from_cst(self.uri, node)

    def node_at(self, target: str | L.Position | L.Range) -> AST:
        match target:
            case str() as mark:
                target = self.locations[mark].range
            case _:
                pass

        return head(maybe(self.body.node_at(target)))

    def offset_of(self, pos: L.Position) -> int:
        return self.line_offsets[pos.line] + pos.character

    def highlight(self, ranges: list[L.Range], style: str):
        """Renders the Jsonnet document with given text ranges highlighted.

        The document is rendered with its URI, a top ruler, an optional bottom ruler
        for long documents, and a line number gutter:

        ```plaintext
        file:///tmp/test.jsonnet <-- Document URI
          0    5   10   15       <-- Top ruler
          |''''|''''|''''|''''
        1 |local x = { f: 1 };
        2 |local y = x.f;
        3 |y + 1
        ^^
          Line number gutter
        ```
        """
        styled = Text.styled
        rendered = []

        uri_line = styled(self.uri, "grey50")
        rendered.append(uri_line)

        # Renders the ranges.
        rendered_source = styled(self.source, "default")
        for r in ranges:
            rendered_source.stylize(
                style,
                start=self.offset_of(r.start),
                end=self.offset_of(r.end),
            )

        raw_lines = self.source.splitlines()
        width = max(map(len, raw_lines))
        height = len(raw_lines)
        line_no_width = len(str(height))
        gutter_width = line_no_width + 1

        def render_ruler(width: int, left_padding: int) -> list[Text]:
            # Assuming that the document has 10 lines with a max line width of 18, to
            # render a ruler, produces a sequence with step 5 first:
            #
            #   [0, 5, 10, 15]
            #
            every_5_chars = range(0, width // 5 * 5 + 1, 5)

            # Prints each number with a width of 5, right aligned ("." for space):
            #
            #   ["....0", "....5", "...10", "...15"]
            #
            header_segs = [f"{i:>5}" for i in every_5_chars]

            # Joins the segments and chops off the leading spaces, producing:
            #
            #   "0....5...10...15"
            #
            header_line = styled("".join(header_segs)[4:], "grey50")

            # Produces the guide line according to the max line width, e.g.:
            #
            #   "|''''|''''|''''|'''"
            #
            guide_line = styled(("|''''" * (width // 5 + 1))[: width + 1], "grey50")

            # Adds left padding for the line number gutter. E.g., if the document has 10
            # lines, the gutter witdh is the width of the max line number (2) plus one
            # (a padding space):
            #
            #   "...0....5...10...15"
            #   "...|''''|''''|''''|'''"
            #
            header_line.pad_left(left_padding)
            guide_line.pad_left(left_padding)

            return [header_line, guide_line]

        # Renders a top horizontal ruler.
        ruler_lines = render_ruler(width, gutter_width)
        rendered.extend(ruler_lines)

        # Renders source lines with line numbers.
        for i, line in enumerate(rendered_source.split()):
            line_no = styled(f"{i + 1:>{line_no_width}} |", "grey50")
            rendered.append(line_no + line)

        # Renders a bottom horizontal ruler for long documents.
        if height > 5:
            rendered.extend(ruler_lines)

        return Text("\n").join(rendered)


class FakeWorkspace:
    def __init__(self, root_uri: str, docs: list[FakeDocument]) -> None:
        self.docs = {doc.uri: doc for doc in docs}
        self.index = WorkspaceIndex(root_uri)

        for doc in docs:
            assert doc.uri not in self.index.docs
            self.index.load(doc.uri, doc.source)

    @staticmethod
    def single_doc(doc: FakeDocument) -> "FakeWorkspace":
        root_uri = Path.from_uri(doc.uri).absolute().parent.as_uri()
        return FakeWorkspace(root_uri, [doc])
