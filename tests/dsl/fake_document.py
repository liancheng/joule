from itertools import accumulate, chain

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
    CompSpec,
    ComputedKey,
    Document,
    Dollar,
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
from joule.model import ScopeResolver
from joule.parsing import parse_jsonnet
from joule.maybe import head, must

from .marked_range import parse_marked_locations


class FakeDocument:
    def __init__(self, source: str, uri: str = "file:///tmp/test.jsonnet") -> None:
        self.uri = uri
        self.source, self.locations = parse_marked_locations(source, uri)
        self.cst = parse_jsonnet(self.source)
        self.ast = ScopeResolver().resolve(Document.from_cst(self.uri, self.cst))
        self.body = self.ast.body
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

    @property
    def location(self) -> L.Location:
        return self.body.location

    def at(self, mark: int) -> L.Location:
        return self.locations[mark]

    def start_of(self, mark: int) -> L.Position:
        return self.at(mark).range.start

    def end_of(self, mark: int) -> L.Position:
        return self.at(mark).range.end

    def query_one(self, query: T.Query, capture: str) -> AST:
        node = head(T.QueryCursor(query).captures(self.cst).get(capture, []))
        return AST.from_cst(self.uri, node)

    def node_at(self, target: int | L.Position | L.Range) -> AST:
        if isinstance(target, int):
            target = self.at(target).range
        return must(self.body.node_at(target))

    def offset_of(self, pos: L.Position) -> int:
        return self.line_offsets[pos.line] + pos.character

    def highlight(
        self, ranges: tuple[L.Range, str] | list[tuple[L.Range, str]]
    ) -> Text:
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
                start=self.offset_of(span.start),
                end=self.offset_of(span.end),
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

    def var(self, *, at: int, name: str) -> Id.Var:
        return Id.Var(self.at(at), name)

    def var_ref(self, *, at: int, name: str) -> Id.VarRef:
        return Id.VarRef(self.at(at), name)

    def field_ref(self, *, at: int, name: str) -> Id.FieldRef:
        return Id.FieldRef(self.at(at), name)

    def param_ref(self, *, at: int, name: str) -> Id.ParamRef:
        return Id.ParamRef(self.at(at), name)

    def fixed_key(self, *, at: int, name: str) -> FixedKey:
        return FixedKey(self.at(at), Id.Field(self.at(at), name))

    def num(self, *, at: int, value: float | int) -> Num:
        return Num(self.at(at), float(value))

    def true(self, *, at: int) -> Bool:
        return Bool(self.at(at), True)

    def false(self, *, at: int) -> Bool:
        return Bool(self.at(at), False)

    def string(self, *, at: int, value: str) -> Str:
        return Str(self.at(at), value)

    def computed_key(self, *, at: int, expr: Expr) -> ComputedKey:
        return ComputedKey(self.at(at), expr)

    def fn(self, *, at: int, params: list[Param], body: Expr) -> Fn:
        return Fn(self.at(at), params, body)

    def call(self, *, at: int, fn: Expr, args: list[Arg]) -> Call:
        return Call(self.at(at), fn, args)

    def array(self, *, at: int, values: list[Expr]) -> Array:
        return Array(self.at(at), values)

    def object(self, *, at: int, members: list[Bind | Assert | Field] = []) -> Object:
        binds = []
        asserts = []
        fields = []

        for ast in members:
            match ast:
                case Bind():
                    binds.append(ast)
                case Assert():
                    asserts.append(ast)
                case Field():
                    fields.append(ast)

        return Object(self.at(at), binds, asserts, fields)

    def if_(self, *, at: int, condition: Expr) -> IfSpec:
        return IfSpec(self.at(at), condition)

    def for_(self, *, at: int, id: Id.Var, source: Expr) -> ForSpec:
        return ForSpec(self.at(at), id, source)

    def assert_(
        self, *, at: int, condition: Expr, message: Expr | None = None
    ) -> Assert:
        return Assert(self.at(at), condition, message)

    def local(self, *, at: int, binds: list[Bind], body: Expr) -> Local:
        return Local(self.at(at), binds, body)

    def import_(self, *, at: int, path: Str) -> Import:
        return Import(self.at(at), "import", path)

    def importbin(self, *, at: int, path: Str) -> Import:
        return Import(self.at(at), "importbin", path)

    def importstr(self, *, at: int, path: Str) -> Import:
        return Import(self.at(at), "importstr", path)

    def list_comp(
        self,
        *,
        at: int,
        expr: Expr,
        for_spec: ForSpec,
        comp_spec: CompSpec = [],
    ) -> ListComp:
        return ListComp(self.at(at), expr, for_spec, comp_spec)

    def slice(
        self,
        *,
        at: int,
        expr: Expr,
        begin: Expr,
        end: Expr | None = None,
        step: Expr | None = None,
    ) -> Slice:
        return Slice(self.at(at), expr, begin, end, step)

    def element_at(
        self,
        *,
        at: int,
        collection: Expr,
        key: Expr,
    ) -> Slice:
        return Slice(self.at(at), collection, key)

    def dollar(self, *, at: int) -> Dollar:
        return Dollar(self.at(at))
